"""
Message passing system for distributed communication
"""
import asyncio
import json
import logging
from typing import Dict, Any, Callable, Optional
from enum import Enum
import time

logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Types of messages in the distributed system"""
    # Raft messages
    REQUEST_VOTE = "request_vote"
    VOTE_RESPONSE = "vote_response"
    APPEND_ENTRIES = "append_entries"
    APPEND_ENTRIES_RESPONSE = "append_entries_response"
    
    # Lock messages
    LOCK_REQUEST = "lock_request"
    LOCK_RELEASE = "lock_release"
    LOCK_RESPONSE = "lock_response"
    
    # Queue messages
    ENQUEUE = "enqueue"
    DEQUEUE = "dequeue"
    QUEUE_RESPONSE = "queue_response"
    
    # Cache messages
    CACHE_GET = "cache_get"
    CACHE_PUT = "cache_put"
    CACHE_INVALIDATE = "cache_invalidate"
    CACHE_RESPONSE = "cache_response"
    
    # System messages
    HEARTBEAT = "heartbeat"
    PING = "ping"
    PONG = "pong"

class Message:
    """Message structure for inter-node communication"""
    
    def __init__(self, msg_type: MessageType, sender: str, data: Dict[str, Any], 
                 msg_id: Optional[str] = None, timestamp: Optional[float] = None):
        self.msg_type = msg_type
        self.sender = sender
        self.data = data
        self.msg_id = msg_id or f"{sender}_{time.time()}"
        self.timestamp = timestamp or time.time()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        return {
            'msg_type': self.msg_type.value,
            'sender': self.sender,
            'data': self.data,
            'msg_id': self.msg_id,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary"""
        return cls(
            msg_type=MessageType(data['msg_type']),
            sender=data['sender'],
            data=data['data'],
            msg_id=data.get('msg_id'),
            timestamp=data.get('timestamp')
        )
    
    def __repr__(self):
        return f"Message({self.msg_type.value}, from={self.sender}, id={self.msg_id})"

class MessageHandler:
    """Handles incoming and outgoing messages"""
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.handlers: Dict[MessageType, Callable] = {}
        self.pending_responses: Dict[str, asyncio.Future] = {}
        
    def register_handler(self, msg_type: MessageType, handler: Callable):
        """Register a handler for a message type"""
        self.handlers[msg_type] = handler
        logger.info(f"Registered handler for {msg_type.value}")
        
    async def handle_message(self, message: Message) -> Optional[Dict[str, Any]]:
        """Handle incoming message"""
        logger.debug(f"Handling message: {message}")
        
        # Check if this is a response to a pending request
        if message.msg_id in self.pending_responses:
            future = self.pending_responses.pop(message.msg_id)
            if not future.done():
                future.set_result(message.data)
            return None
        
        # Handle message with registered handler
        handler = self.handlers.get(message.msg_type)
        if handler:
            try:
                result = await handler(message)
                return result
            except Exception as e:
                logger.error(f"Error handling message {message.msg_type}: {e}", exc_info=True)
                return {'error': str(e)}
        else:
            logger.warning(f"No handler registered for {message.msg_type}")
            return None

class MessagePassing:
    """Message passing layer for network communication"""
    
    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.handler = MessageHandler(node_id)
        self.connections: Dict[str, tuple] = {}  # node_id -> (reader, writer)
        self.server = None
        self.running = False
        
    async def start(self):
        """Start message passing server"""
        self.running = True
        try:
            self.server = await asyncio.start_server(
                self._handle_connection, 
                self.host, 
                self.port
            )
            
            # Get the actual address the server is listening on
            addrs = ', '.join(str(sock.getsockname()) for sock in self.server.sockets)
            logger.info(f"Message passing server started on {addrs}")
            
            # Start serving in background
            asyncio.create_task(self.server.serve_forever())
            
        except Exception as e:
            logger.error(f"Failed to start message passing server on {self.host}:{self.port}: {e}", exc_info=True)
            raise
        
    async def stop(self):
        """Stop message passing server"""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # Close all connections
        for node_id, (reader, writer) in self.connections.items():
            writer.close()
            await writer.wait_closed()
        
        logger.info("Message passing server stopped")
        
    async def _handle_connection(self, reader: asyncio.StreamReader, 
                                 writer: asyncio.StreamWriter):
        """Handle incoming connection"""
        addr = writer.get_extra_info('peername')
        logger.debug(f"New connection from {addr}")
        
        try:
            while self.running:
                # Read message length (4 bytes)
                length_data = await reader.readexactly(4)
                if not length_data:
                    break
                    
                msg_length = int.from_bytes(length_data, 'big')
                
                # Read message data
                data = await reader.readexactly(msg_length)
                message_dict = json.loads(data.decode())
                message = Message.from_dict(message_dict)
                
                # Handle message
                response = await self.handler.handle_message(message)
                
                # Send response if any
                if response is not None:
                    response_msg = Message(
                        msg_type=message.msg_type,
                        sender=self.node_id,
                        data=response,
                        msg_id=message.msg_id
                    )
                    await self._send_message(writer, response_msg)
                    
        except asyncio.IncompleteReadError:
            logger.debug(f"Connection closed by {addr}")
        except Exception as e:
            logger.error(f"Error handling connection from {addr}: {e}", exc_info=True)
        finally:
            writer.close()
            await writer.wait_closed()
            
    async def _send_message(self, writer: asyncio.StreamWriter, message: Message):
        """Send message through writer"""
        data = json.dumps(message.to_dict()).encode()
        length = len(data).to_bytes(4, 'big')
        writer.write(length + data)
        await writer.drain()
        
    async def connect_to_node(self, node_id: str, host: str, port: int):
        """Connect to another node"""
        try:
            reader, writer = await asyncio.open_connection(host, port)
            self.connections[node_id] = (reader, writer)
            # Start reading responses from this connection
            asyncio.create_task(self._read_responses(node_id, reader))
            logger.info(f"Connected to node {node_id} at {host}:{port}")
        except Exception as e:
            logger.error(f"Failed to connect to node {node_id}: {e}")
    
    async def _read_responses(self, node_id: str, reader: asyncio.StreamReader):
        """Read responses from a connected node"""
        try:
            while self.running:
                # Read message length
                length_data = await reader.readexactly(4)
                if not length_data:
                    break
                
                msg_length = int.from_bytes(length_data, 'big')
                
                # Read message data
                data = await reader.readexactly(msg_length)
                message_dict = json.loads(data.decode())
                message = Message.from_dict(message_dict)
                
                # Handle the response
                await self.handler.handle_message(message)
                    
        except asyncio.IncompleteReadError:
            logger.debug(f"Connection to {node_id} closed")
        except Exception as e:
            logger.error(f"Error reading from {node_id}: {e}", exc_info=True)
            
    async def send_message(self, target_node: str, message: Message, 
                          wait_response: bool = False, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Send message to target node"""
        if target_node not in self.connections:
            logger.error(f"No connection to node {target_node}")
            return None
            
        _, writer = self.connections[target_node]
        
        try:
            # Setup response future if waiting for response
            if wait_response:
                future = asyncio.Future()
                self.handler.pending_responses[message.msg_id] = future
            
            # Send message
            await self._send_message(writer, message)
            logger.debug(f"Sent message to {target_node}: {message}")
            
            # Wait for response if needed
            if wait_response:
                try:
                    response = await asyncio.wait_for(future, timeout=timeout)
                    return response
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout waiting for response from {target_node}")
                    self.handler.pending_responses.pop(message.msg_id, None)
                    return None
            
            return {'status': 'sent'}
            
        except Exception as e:
            logger.error(f"Error sending message to {target_node}: {e}", exc_info=True)
            return None
            
    async def broadcast_message(self, message: Message, exclude: Optional[list] = None):
        """Broadcast message to all connected nodes"""
        exclude = exclude or []
        tasks = []
        
        for node_id in self.connections:
            if node_id not in exclude:
                tasks.append(self.send_message(node_id, message))
                
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
