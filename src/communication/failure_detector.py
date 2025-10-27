"""
Failure detector for distributed systems
"""
import asyncio
import time
import logging
from typing import Dict, Set, Callable, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class NodeState(Enum):
    """Node state in failure detector"""
    ALIVE = "alive"
    SUSPECTED = "suspected"
    FAILED = "failed"
    UNKNOWN = "unknown"

class FailureDetector:
    """
    Adaptive failure detector based on heartbeat mechanism
    Implements φ accrual failure detector algorithm
    """
    
    def __init__(self, node_id: str, heartbeat_interval: float = 1.0, 
                 timeout_threshold: float = 5.0, phi_threshold: float = 8.0):
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval
        self.timeout_threshold = timeout_threshold
        self.phi_threshold = phi_threshold
        
        # Node states
        self.node_states: Dict[str, NodeState] = {}
        self.last_heartbeat: Dict[str, float] = {}
        self.heartbeat_history: Dict[str, list] = {}
        
        # Callbacks
        self.on_node_failed: Optional[Callable] = None
        self.on_node_recovered: Optional[Callable] = None
        
        # Monitoring
        self.running = False
        self.monitor_task = None
        
    async def start(self):
        """Start failure detector"""
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_nodes())
        logger.info(f"Failure detector started for node {self.node_id}")
        
    async def stop(self):
        """Stop failure detector"""
        self.running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Failure detector stopped")
        
    def register_node(self, node_id: str):
        """Register a node for monitoring"""
        if node_id not in self.node_states:
            self.node_states[node_id] = NodeState.UNKNOWN
            self.last_heartbeat[node_id] = time.time()
            self.heartbeat_history[node_id] = []
            logger.info(f"Registered node {node_id} for monitoring")
            
    def unregister_node(self, node_id: str):
        """Unregister a node from monitoring"""
        self.node_states.pop(node_id, None)
        self.last_heartbeat.pop(node_id, None)
        self.heartbeat_history.pop(node_id, None)
        logger.info(f"Unregistered node {node_id} from monitoring")
        
    def receive_heartbeat(self, node_id: str):
        """Record heartbeat from a node"""
        current_time = time.time()
        
        # Initialize if not registered
        if node_id not in self.node_states:
            self.register_node(node_id)
            
        # Update last heartbeat time
        last_time = self.last_heartbeat.get(node_id, current_time)
        interval = current_time - last_time
        
        # Update heartbeat history (keep last 100 intervals)
        if node_id not in self.heartbeat_history:
            self.heartbeat_history[node_id] = []
        self.heartbeat_history[node_id].append(interval)
        if len(self.heartbeat_history[node_id]) > 100:
            self.heartbeat_history[node_id].pop(0)
            
        self.last_heartbeat[node_id] = current_time
        
        # Update node state
        old_state = self.node_states.get(node_id)
        self.node_states[node_id] = NodeState.ALIVE
        
        # Trigger recovery callback if node was failed
        if old_state == NodeState.FAILED and self.on_node_recovered:
            asyncio.create_task(self.on_node_recovered(node_id))
            logger.info(f"Node {node_id} recovered")
            
    def calculate_phi(self, node_id: str) -> float:
        """
        Calculate phi value (suspicion level) for a node
        Higher phi means more suspicious
        """
        if node_id not in self.last_heartbeat:
            return float('inf')
            
        current_time = time.time()
        last_time = self.last_heartbeat[node_id]
        elapsed = current_time - last_time
        
        # Get heartbeat history
        history = self.heartbeat_history.get(node_id, [])
        if len(history) < 2:
            # Not enough data, use simple timeout
            return elapsed / self.timeout_threshold
            
        # Calculate mean and standard deviation
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            std_dev = 0.1  # Avoid division by zero
            
        # Calculate phi using normal distribution
        import math
        phi = -math.log10(max(0.001, 1 - (elapsed - mean) / (std_dev * math.sqrt(2))))
        
        return max(0, phi)
        
    def is_node_alive(self, node_id: str) -> bool:
        """Check if a node is considered alive"""
        return self.node_states.get(node_id) == NodeState.ALIVE
        
    def is_node_failed(self, node_id: str) -> bool:
        """Check if a node is considered failed"""
        return self.node_states.get(node_id) == NodeState.FAILED
        
    def get_alive_nodes(self) -> Set[str]:
        """Get set of alive nodes"""
        return {node_id for node_id, state in self.node_states.items() 
                if state == NodeState.ALIVE}
                
    def get_failed_nodes(self) -> Set[str]:
        """Get set of failed nodes"""
        return {node_id for node_id, state in self.node_states.items() 
                if state == NodeState.FAILED}
                
    async def _monitor_nodes(self):
        """Monitor nodes for failures"""
        while self.running:
            try:
                current_time = time.time()
                
                for node_id in list(self.node_states.keys()):
                    # Skip self
                    if node_id == self.node_id:
                        continue
                        
                    # Calculate phi value
                    phi = self.calculate_phi(node_id)
                    
                    old_state = self.node_states[node_id]
                    
                    # Determine new state based on phi
                    if phi >= self.phi_threshold:
                        new_state = NodeState.FAILED
                    elif phi >= self.phi_threshold * 0.5:
                        new_state = NodeState.SUSPECTED
                    else:
                        new_state = NodeState.ALIVE
                        
                    # Update state if changed
                    if new_state != old_state:
                        self.node_states[node_id] = new_state
                        logger.warning(f"Node {node_id} state changed: {old_state.value} -> {new_state.value} (phi={phi:.2f})")
                        
                        # Trigger failure callback
                        if new_state == NodeState.FAILED and self.on_node_failed:
                            await self.on_node_failed(node_id)
                            
                await asyncio.sleep(self.heartbeat_interval)
                
            except Exception as e:
                logger.error(f"Error in failure detector monitor: {e}", exc_info=True)
                await asyncio.sleep(1)
                
    def get_status(self) -> Dict[str, any]:
        """Get failure detector status"""
        return {
            'node_id': self.node_id,
            'monitored_nodes': len(self.node_states),
            'alive_nodes': len(self.get_alive_nodes()),
            'failed_nodes': len(self.get_failed_nodes()),
            'node_states': {node_id: state.value for node_id, state in self.node_states.items()}
        }
