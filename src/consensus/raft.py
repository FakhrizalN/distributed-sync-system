"""
Raft Consensus Algorithm Implementation
Implements leader election, log replication, and consensus
"""
import asyncio
import random
import time
import logging
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

class NodeRole(Enum):
    """Raft node roles"""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"

@dataclass
class LogEntry:
    """Raft log entry"""
    term: int
    index: int
    command: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'term': self.term,
            'index': self.index,
            'command': self.command,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogEntry':
        return cls(
            term=data['term'],
            index=data['index'],
            command=data['command'],
            timestamp=data.get('timestamp', time.time())
        )

class RaftNode:
    """
    Raft consensus node implementation
    """
    
    def __init__(self, node_id: str, cluster_nodes: List[str], 
                 election_timeout_range: tuple = (150, 300),
                 heartbeat_interval: int = 50):
        self.node_id = node_id
        self.cluster_nodes = [n for n in cluster_nodes if n != node_id]
        self.election_timeout_range = election_timeout_range
        self.heartbeat_interval = heartbeat_interval / 1000.0  # Convert to seconds
        
        # Persistent state
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log: List[LogEntry] = []
        
        # Volatile state
        self.commit_index = 0
        self.last_applied = 0
        self.role = NodeRole.FOLLOWER
        
        # Leader state
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}
        
        # Timing
        self.last_heartbeat_time = time.time()
        self.election_timeout = self._reset_election_timeout()
        
        # Tasks
        self.election_timer_task = None
        self.heartbeat_task = None
        self.running = False
        
        # Callbacks
        self.on_commit_callback = None
        self.message_sender = None
        
        logger.info(f"Raft node {node_id} initialized with {len(self.cluster_nodes)} peers")
        
    def _reset_election_timeout(self) -> float:
        """Reset election timeout to random value in range"""
        return random.uniform(
            self.election_timeout_range[0] / 1000.0,
            self.election_timeout_range[1] / 1000.0
        )
        
    async def start(self):
        """Start Raft node"""
        self.running = True
        self.election_timer_task = asyncio.create_task(self._election_timer())
        logger.info(f"Raft node {self.node_id} started as {self.role.value}")
        
    async def stop(self):
        """Stop Raft node"""
        self.running = False
        if self.election_timer_task:
            self.election_timer_task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        logger.info(f"Raft node {self.node_id} stopped")
        
    async def _election_timer(self):
        """Election timeout timer"""
        while self.running:
            try:
                await asyncio.sleep(0.01)  # Check every 10ms
                
                if self.role == NodeRole.LEADER:
                    continue
                    
                elapsed = time.time() - self.last_heartbeat_time
                
                if elapsed >= self.election_timeout:
                    logger.info(f"Election timeout reached for {self.node_id}, starting election")
                    await self._start_election()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in election timer: {e}", exc_info=True)
                
    async def _start_election(self):
        """Start leader election"""
        # Transition to candidate
        self.role = NodeRole.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.last_heartbeat_time = time.time()
        self.election_timeout = self._reset_election_timeout()
        
        logger.info(f"Node {self.node_id} starting election for term {self.current_term}")
        
        # Vote for self
        votes_received = 1
        votes_needed = (len(self.cluster_nodes) + 1) // 2 + 1
        
        # Request votes from other nodes
        if self.message_sender:
            vote_requests = []
            for peer in self.cluster_nodes:
                last_log_index = len(self.log) - 1 if self.log else 0
                last_log_term = self.log[-1].term if self.log else 0
                
                vote_request = {
                    'term': self.current_term,
                    'candidate_id': self.node_id,
                    'last_log_index': last_log_index,
                    'last_log_term': last_log_term
                }
                vote_requests.append(
                    self.message_sender(peer, 'request_vote', vote_request)
                )
            
            # Wait for responses
            if vote_requests:
                responses = await asyncio.gather(*vote_requests, return_exceptions=True)
                
                for response in responses:
                    if isinstance(response, dict) and response.get('vote_granted'):
                        votes_received += 1
                        
        # Check if won election
        if votes_received >= votes_needed and self.role == NodeRole.CANDIDATE:
            await self._become_leader()
        else:
            logger.info(f"Node {self.node_id} did not win election (got {votes_received}/{votes_needed} votes)")
            
    async def _become_leader(self):
        """Transition to leader"""
        self.role = NodeRole.LEADER
        logger.info(f"Node {self.node_id} became LEADER for term {self.current_term}")
        
        # Initialize leader state
        last_log_index = len(self.log)
        for peer in self.cluster_nodes:
            self.next_index[peer] = last_log_index
            self.match_index[peer] = 0
            
        # Start sending heartbeats
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        self.heartbeat_task = asyncio.create_task(self._send_heartbeats())
        
    async def _send_heartbeats(self):
        """Send periodic heartbeats as leader"""
        while self.running and self.role == NodeRole.LEADER:
            try:
                # Send append entries to all followers
                if self.message_sender:
                    tasks = []
                    for peer in self.cluster_nodes:
                        tasks.append(self._send_append_entries(peer))
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                        
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error sending heartbeats: {e}", exc_info=True)
                
    async def _send_append_entries(self, peer: str):
        """Send append entries RPC to a peer"""
        if not self.message_sender:
            return
            
        next_idx = self.next_index.get(peer, 0)
        prev_log_index = next_idx - 1
        prev_log_term = self.log[prev_log_index].term if prev_log_index >= 0 and prev_log_index < len(self.log) else 0
        
        # Get entries to send
        entries = []
        if next_idx < len(self.log):
            entries = [e.to_dict() for e in self.log[next_idx:]]
            
        append_entries_request = {
            'term': self.current_term,
            'leader_id': self.node_id,
            'prev_log_index': prev_log_index,
            'prev_log_term': prev_log_term,
            'entries': entries,
            'leader_commit': self.commit_index
        }
        
        try:
            response = await self.message_sender(peer, 'append_entries', append_entries_request)
            
            if isinstance(response, dict):
                # Update term if response has higher term
                if response.get('term', 0) > self.current_term:
                    await self._step_down(response['term'])
                    return
                    
                # Update indices if successful
                if response.get('success'):
                    if entries:
                        self.match_index[peer] = prev_log_index + len(entries)
                        self.next_index[peer] = self.match_index[peer] + 1
                else:
                    # Decrement next_index and retry
                    self.next_index[peer] = max(0, self.next_index[peer] - 1)
                    
        except Exception as e:
            logger.debug(f"Error sending append entries to {peer}: {e}")
            
    async def _step_down(self, new_term: int):
        """Step down from leader/candidate to follower"""
        logger.info(f"Node {self.node_id} stepping down from {self.role.value} (term {self.current_term} -> {new_term})")
        self.current_term = new_term
        self.role = NodeRole.FOLLOWER
        self.voted_for = None
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            self.heartbeat_task = None
            
    async def handle_request_vote(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle RequestVote RPC"""
        term = request['term']
        candidate_id = request['candidate_id']
        last_log_index = request['last_log_index']
        last_log_term = request['last_log_term']
        
        # Update term if necessary
        if term > self.current_term:
            await self._step_down(term)
            
        # Determine if should grant vote
        vote_granted = False
        
        if term < self.current_term:
            vote_granted = False
        elif self.voted_for is None or self.voted_for == candidate_id:
            # Check if candidate's log is at least as up-to-date
            our_last_log_index = len(self.log) - 1 if self.log else -1
            our_last_log_term = self.log[-1].term if self.log else 0
            
            log_ok = (last_log_term > our_last_log_term or 
                     (last_log_term == our_last_log_term and last_log_index >= our_last_log_index))
            
            if log_ok:
                vote_granted = True
                self.voted_for = candidate_id
                self.last_heartbeat_time = time.time()
                
        logger.debug(f"Node {self.node_id} {'granted' if vote_granted else 'denied'} vote to {candidate_id} for term {term}")
        
        return {
            'term': self.current_term,
            'vote_granted': vote_granted
        }
        
    async def handle_append_entries(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle AppendEntries RPC"""
        term = request['term']
        leader_id = request['leader_id']
        prev_log_index = request['prev_log_index']
        prev_log_term = request['prev_log_term']
        entries = request['entries']
        leader_commit = request['leader_commit']
        
        # Update term if necessary
        if term > self.current_term:
            await self._step_down(term)
            
        # Reset election timeout
        if term == self.current_term:
            self.last_heartbeat_time = time.time()
            if self.role != NodeRole.FOLLOWER:
                self.role = NodeRole.FOLLOWER
                
        # Reply false if term < currentTerm
        if term < self.current_term:
            return {
                'term': self.current_term,
                'success': False
            }
            
        # Check if log contains entry at prevLogIndex with prevLogTerm
        if prev_log_index >= 0:
            if prev_log_index >= len(self.log) or self.log[prev_log_index].term != prev_log_term:
                return {
                    'term': self.current_term,
                    'success': False
                }
                
        # Append new entries
        if entries:
            # Delete conflicting entries
            self.log = self.log[:prev_log_index + 1]
            
            # Append new entries
            for entry_dict in entries:
                entry = LogEntry.from_dict(entry_dict)
                self.log.append(entry)
                
        # Update commit index
        if leader_commit > self.commit_index:
            self.commit_index = min(leader_commit, len(self.log) - 1)
            await self._apply_committed_entries()
            
        return {
            'term': self.current_term,
            'success': True
        }
        
    async def _apply_committed_entries(self):
        """Apply committed log entries"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied]
            
            if self.on_commit_callback:
                try:
                    await self.on_commit_callback(entry.command)
                except Exception as e:
                    logger.error(f"Error applying committed entry: {e}", exc_info=True)
                    
    async def append_entry(self, command: Dict[str, Any]) -> bool:
        """Append entry to log (only for leader)"""
        if self.role != NodeRole.LEADER:
            logger.warning(f"Cannot append entry: not leader (role={self.role.value})")
            return False
            
        # Create log entry
        entry = LogEntry(
            term=self.current_term,
            index=len(self.log),
            command=command
        )
        self.log.append(entry)
        
        logger.info(f"Leader {self.node_id} appended entry {entry.index} to log")
        
        # Replicate to followers (will happen in next heartbeat)
        return True
        
    def is_leader(self) -> bool:
        """Check if this node is the leader"""
        return self.role == NodeRole.LEADER
        
    def get_leader_id(self) -> Optional[str]:
        """Get current leader ID"""
        if self.role == NodeRole.LEADER:
            return self.node_id
        return None
        
    def get_state(self) -> Dict[str, Any]:
        """Get current Raft state"""
        return {
            'node_id': self.node_id,
            'role': self.role.value,
            'term': self.current_term,
            'voted_for': self.voted_for,
            'log_length': len(self.log),
            'commit_index': self.commit_index,
            'last_applied': self.last_applied
        }
