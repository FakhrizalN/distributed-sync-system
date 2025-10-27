"""
Distributed Cache with MESI Coherence Protocol and LRU replacement
"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional
from enum import Enum
from collections import OrderedDict
from .base_node import BaseNode
from ..communication import Message, MessageType

logger = logging.getLogger(__name__)

class CacheState(Enum):
    """MESI Cache states"""
    MODIFIED = "modified"  # Cache has modified data, main memory is stale
    EXCLUSIVE = "exclusive"  # Only this cache has the data, same as memory
    SHARED = "shared"  # Multiple caches may have the data
    INVALID = "invalid"  # Cache line is invalid

class CacheLine:
    """Cache line with MESI state"""
    def __init__(self, key: str, value: Any, state: CacheState = CacheState.EXCLUSIVE):
        self.key = key
        self.value = value
        self.state = state
        self.last_access = time.time()
        self.access_count = 0

class LRUCache:
    """LRU Cache implementation"""
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache: OrderedDict[str, CacheLine] = OrderedDict()
        
    def get(self, key: str) -> Optional[CacheLine]:
        """Get cache line"""
        if key in self.cache:
            self.cache.move_to_end(key)
            line = self.cache[key]
            line.last_access = time.time()
            line.access_count += 1
            return line
        return None
        
    def put(self, key: str, line: CacheLine):
        """Put cache line"""
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = line
        
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
            
    def invalidate(self, key: str):
        """Invalidate cache line"""
        if key in self.cache:
            self.cache[key].state = CacheState.INVALID
            
    def remove(self, key: str):
        """Remove cache line"""
        self.cache.pop(key, None)

class CacheNode(BaseNode):
    """
    Distributed Cache Node with MESI protocol
    """
    
    def __init__(self, node_id: str, host: str, port: int, cluster_nodes: list,
                 cache_size: int = 1000):
        super().__init__(node_id, host, port, cluster_nodes)
        
        self.cache = LRUCache(cache_size)
        self.cache_size = cache_size
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        
        # Register handlers
        self._register_cache_handlers()
        
        logger.info(f"CacheNode {node_id} initialized with size {cache_size}")
        
    def _register_cache_handlers(self):
        """Register cache-specific handlers"""
        self.message_passing.handler.register_handler(
            MessageType.CACHE_GET,
            self._handle_cache_get
        )
        self.message_passing.handler.register_handler(
            MessageType.CACHE_PUT,
            self._handle_cache_put
        )
        self.message_passing.handler.register_handler(
            MessageType.CACHE_INVALIDATE,
            self._handle_cache_invalidate
        )
        
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        line = self.cache.get(key)
        
        if line and line.state != CacheState.INVALID:
            self.hits += 1
            logger.debug(f"Cache HIT for key {key} (state={line.state.value})")
            return line.value
            
        self.misses += 1
        logger.debug(f"Cache MISS for key {key}")
        
        # Try to get from other caches or main storage
        value = await self._fetch_from_cluster(key)
        
        if value is not None:
            # Add to cache in SHARED state
            self.cache.put(key, CacheLine(key, value, CacheState.SHARED))
            
        return value
        
    async def put(self, key: str, value: Any):
        """Put value in cache"""
        # Invalidate in other caches
        await self._broadcast_invalidate(key)
        
        # Put in local cache with MODIFIED state
        line = CacheLine(key, value, CacheState.MODIFIED)
        self.cache.put(key, line)
        
        logger.debug(f"Cache PUT for key {key} (state=MODIFIED)")
        
        # Write through to state machine
        await self.submit_command({
            'op': 'set',
            'key': key,
            'value': value
        })
        
    async def invalidate(self, key: str):
        """Invalidate cache entry"""
        self.cache.invalidate(key)
        await self._broadcast_invalidate(key)
        
    async def _fetch_from_cluster(self, key: str) -> Optional[Any]:
        """Fetch value from other caches or storage"""
        # Try other cache nodes
        msg = Message(
            msg_type=MessageType.CACHE_GET,
            sender=self.node_id,
            data={'key': key}
        )
        
        # Broadcast to all nodes
        for node_id in self.cluster_nodes:
            if node_id != self.node_id:
                node_name = node_id.split(':')[0]
                response = await self.message_passing.send_message(
                    node_name, 
                    msg, 
                    wait_response=True,
                    timeout=1.0
                )
                
                if response and response.get('found'):
                    return response.get('value')
                    
        # Fallback to state machine
        return self.state_machine.get(key)
        
    async def _broadcast_invalidate(self, key: str):
        """Broadcast cache invalidation"""
        msg = Message(
            msg_type=MessageType.CACHE_INVALIDATE,
            sender=self.node_id,
            data={'key': key}
        )
        
        await self.message_passing.broadcast_message(msg)
        
    async def _handle_cache_get(self, message: Message) -> Dict[str, Any]:
        """Handle cache get request"""
        key = message.data['key']
        line = self.cache.get(key)
        
        if line and line.state != CacheState.INVALID:
            # Change to SHARED state if was EXCLUSIVE
            if line.state == CacheState.EXCLUSIVE:
                line.state = CacheState.SHARED
                
            return {
                'found': True,
                'value': line.value,
                'state': line.state.value
            }
            
        return {'found': False}
        
    async def _handle_cache_put(self, message: Message) -> Dict[str, Any]:
        """Handle cache put request"""
        key = message.data['key']
        value = message.data['value']
        
        # Invalidate local copy
        self.cache.invalidate(key)
        
        return {'status': 'invalidated'}
        
    async def _handle_cache_invalidate(self, message: Message) -> Dict[str, Any]:
        """Handle cache invalidation"""
        key = message.data['key']
        self.cache.invalidate(key)
        
        logger.debug(f"Invalidated cache key {key} from {message.sender}")
        
        return {'status': 'invalidated'}
        
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self.cache.cache),
            'capacity': self.cache_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{hit_rate:.2f}%",
            'evictions': self.evictions,
            'cache_entries': [
                {
                    'key': line.key,
                    'state': line.state.value,
                    'access_count': line.access_count,
                    'last_access': line.last_access
                }
                for line in list(self.cache.cache.values())[:10]  # Top 10
            ]
        }
