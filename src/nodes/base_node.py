"""
Base node implementation for distributed system
Integrates Raft consensus, message passing, and failure detection
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from ..communication import MessagePassing, Message, MessageType, FailureDetector
from ..consensus import RaftNode
from ..utils import Config, metrics

logger = logging.getLogger(__name__)

class BaseNode:
    """
    Base node that integrates all core components
    """
    
    def __init__(self, node_id: str, host: str, port: int, cluster_nodes: list):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.cluster_nodes = cluster_nodes
        
        # Create node registry mapping node_id -> (host, port)
        self.node_registry = {}
        for node_info in cluster_nodes:
            if isinstance(node_info, dict):
                node_host = node_info.get('host')
                node_port = node_info.get('port')
                # Extract node_id from host (e.g., "node1" from "node1:5000")
                peer_node_id = node_host.split(':')[0] if ':' in node_host else node_host
                self.node_registry[peer_node_id] = (node_host, node_port)
        
        # Extract node IDs for Raft (e.g., ["node1", "node2", "node3"])
        raft_cluster_nodes = list(self.node_registry.keys())
        
        # Add self to cluster
        if node_id not in raft_cluster_nodes:
            raft_cluster_nodes.append(node_id)
            self.node_registry[node_id] = (host, port)
        
        # Initialize components
        self.message_passing = MessagePassing(node_id, host, port)
        self.raft = RaftNode(
            node_id=node_id,
            cluster_nodes=raft_cluster_nodes,
            election_timeout_range=(Config.RAFT_ELECTION_TIMEOUT_MIN, 
                                   Config.RAFT_ELECTION_TIMEOUT_MAX),
            heartbeat_interval=Config.RAFT_HEARTBEAT_INTERVAL
        )
        self.failure_detector = FailureDetector(
            node_id=node_id,
            heartbeat_interval=Config.RAFT_HEARTBEAT_INTERVAL / 1000.0
        )
        
        # State
        self.running = False
        self.state_machine: Dict[str, Any] = {}
        
        # Setup integrations
        self._setup_integrations()
        
        logger.info(f"BaseNode {node_id} initialized")
        
    def _setup_integrations(self):
        """Setup integrations between components"""
        # Register message handlers
        self.message_passing.handler.register_handler(
            MessageType.REQUEST_VOTE,
            self._handle_request_vote
        )
        self.message_passing.handler.register_handler(
            MessageType.APPEND_ENTRIES,
            self._handle_append_entries
        )
        self.message_passing.handler.register_handler(
            MessageType.HEARTBEAT,
            self._handle_heartbeat
        )
        self.message_passing.handler.register_handler(
            MessageType.PING,
            self._handle_ping
        )
        
        # Setup Raft callbacks
        self.raft.on_commit_callback = self._apply_to_state_machine
        self.raft.message_sender = self._send_raft_message
        
        # Setup failure detector callbacks
        self.failure_detector.on_node_failed = self._on_node_failed
        self.failure_detector.on_node_recovered = self._on_node_recovered
        
    async def start(self):
        """Start the node"""
        self.running = True
        
        # Start message passing server
        await self.message_passing.start()
        
        # Wait a bit for server to be ready
        await asyncio.sleep(1)
        
        # Connect to cluster nodes with retry
        await self._connect_to_cluster()
        
        # Wait for connections to establish
        await asyncio.sleep(2)
        
        # Start Raft consensus
        await self.raft.start()
        
        # Start failure detector
        await self.failure_detector.start()
        
        # Start metrics collection if enabled
        if Config.METRICS_ENABLED:
            metrics.start_server()
            asyncio.create_task(metrics.collect_system_metrics())
        
        # Start periodic tasks
        asyncio.create_task(self._send_periodic_heartbeats())
        
        logger.info(f"Node {self.node_id} started successfully")
        
    async def stop(self):
        """Stop the node"""
        self.running = False
        
        await self.raft.stop()
        await self.failure_detector.stop()
        await self.message_passing.stop()
        
        logger.info(f"Node {self.node_id} stopped")
        
    async def _connect_to_cluster(self):
        """Connect to all nodes in cluster with retry logic"""
        for node_info in self.cluster_nodes:
            # node_info is a dict with 'host' and 'port'
            if isinstance(node_info, dict):
                node_host = node_info.get('host')
                node_port = node_info.get('port')
                # Extract node_id from host (e.g., "node1" from "node1:5000")
                node_id = node_host.split(':')[0] if ':' in node_host else node_host
                
                if node_id != self.node_id:
                    # Retry connection up to 5 times
                    for attempt in range(5):
                        try:
                            await self.message_passing.connect_to_node(
                                node_id, 
                                node_host, 
                                node_port
                            )
                            self.failure_detector.register_node(node_id)
                            logger.info(f"Connected to node {node_id} at {node_host}:{node_port}")
                            break  # Success, exit retry loop
                        except Exception as e:
                            if attempt < 4:  # Not last attempt
                                logger.warning(f"Connection attempt {attempt + 1} to {node_id} failed: {e}. Retrying...")
                                await asyncio.sleep(1)  # Wait before retry
                            else:
                                logger.error(f"Failed to connect to {node_id} after 5 attempts: {e}")
                    
    async def _send_periodic_heartbeats(self):
        """Send periodic heartbeats to all nodes"""
        while self.running:
            try:
                message = Message(
                    msg_type=MessageType.HEARTBEAT,
                    sender=self.node_id,
                    data={'timestamp': asyncio.get_event_loop().time()}
                )
                await self.message_passing.broadcast_message(message)
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error sending heartbeats: {e}")
                
    async def _handle_heartbeat(self, message: Message) -> Dict[str, Any]:
        """Handle heartbeat message"""
        self.failure_detector.receive_heartbeat(message.sender)
        return {'status': 'ok'}
        
    async def _handle_ping(self, message: Message) -> Dict[str, Any]:
        """Handle ping message"""
        return {
            'status': 'ok',
            'node_id': self.node_id,
            'role': self.raft.role.value
        }
        
    async def _handle_request_vote(self, message: Message) -> Dict[str, Any]:
        """Handle Raft RequestVote RPC"""
        return await self.raft.handle_request_vote(message.data)
        
    async def _handle_append_entries(self, message: Message) -> Dict[str, Any]:
        """Handle Raft AppendEntries RPC"""
        return await self.raft.handle_append_entries(message.data)
        
    async def _send_raft_message(self, target: str, msg_type: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send Raft message to target node"""
        # Map Raft message types to MessageType enum
        type_mapping = {
            'request_vote': MessageType.REQUEST_VOTE,
            'append_entries': MessageType.APPEND_ENTRIES
        }
        
        message_type = type_mapping.get(msg_type)
        if not message_type:
            logger.error(f"Unknown Raft message type: {msg_type}")
            return None
            
        message = Message(
            msg_type=message_type,
            sender=self.node_id,
            data=data
        )
        
        return await self.message_passing.send_message(
            target, 
            message, 
            wait_response=True,
            timeout=2.0
        )
        
    async def _apply_to_state_machine(self, command: Dict[str, Any]):
        """Apply committed command to state machine"""
        try:
            op = command.get('op')
            key = command.get('key')
            value = command.get('value')
            
            if op == 'set':
                self.state_machine[key] = value
                logger.info(f"Applied: SET {key} = {value}")
            elif op == 'delete':
                self.state_machine.pop(key, None)
                logger.info(f"Applied: DELETE {key}")
            else:
                logger.warning(f"Unknown operation: {op}")
                
        except Exception as e:
            logger.error(f"Error applying command: {e}", exc_info=True)
            
    async def _on_node_failed(self, node_id: str):
        """Handle node failure"""
        logger.warning(f"Node {node_id} detected as FAILED")
        # Additional failure handling logic can be added here
        
    async def _on_node_recovered(self, node_id: str):
        """Handle node recovery"""
        logger.info(f"Node {node_id} recovered")
        # Additional recovery handling logic can be added here
        
    async def submit_command(self, command: Dict[str, Any]) -> bool:
        """Submit command to distributed system"""
        if not self.raft.is_leader():
            logger.warning("Cannot submit command: not leader")
            return False
            
        return await self.raft.append_entry(command)
        
    def get_state(self) -> Dict[str, Any]:
        """Get current state"""
        return self.state_machine.copy()
        
    def get_status(self) -> Dict[str, Any]:
        """Get node status"""
        return {
            'node_id': self.node_id,
            'host': self.host,
            'port': self.port,
            'raft': self.raft.get_state(),
            'failure_detector': self.failure_detector.get_status(),
            'state_machine_size': len(self.state_machine),
            'connected_nodes': len(self.message_passing.connections)
        }
