"""
Metrics collection untuk monitoring performance.
Menggunakan Prometheus client untuk export metrics.
"""

import time
import psutil
from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
from functools import wraps
import asyncio


class MetricsCollector:
    """
    Collector untuk semua metrics sistem.
    Tracking throughput, latency, resource usage, dll.
    """
    
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.registry = CollectorRegistry()
        
        # Lock Metrics
        self.lock_requests = Counter(
            'lock_requests_total',
            'Total lock requests',
            ['node_id', 'lock_type', 'status'],
            registry=self.registry
        )
        self.lock_duration = Histogram(
            'lock_duration_seconds',
            'Lock operation duration',
            ['node_id', 'operation'],
            registry=self.registry
        )
        self.active_locks = Gauge(
            'active_locks',
            'Number of active locks',
            ['node_id'],
            registry=self.registry
        )
        
        # Queue Metrics
        self.queue_messages = Counter(
            'queue_messages_total',
            'Total queue messages',
            ['node_id', 'operation', 'status'],
            registry=self.registry
        )
        self.queue_size = Gauge(
            'queue_size',
            'Current queue size',
            ['node_id', 'queue_name'],
            registry=self.registry
        )
        self.message_processing_time = Histogram(
            'message_processing_seconds',
            'Message processing time',
            ['node_id'],
            registry=self.registry
        )
        
        # Cache Metrics
        self.cache_operations = Counter(
            'cache_operations_total',
            'Total cache operations',
            ['node_id', 'operation', 'result'],
            registry=self.registry
        )
        self.cache_hit_rate = Gauge(
            'cache_hit_rate',
            'Cache hit rate',
            ['node_id'],
            registry=self.registry
        )
        self.cache_size = Gauge(
            'cache_entries',
            'Number of cache entries',
            ['node_id'],
            registry=self.registry
        )
        
        # Raft Consensus Metrics
        self.raft_elections = Counter(
            'raft_elections_total',
            'Total Raft elections',
            ['node_id', 'result'],
            registry=self.registry
        )
        self.raft_term = Gauge(
            'raft_current_term',
            'Current Raft term',
            ['node_id'],
            registry=self.registry
        )
        self.raft_log_entries = Gauge(
            'raft_log_entries',
            'Number of log entries',
            ['node_id'],
            registry=self.registry
        )
        
        # System Metrics
        self.cpu_usage = Gauge(
            'cpu_usage_percent',
            'CPU usage percentage',
            ['node_id'],
            registry=self.registry
        )
        self.memory_usage = Gauge(
            'memory_usage_bytes',
            'Memory usage in bytes',
            ['node_id'],
            registry=self.registry
        )
        self.network_io = Counter(
            'network_io_bytes',
            'Network I/O in bytes',
            ['node_id', 'direction'],
            registry=self.registry
        )
        
        # Request Metrics
        self.http_requests = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['node_id', 'method', 'endpoint', 'status'],
            registry=self.registry
        )
        self.http_request_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['node_id', 'method', 'endpoint'],
            registry=self.registry
        )
        
        # Counters untuk statistik
        self.stats = {
            'locks_acquired': 0,
            'locks_released': 0,
            'locks_failed': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'elections_won': 0,
            'elections_lost': 0,
        }
    
    def record_lock_request(self, lock_type: str, success: bool):
        """Record lock request metric."""
        status = 'success' if success else 'failed'
        self.lock_requests.labels(
            node_id=self.node_id,
            lock_type=lock_type,
            status=status
        ).inc()
        
        if success:
            self.stats['locks_acquired'] += 1
        else:
            self.stats['locks_failed'] += 1
    
    def record_lock_release(self):
        """Record lock release."""
        self.stats['locks_released'] += 1
    
    def set_active_locks(self, count: int):
        """Set current active locks count."""
        self.active_locks.labels(node_id=self.node_id).set(count)
    
    def record_queue_operation(self, operation: str, success: bool):
        """Record queue operation."""
        status = 'success' if success else 'failed'
        self.queue_messages.labels(
            node_id=self.node_id,
            operation=operation,
            status=status
        ).inc()
        
        if operation == 'enqueue':
            self.stats['messages_sent'] += 1
        elif operation == 'dequeue':
            self.stats['messages_received'] += 1
    
    def set_queue_size(self, queue_name: str, size: int):
        """Set current queue size."""
        self.queue_size.labels(
            node_id=self.node_id,
            queue_name=queue_name
        ).set(size)
    
    def record_cache_operation(self, operation: str, hit: bool):
        """Record cache operation."""
        result = 'hit' if hit else 'miss'
        self.cache_operations.labels(
            node_id=self.node_id,
            operation=operation,
            result=result
        ).inc()
        
        if hit:
            self.stats['cache_hits'] += 1
        else:
            self.stats['cache_misses'] += 1
        
        # Update hit rate
        total = self.stats['cache_hits'] + self.stats['cache_misses']
        if total > 0:
            hit_rate = self.stats['cache_hits'] / total
            self.cache_hit_rate.labels(node_id=self.node_id).set(hit_rate)
    
    def set_cache_size(self, size: int):
        """Set current cache size."""
        self.cache_size.labels(node_id=self.node_id).set(size)
    
    def record_raft_election(self, won: bool):
        """Record Raft election result."""
        result = 'won' if won else 'lost'
        self.raft_elections.labels(
            node_id=self.node_id,
            result=result
        ).inc()
        
        if won:
            self.stats['elections_won'] += 1
        else:
            self.stats['elections_lost'] += 1
    
    def set_raft_term(self, term: int):
        """Set current Raft term."""
        self.raft_term.labels(node_id=self.node_id).set(term)
    
    def set_raft_log_entries(self, count: int):
        """Set Raft log entries count."""
        self.raft_log_entries.labels(node_id=self.node_id).set(count)
    
    def record_http_request(self, method: str, endpoint: str, status: int, duration: float):
        """Record HTTP request."""
        self.http_requests.labels(
            node_id=self.node_id,
            method=method,
            endpoint=endpoint,
            status=status
        ).inc()
        
        self.http_request_duration.labels(
            node_id=self.node_id,
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def update_system_metrics(self):
        """Update system resource metrics."""
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        self.cpu_usage.labels(node_id=self.node_id).set(cpu_percent)
        
        # Memory usage
        memory = psutil.virtual_memory()
        self.memory_usage.labels(node_id=self.node_id).set(memory.used)
        
        # Network I/O
        net_io = psutil.net_io_counters()
        self.network_io.labels(node_id=self.node_id, direction='sent').inc(net_io.bytes_sent)
        self.network_io.labels(node_id=self.node_id, direction='received').inc(net_io.bytes_recv)
    
    def get_metrics(self) -> bytes:
        """Get Prometheus metrics in text format."""
        return generate_latest(self.registry)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get human-readable stats."""
        self.update_system_metrics()
        
        return {
            'node_id': self.node_id,
            'locks': {
                'acquired': self.stats['locks_acquired'],
                'released': self.stats['locks_released'],
                'failed': self.stats['locks_failed'],
            },
            'queue': {
                'messages_sent': self.stats['messages_sent'],
                'messages_received': self.stats['messages_received'],
            },
            'cache': {
                'hits': self.stats['cache_hits'],
                'misses': self.stats['cache_misses'],
                'hit_rate': self.stats['cache_hits'] / max(1, self.stats['cache_hits'] + self.stats['cache_misses']),
            },
            'raft': {
                'elections_won': self.stats['elections_won'],
                'elections_lost': self.stats['elections_lost'],
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
            }
        }


def measure_time(metric_name: str):
    """
    Decorator untuk mengukur execution time.
    
    Usage:
        @measure_time('lock_acquire')
        async def acquire_lock(self, resource):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                # Log duration or record to metrics
                print(f"{metric_name} took {duration:.3f}s")
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                print(f"{metric_name} took {duration:.3f}s")
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
