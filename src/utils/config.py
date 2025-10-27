"""
Configuration management for distributed system
"""
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class Config:
    """System configuration - using class attributes for easy access"""
    
    # Node configuration
    NODE_ID = os.getenv('NODE_ID', 'node1')
    NODE_HOST = os.getenv('NODE_HOST', '0.0.0.0')
    NODE_PORT = int(os.getenv('NODE_PORT', 5000))
    
    # Cluster configuration
    CLUSTER_NODES = os.getenv('CLUSTER_NODES', 'localhost:5000,localhost:5001,localhost:5002')
    
    # Redis configuration
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    
    # Raft configuration
    RAFT_ELECTION_TIMEOUT_MIN = int(os.getenv('ELECTION_TIMEOUT_MIN', 150))
    RAFT_ELECTION_TIMEOUT_MAX = int(os.getenv('ELECTION_TIMEOUT_MAX', 300))
    RAFT_HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', 50))
    
    # Performance configuration
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 10))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 5))
    
    # Metrics configuration
    METRICS_PORT = int(os.getenv('METRICS_PORT', 9090))
    METRICS_ENABLED = os.getenv('METRICS_ENABLED', 'true').lower() == 'true'
    
    # Cache configuration
    CACHE_SIZE = int(os.getenv('CACHE_SIZE', 1000))
    CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))
    
    # Queue configuration
    QUEUE_MAX_SIZE = int(os.getenv('QUEUE_MAX_SIZE', 10000))
    QUEUE_BATCH_SIZE = int(os.getenv('QUEUE_BATCH_SIZE', 100))
    
    # Lock configuration
    LOCK_TIMEOUT = int(os.getenv('LOCK_TIMEOUT', 30))
    DEADLOCK_DETECTION_INTERVAL = int(os.getenv('DEADLOCK_DETECTION_INTERVAL', 10))
    
    def __init__(self):
        """Initialize instance if needed"""
        pass
    
    @classmethod
    def get_peers(cls) -> List[Dict[str, Any]]:
        """
        Parse CLUSTER_NODES and return list of peer nodes (excluding self)
        
        Returns:
            List of peer dictionaries with 'node_id', 'host', 'port'
        """
        peers = []
        current_node = f"{cls.NODE_HOST}:{cls.NODE_PORT}"
        
        for node_str in cls.CLUSTER_NODES.split(','):
            node_str = node_str.strip()
            if not node_str:
                continue
            
            # Parse host:port
            if ':' in node_str:
                host, port = node_str.rsplit(':', 1)
                port = int(port)
            else:
                host = node_str
                port = 5000
            
            # Skip if it's the current node
            node_address = f"{host}:{port}"
            if node_address == current_node or node_address == f"0.0.0.0:{cls.NODE_PORT}":
                continue
            
            # Extract node_id from host if it's a container name (e.g., "node1")
            node_id = host.split('.')[0]  # Take first part before any dots
            
            peers.append({
                'node_id': node_id,
                'host': host,
                'port': port
            })
        
        return peers
    
    @classmethod
    def get_redis_url(cls) -> str:
        """Get Redis connection URL"""
        return f"redis://{cls.REDIS_HOST}:{cls.REDIS_PORT}/{cls.REDIS_DB}"
    
    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'node_id': cls.NODE_ID,
            'node_host': cls.NODE_HOST,
            'node_port': cls.NODE_PORT,
            'cluster_nodes': cls.CLUSTER_NODES,
            'redis_host': cls.REDIS_HOST,
            'redis_port': cls.REDIS_PORT,
            'metrics_port': cls.METRICS_PORT,
            'cache_size': cls.CACHE_SIZE,
            'queue_max_size': cls.QUEUE_MAX_SIZE,
            'lock_timeout': cls.LOCK_TIMEOUT
        }
    
    @classmethod
    def reload(cls):
        """Reload configuration from environment"""
        load_dotenv(override=True)
        cls.NODE_ID = os.getenv('NODE_ID', 'node1')
        cls.NODE_HOST = os.getenv('NODE_HOST', '0.0.0.0')
        cls.NODE_PORT = int(os.getenv('NODE_PORT', 5000))
        cls.CLUSTER_NODES = os.getenv('CLUSTER_NODES', 'localhost:5000,localhost:5001,localhost:5002')
        cls.REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
        cls.REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
        cls.METRICS_PORT = int(os.getenv('METRICS_PORT', 9090))
