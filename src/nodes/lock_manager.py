"""
Distributed Lock Manager with deadlock detection
"""
import asyncio
import time
import logging
from typing import Dict, Set, Optional, List
from enum import Enum
from dataclasses import dataclass
from .base_node import BaseNode
from ..communication import Message, MessageType

logger = logging.getLogger(__name__)

class LockType(Enum):
    """Types of distributed locks"""
    SHARED = "shared"
    EXCLUSIVE = "exclusive"

@dataclass
class Lock:
    """Lock information"""
    lock_id: str
    lock_type: LockType
    holders: Set[str]  # Node IDs holding the lock
    waiters: List[tuple]  # (node_id, lock_type, timestamp)
    created_at: float
    expires_at: Optional[float] = None
    
class LockManager(BaseNode):
    """
    Distributed Lock Manager using Raft consensus
    Supports shared and exclusive locks with deadlock detection
    """
    
    def __init__(self, node_id: str, host: str, port: int, cluster_nodes: list,
                 lock_timeout: int = 30, deadlock_check_interval: int = 5):
        super().__init__(node_id, host, port, cluster_nodes)
        
        self.lock_timeout = lock_timeout
        self.deadlock_check_interval = deadlock_check_interval
        
        # Lock state
        self.locks: Dict[str, Lock] = {}
        self.node_locks: Dict[str, Set[str]] = {}  # node_id -> set of lock_ids
        
        # Deadlock detection
        self.wait_for_graph: Dict[str, Set[str]] = {}  # node -> nodes it's waiting for
        
        # Register additional handlers
        self._register_lock_handlers()
        
        logger.info(f"LockManager {node_id} initialized")
        
    def _register_lock_handlers(self):
        """Register lock-specific message handlers"""
        self.message_passing.handler.register_handler(
            MessageType.LOCK_REQUEST,
            self._handle_lock_request
        )
        self.message_passing.handler.register_handler(
            MessageType.LOCK_RELEASE,
            self._handle_lock_release
        )
        
    async def start(self):
        """Start lock manager"""
        await super().start()
        
        # Start deadlock detection
        asyncio.create_task(self._deadlock_detection_loop())
        
        # Start lock cleanup
        asyncio.create_task(self._lock_cleanup_loop())
        
        logger.info(f"LockManager {self.node_id} started")
        
    async def acquire_lock(self, lock_id: str, lock_type: LockType = LockType.EXCLUSIVE,
                          timeout: Optional[float] = None) -> bool:
        """
        Acquire a distributed lock
        """
        timeout = timeout or self.lock_timeout
        start_time = time.time()
        
        logger.info(f"Node {self.node_id} requesting {lock_type.value} lock on {lock_id}")
        
        # Submit lock request through Raft
        command = {
            'op': 'acquire_lock',
            'lock_id': lock_id,
            'lock_type': lock_type.value,
            'node_id': self.node_id,
            'timeout': timeout,
            'timestamp': time.time()
        }
        
        if not await self.submit_command(command):
            # Not leader, forward to leader
            return await self._forward_lock_request(lock_id, lock_type, timeout)
            
        # Wait for lock to be granted
        while time.time() - start_time < timeout:
            if self._check_lock_granted(lock_id):
                logger.info(f"Lock {lock_id} granted to {self.node_id}")
                return True
            await asyncio.sleep(0.1)
            
        logger.warning(f"Lock acquisition timeout for {lock_id} by {self.node_id}")
        return False
        
    async def release_lock(self, lock_id: str) -> bool:
        """Release a distributed lock"""
        logger.info(f"Node {self.node_id} releasing lock {lock_id}")
        
        command = {
            'op': 'release_lock',
            'lock_id': lock_id,
            'node_id': self.node_id,
            'timestamp': time.time()
        }
        
        if not await self.submit_command(command):
            return await self._forward_lock_release(lock_id)
            
        return True
        
    def _check_lock_granted(self, lock_id: str) -> bool:
        """Check if lock is granted to this node"""
        lock = self.locks.get(lock_id)
        if not lock:
            return False
        return self.node_id in lock.holders
        
    async def _handle_lock_request(self, message: Message) -> Dict[str, any]:
        """Handle lock request message"""
        lock_id = message.data['lock_id']
        lock_type = LockType(message.data['lock_type'])
        requester = message.data['node_id']
        
        # Try to grant lock
        granted = self._try_grant_lock(lock_id, requester, lock_type)
        
        return {
            'granted': granted,
            'lock_id': lock_id
        }
        
    async def _handle_lock_release(self, message: Message) -> Dict[str, any]:
        """Handle lock release message"""
        lock_id = message.data['lock_id']
        releaser = message.data['node_id']
        
        self._release_lock_internal(lock_id, releaser)
        
        return {
            'status': 'released',
            'lock_id': lock_id
        }
        
    def _try_grant_lock(self, lock_id: str, node_id: str, lock_type: LockType) -> bool:
        """Try to grant a lock"""
        current_time = time.time()
        
        # Create lock if doesn't exist
        if lock_id not in self.locks:
            self.locks[lock_id] = Lock(
                lock_id=lock_id,
                lock_type=lock_type,
                holders=set(),
                waiters=[],
                created_at=current_time,
                expires_at=current_time + self.lock_timeout
            )
            
        lock = self.locks[lock_id]
        
        # Check if can grant lock
        if not lock.holders:
            # No current holders, grant lock
            lock.holders.add(node_id)
            lock.lock_type = lock_type
            self._add_node_lock(node_id, lock_id)
            return True
        elif lock.lock_type == LockType.SHARED and lock_type == LockType.SHARED:
            # Both shared, can grant
            lock.holders.add(node_id)
            self._add_node_lock(node_id, lock_id)
            return True
        else:
            # Must wait
            lock.waiters.append((node_id, lock_type, current_time))
            self._update_wait_for_graph(node_id, lock.holders)
            return False
            
    def _release_lock_internal(self, lock_id: str, node_id: str):
        """Internal lock release"""
        if lock_id not in self.locks:
            return
            
        lock = self.locks[lock_id]
        lock.holders.discard(node_id)
        self._remove_node_lock(node_id, lock_id)
        
        # Grant to waiting nodes if lock is now free
        if not lock.holders and lock.waiters:
            self._grant_to_waiters(lock_id)
            
        # Remove lock if no holders and no waiters
        if not lock.holders and not lock.waiters:
            del self.locks[lock_id]
            
    def _grant_to_waiters(self, lock_id: str):
        """Grant lock to waiting nodes"""
        lock = self.locks[lock_id]
        
        if not lock.waiters:
            return
            
        # Get first waiter
        first_waiter = lock.waiters[0]
        node_id, lock_type, _ = first_waiter
        
        # Grant to first waiter
        lock.holders.add(node_id)
        lock.lock_type = lock_type
        lock.waiters.pop(0)
        self._add_node_lock(node_id, lock_id)
        
        # If shared lock, grant to other shared waiters
        if lock_type == LockType.SHARED:
            remaining_waiters = []
            for waiter_node, waiter_type, timestamp in lock.waiters:
                if waiter_type == LockType.SHARED:
                    lock.holders.add(waiter_node)
                    self._add_node_lock(waiter_node, lock_id)
                else:
                    remaining_waiters.append((waiter_node, waiter_type, timestamp))
            lock.waiters = remaining_waiters
            
    def _add_node_lock(self, node_id: str, lock_id: str):
        """Track locks held by node"""
        if node_id not in self.node_locks:
            self.node_locks[node_id] = set()
        self.node_locks[node_id].add(lock_id)
        
    def _remove_node_lock(self, node_id: str, lock_id: str):
        """Remove lock from node tracking"""
        if node_id in self.node_locks:
            self.node_locks[node_id].discard(lock_id)
            if not self.node_locks[node_id]:
                del self.node_locks[node_id]
                
    def _update_wait_for_graph(self, waiter: str, holders: Set[str]):
        """Update wait-for graph for deadlock detection"""
        self.wait_for_graph[waiter] = holders.copy()
        
    async def _deadlock_detection_loop(self):
        """Periodic deadlock detection"""
        while self.running:
            try:
                deadlocks = self._detect_deadlocks()
                if deadlocks:
                    logger.warning(f"Deadlocks detected: {deadlocks}")
                    await self._resolve_deadlocks(deadlocks)
                    
                await asyncio.sleep(self.deadlock_check_interval)
            except Exception as e:
                logger.error(f"Error in deadlock detection: {e}", exc_info=True)
                
    def _detect_deadlocks(self) -> List[List[str]]:
        """Detect deadlocks using cycle detection in wait-for graph"""
        deadlocks = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.wait_for_graph.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:]
                    deadlocks.append(cycle)
                    return True
                    
            rec_stack.remove(node)
            path.pop()
            return False
            
        for node in self.wait_for_graph:
            if node not in visited:
                dfs(node, [])
                
        return deadlocks
        
    async def _resolve_deadlocks(self, deadlocks: List[List[str]]):
        """Resolve detected deadlocks"""
        for cycle in deadlocks:
            # Abort youngest transaction in cycle
            youngest_node = max(cycle, key=lambda n: self._get_node_wait_time(n))
            logger.info(f"Aborting {youngest_node} to resolve deadlock")
            
            # Release all locks held by this node
            if youngest_node in self.node_locks:
                for lock_id in list(self.node_locks[youngest_node]):
                    self._release_lock_internal(lock_id, youngest_node)
                    
    def _get_node_wait_time(self, node_id: str) -> float:
        """Get wait time for a node"""
        min_wait_time = float('inf')
        for lock in self.locks.values():
            for waiter_node, _, timestamp in lock.waiters:
                if waiter_node == node_id:
                    min_wait_time = min(min_wait_time, timestamp)
        return min_wait_time
        
    async def _lock_cleanup_loop(self):
        """Clean up expired locks"""
        while self.running:
            try:
                current_time = time.time()
                expired_locks = []
                
                for lock_id, lock in self.locks.items():
                    if lock.expires_at and current_time > lock.expires_at:
                        expired_locks.append(lock_id)
                        
                for lock_id in expired_locks:
                    logger.warning(f"Lock {lock_id} expired, releasing")
                    del self.locks[lock_id]
                    
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in lock cleanup: {e}", exc_info=True)
                
    async def _forward_lock_request(self, lock_id: str, lock_type: LockType, 
                                   timeout: float) -> bool:
        """Forward lock request to leader"""
        # TODO: Implement forwarding to leader
        logger.warning("Lock forwarding not yet implemented")
        return False
        
    async def _forward_lock_release(self, lock_id: str) -> bool:
        """Forward lock release to leader"""
        # TODO: Implement forwarding to leader
        return False
        
    def get_lock_status(self) -> Dict[str, any]:
        """Get status of all locks"""
        return {
            'total_locks': len(self.locks),
            'locks': {
                lock_id: {
                    'type': lock.lock_type.value,
                    'holders': list(lock.holders),
                    'waiters': len(lock.waiters),
                    'created_at': lock.created_at
                }
                for lock_id, lock in self.locks.items()
            },
            'node_locks': {
                node_id: list(locks)
                for node_id, locks in self.node_locks.items()
            }
        }
