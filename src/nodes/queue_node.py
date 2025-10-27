"""
Distributed Queue System with consistent hashing and persistence
"""
import asyncio
import hashlib
import json
import time
import logging
from typing import Dict, List, Optional, Any
from collections import deque
from dataclasses import dataclass, asdict
from .base_node import BaseNode
from ..communication import Message, MessageType

logger = logging.getLogger(__name__)

@dataclass
class QueueMessage:
    """Queue message structure"""
    msg_id: str
    data: Any
    timestamp: float
    retries: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueMessage':
        return cls(**data)

class ConsistentHash:
    """Consistent hashing for queue distribution"""
    
    def __init__(self, nodes: List[str], virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self.ring: Dict[int, str] = {}
        self.sorted_keys: List[int] = []
        
        for node in nodes:
            self.add_node(node)
            
    def _hash(self, key: str) -> int:
        """Hash function"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
        
    def add_node(self, node: str):
        """Add node to consistent hash ring"""
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}:{i}"
            hash_val = self._hash(virtual_key)
            self.ring[hash_val] = node
            
        self.sorted_keys = sorted(self.ring.keys())
        logger.info(f"Added node {node} to hash ring with {self.virtual_nodes} virtual nodes")
        
    def remove_node(self, node: str):
        """Remove node from hash ring"""
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}:{i}"
            hash_val = self._hash(virtual_key)
            if hash_val in self.ring:
                del self.ring[hash_val]
                
        self.sorted_keys = sorted(self.ring.keys())
        logger.info(f"Removed node {node} from hash ring")
        
    def get_node(self, key: str) -> Optional[str]:
        """Get responsible node for a key"""
        if not self.ring:
            return None
            
        hash_val = self._hash(key)
        
        # Binary search for the node
        for ring_key in self.sorted_keys:
            if hash_val <= ring_key:
                return self.ring[ring_key]
                
        # Wrap around to first node
        return self.ring[self.sorted_keys[0]]

class QueueNode(BaseNode):
    """
    Distributed Queue Node with persistence and at-least-once delivery
    """
    
    def __init__(self, node_id: str, host: str, port: int, cluster_nodes: list,
                 max_queue_size: int = 10000, persistence_enabled: bool = True):
        super().__init__(node_id, host, port, cluster_nodes)
        
        self.max_queue_size = max_queue_size
        self.persistence_enabled = persistence_enabled
        
        # Queue storage
        self.queues: Dict[str, deque] = {}  # queue_name -> deque of messages
        self.in_flight: Dict[str, QueueMessage] = {}  # msg_id -> message
        self.dlq: Dict[str, List[QueueMessage]] = {}  # Dead letter queue
        
        # Consistent hashing
        self.consistent_hash = ConsistentHash(
            [n.split(':')[0] for n in cluster_nodes]
        )
        
        # Message acknowledgment tracking
        self.pending_acks: Dict[str, asyncio.Event] = {}
        
        # Register handlers
        self._register_queue_handlers()
        
        logger.info(f"QueueNode {node_id} initialized")
        
    def _register_queue_handlers(self):
        """Register queue-specific handlers"""
        self.message_passing.handler.register_handler(
            MessageType.ENQUEUE,
            self._handle_enqueue
        )
        self.message_passing.handler.register_handler(
            MessageType.DEQUEUE,
            self._handle_dequeue
        )
        
    async def start(self):
        """Start queue node"""
        await super().start()
        
        # Load persisted messages if enabled
        if self.persistence_enabled:
            await self._load_persisted_messages()
            
        # Start message retry task
        asyncio.create_task(self._retry_failed_messages())
        
        logger.info(f"QueueNode {self.node_id} started")
        
    async def enqueue(self, queue_name: str, data: Any) -> bool:
        """Enqueue a message"""
        msg_id = f"{self.node_id}_{time.time()}_{id(data)}"
        
        message = QueueMessage(
            msg_id=msg_id,
            data=data,
            timestamp=time.time()
        )
        
        # Determine responsible node using consistent hashing
        responsible_node = self.consistent_hash.get_node(queue_name)
        
        if responsible_node == self.node_id:
            # This node is responsible
            return await self._enqueue_local(queue_name, message)
        else:
            # Forward to responsible node
            return await self._forward_enqueue(responsible_node, queue_name, message)
            
    async def dequeue(self, queue_name: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Dequeue a message"""
        responsible_node = self.consistent_hash.get_node(queue_name)
        
        if responsible_node == self.node_id:
            return await self._dequeue_local(queue_name, timeout)
        else:
            return await self._forward_dequeue(responsible_node, queue_name, timeout)
            
    async def _enqueue_local(self, queue_name: str, message: QueueMessage) -> bool:
        """Enqueue message locally"""
        # Create queue if doesn't exist
        if queue_name not in self.queues:
            self.queues[queue_name] = deque()
            
        queue = self.queues[queue_name]
        
        # Check size limit
        if len(queue) >= self.max_queue_size:
            logger.warning(f"Queue {queue_name} is full")
            return False
            
        queue.append(message)
        logger.debug(f"Enqueued message {message.msg_id} to {queue_name}")
        
        # Persist if enabled
        if self.persistence_enabled:
            await self._persist_message(queue_name, message)
            
        return True
        
    async def _dequeue_local(self, queue_name: str, timeout: float) -> Optional[Dict[str, Any]]:
        """Dequeue message locally"""
        if queue_name not in self.queues:
            return None
            
        queue = self.queues[queue_name]
        start_time = time.time()
        
        # Wait for message with timeout
        while time.time() - start_time < timeout:
            if queue:
                message = queue.popleft()
                
                # Track in-flight
                self.in_flight[message.msg_id] = message
                
                logger.debug(f"Dequeued message {message.msg_id} from {queue_name}")
                
                return {
                    'msg_id': message.msg_id,
                    'data': message.data,
                    'timestamp': message.timestamp
                }
                
            await asyncio.sleep(0.1)
            
        return None
        
    async def acknowledge(self, msg_id: str) -> bool:
        """Acknowledge message processing"""
        if msg_id in self.in_flight:
            message = self.in_flight.pop(msg_id)
            
            # Remove from persistence
            if self.persistence_enabled:
                await self._remove_persisted_message(msg_id)
                
            logger.debug(f"Acknowledged message {msg_id}")
            return True
            
        return False
        
    async def _handle_enqueue(self, message: Message) -> Dict[str, Any]:
        """Handle enqueue request"""
        queue_name = message.data['queue_name']
        queue_message = QueueMessage.from_dict(message.data['message'])
        
        success = await self._enqueue_local(queue_name, queue_message)
        
        return {
            'success': success,
            'msg_id': queue_message.msg_id
        }
        
    async def _handle_dequeue(self, message: Message) -> Dict[str, Any]:
        """Handle dequeue request"""
        queue_name = message.data['queue_name']
        timeout = message.data.get('timeout', 10.0)
        
        result = await self._dequeue_local(queue_name, timeout)
        
        return {
            'message': result
        }
        
    async def _forward_enqueue(self, target_node: str, queue_name: str, 
                              message: QueueMessage) -> bool:
        """Forward enqueue to responsible node"""
        msg = Message(
            msg_type=MessageType.ENQUEUE,
            sender=self.node_id,
            data={
                'queue_name': queue_name,
                'message': message.to_dict()
            }
        )
        
        response = await self.message_passing.send_message(
            target_node, 
            msg, 
            wait_response=True
        )
        
        return response.get('success', False) if response else False
        
    async def _forward_dequeue(self, target_node: str, queue_name: str, 
                              timeout: float) -> Optional[Dict[str, Any]]:
        """Forward dequeue to responsible node"""
        msg = Message(
            msg_type=MessageType.DEQUEUE,
            sender=self.node_id,
            data={
                'queue_name': queue_name,
                'timeout': timeout
            }
        )
        
        response = await self.message_passing.send_message(
            target_node,
            msg,
            wait_response=True,
            timeout=timeout + 1.0
        )
        
        return response.get('message') if response else None
        
    async def _retry_failed_messages(self):
        """Retry failed messages"""
        while self.running:
            try:
                current_time = time.time()
                messages_to_retry = []
                
                # Find timed out in-flight messages
                for msg_id, message in list(self.in_flight.items()):
                    if current_time - message.timestamp > 30:  # 30 second timeout
                        messages_to_retry.append((msg_id, message))
                        
                # Retry or move to DLQ
                for msg_id, message in messages_to_retry:
                    self.in_flight.pop(msg_id, None)
                    
                    if message.retries < message.max_retries:
                        message.retries += 1
                        # Re-enqueue
                        logger.info(f"Retrying message {msg_id} (attempt {message.retries})")
                        # Add back to appropriate queue
                        for queue_name, queue in self.queues.items():
                            queue.append(message)
                            break
                    else:
                        # Move to dead letter queue
                        logger.warning(f"Moving message {msg_id} to DLQ after {message.retries} retries")
                        dlq_key = "default_dlq"
                        if dlq_key not in self.dlq:
                            self.dlq[dlq_key] = []
                        self.dlq[dlq_key].append(message)
                        
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in retry loop: {e}", exc_info=True)
                
    async def _persist_message(self, queue_name: str, message: QueueMessage):
        """Persist message to storage"""
        # Simple file-based persistence
        try:
            filename = f"data/queue_{queue_name}_{message.msg_id}.json"
            import os
            os.makedirs("data", exist_ok=True)
            
            with open(filename, 'w') as f:
                json.dump(message.to_dict(), f)
        except Exception as e:
            logger.error(f"Error persisting message: {e}")
            
    async def _remove_persisted_message(self, msg_id: str):
        """Remove persisted message"""
        try:
            import os
            import glob
            
            files = glob.glob(f"data/queue_*_{msg_id}.json")
            for file in files:
                os.remove(file)
        except Exception as e:
            logger.error(f"Error removing persisted message: {e}")
            
    async def _load_persisted_messages(self):
        """Load persisted messages on startup"""
        try:
            import os
            import glob
            
            if not os.path.exists("data"):
                return
                
            files = glob.glob("data/queue_*.json")
            
            for file in files:
                with open(file, 'r') as f:
                    message_data = json.load(f)
                    message = QueueMessage.from_dict(message_data)
                    
                    # Extract queue name from filename
                    queue_name = file.split('_')[1]
                    
                    if queue_name not in self.queues:
                        self.queues[queue_name] = deque()
                        
                    self.queues[queue_name].append(message)
                    
            logger.info(f"Loaded {len(files)} persisted messages")
            
        except Exception as e:
            logger.error(f"Error loading persisted messages: {e}")
            
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            'queues': {
                name: {
                    'size': len(queue),
                    'oldest_message': queue[0].timestamp if queue else None
                }
                for name, queue in self.queues.items()
            },
            'in_flight_count': len(self.in_flight),
            'dlq_count': sum(len(msgs) for msgs in self.dlq.values())
        }
