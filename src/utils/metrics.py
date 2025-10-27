"""
Metrics collection and monitoring
"""
import time
import psutil
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from typing import Dict, Any
import asyncio

class Metrics:
    """Metrics collector for distributed system"""
    
    def __init__(self, port: int = 9090):
        self.port = port
        
        # Node metrics
        self.node_status = Gauge('node_status', 'Node status (1=leader, 0=follower, -1=candidate)')
        self.node_uptime = Counter('node_uptime_seconds', 'Node uptime in seconds')
        
        # Lock metrics
        self.locks_acquired = Counter('locks_acquired_total', 'Total locks acquired', ['lock_type'])
        self.locks_released = Counter('locks_released_total', 'Total locks released', ['lock_type'])
        self.lock_wait_time = Histogram('lock_wait_seconds', 'Lock wait time in seconds')
        self.active_locks = Gauge('active_locks', 'Number of active locks', ['lock_type'])
        
        # Queue metrics
        self.messages_enqueued = Counter('messages_enqueued_total', 'Total messages enqueued')
        self.messages_dequeued = Counter('messages_dequeued_total', 'Total messages dequeued')
        self.queue_size = Gauge('queue_size', 'Current queue size')
        self.message_processing_time = Histogram('message_processing_seconds', 'Message processing time')
        
        # Cache metrics
        self.cache_hits = Counter('cache_hits_total', 'Total cache hits')
        self.cache_misses = Counter('cache_misses_total', 'Total cache misses')
        self.cache_size = Gauge('cache_size', 'Current cache size')
        self.cache_evictions = Counter('cache_evictions_total', 'Total cache evictions')
        
        # Network metrics
        self.messages_sent = Counter('messages_sent_total', 'Total messages sent', ['message_type'])
        self.messages_received = Counter('messages_received_total', 'Total messages received', ['message_type'])
        self.network_errors = Counter('network_errors_total', 'Total network errors')
        
        # System metrics
        self.cpu_usage = Gauge('cpu_usage_percent', 'CPU usage percentage')
        self.memory_usage = Gauge('memory_usage_bytes', 'Memory usage in bytes')
        self.disk_usage = Gauge('disk_usage_percent', 'Disk usage percentage')
        
        # Raft metrics
        self.raft_term = Gauge('raft_term', 'Current Raft term')
        self.raft_log_entries = Gauge('raft_log_entries', 'Number of Raft log entries')
        self.raft_commit_index = Gauge('raft_commit_index', 'Raft commit index')
        
    def start_server(self):
        """Start Prometheus metrics server"""
        start_http_server(self.port)
        
    async def collect_system_metrics(self):
        """Collect system resource metrics"""
        while True:
            try:
                self.cpu_usage.set(psutil.cpu_percent())
                self.memory_usage.set(psutil.virtual_memory().used)
                self.disk_usage.set(psutil.disk_usage('/').percent)
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Error collecting system metrics: {e}")
                
    def record_lock_acquired(self, lock_type: str):
        """Record lock acquisition"""
        self.locks_acquired.labels(lock_type=lock_type).inc()
        
    def record_lock_released(self, lock_type: str):
        """Record lock release"""
        self.locks_released.labels(lock_type=lock_type).inc()
        
    def record_cache_hit(self):
        """Record cache hit"""
        self.cache_hits.inc()
        
    def record_cache_miss(self):
        """Record cache miss"""
        self.cache_misses.inc()
        
    def get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        hits = self.cache_hits._value.get()
        misses = self.cache_misses._value.get()
        total = hits + misses
        return (hits / total * 100) if total > 0 else 0
        
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics"""
        return {
            'cache_hit_rate': self.get_cache_hit_rate(),
            'cpu_usage': psutil.cpu_percent(),
            'memory_usage': psutil.virtual_memory().percent,
            'disk_usage': psutil.disk_usage('/').percent,
        }

# Global metrics instance
metrics = Metrics()
