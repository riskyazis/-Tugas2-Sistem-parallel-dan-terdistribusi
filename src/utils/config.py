"""
Utility functions for loading and managing configuration.
Menggunakan pydantic untuk validation dan type safety.
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Config(BaseSettings):
    """
    Konfigurasi global untuk distributed system.
    Semua nilai bisa di-override melalui environment variables.
    """
    
    # Node Configuration
    node_id: int = Field(default=1, description="Unique node identifier")
    node_host: str = Field(default="0.0.0.0", description="Node bind address")
    node_port: int = Field(default=5001, description="Node port")
    
    # Cluster Configuration
    cluster_nodes: str = Field(
        default="localhost:5001,localhost:5002,localhost:5003",
        description="Comma-separated list of cluster nodes"
    )
    bootstrap_node: str = Field(default="localhost:5001", description="Initial bootstrap node")
    
    # Redis Configuration
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_db: int = Field(default=0, description="Redis database number")
    
    # Raft Consensus
    election_timeout_min: int = Field(default=150, description="Min election timeout (ms)")
    election_timeout_max: int = Field(default=300, description="Max election timeout (ms)")
    heartbeat_interval: int = Field(default=50, description="Heartbeat interval (ms)")
    log_replication_batch_size: int = Field(default=100, description="Log batch size")
    
    # Distributed Lock
    lock_timeout: int = Field(default=30, description="Default lock timeout (seconds)")
    lock_retry_delay: float = Field(default=0.1, description="Lock retry delay (seconds)")
    max_lock_attempts: int = Field(default=50, description="Max lock acquire attempts")
    deadlock_detection_interval: int = Field(default=10, description="Deadlock detection interval (s)")
    
    # Distributed Queue
    queue_persistence_interval: int = Field(default=5, description="Queue save interval (s)")
    queue_max_size: int = Field(default=10000, description="Max queue size")
    queue_batch_size: int = Field(default=100, description="Queue batch processing size")
    message_ttl: int = Field(default=3600, description="Message TTL (seconds)")
    
    # Cache Configuration
    cache_size: int = Field(default=1000, description="Max cache entries")
    cache_ttl: int = Field(default=300, description="Default cache TTL (seconds)")
    cache_policy: str = Field(default="LRU", description="Cache replacement policy")
    cache_invalidation_delay: float = Field(default=0.5, description="Cache invalidation delay (s)")
    
    # Performance
    max_workers: int = Field(default=4, description="Max worker threads")
    connection_pool_size: int = Field(default=50, description="Connection pool size")
    request_timeout: int = Field(default=30, description="Request timeout (seconds)")
    max_concurrent_requests: int = Field(default=1000, description="Max concurrent requests")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json/text)")
    log_file: str = Field(default="logs/node.log", description="Log file path")
    
    # Monitoring
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=9090, description="Metrics server port")
    metrics_path: str = Field(default="/metrics", description="Metrics endpoint path")
    
    # Security
    enable_tls: bool = Field(default=False, description="Enable TLS encryption")
    tls_cert_path: str = Field(default="certs/server.crt", description="TLS certificate path")
    tls_key_path: str = Field(default="certs/server.key", description="TLS key path")
    enable_authentication: bool = Field(default=False, description="Enable authentication")
    jwt_secret: str = Field(default="change-this-secret-key", description="JWT secret key")
    
    # Development
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="production", description="Environment (dev/staging/production)")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @validator("cluster_nodes")
    def parse_cluster_nodes(cls, v):
        """Parse cluster nodes string menjadi list."""
        if isinstance(v, str):
            return [node.strip() for node in v.split(",")]
        return v
    
    def get_cluster_nodes_list(self) -> List[str]:
        """Return list of cluster nodes."""
        if isinstance(self.cluster_nodes, str):
            return [node.strip() for node in self.cluster_nodes.split(",")]
        return self.cluster_nodes
    
    def get_redis_url(self) -> str:
        """Generate Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    def is_leader_node(self) -> bool:
        """Check if this is the bootstrap/leader node."""
        return f"{self.node_host}:{self.node_port}" == self.bootstrap_node


# Global config instance
config = Config()


def get_config() -> Config:
    """Get global configuration instance."""
    return config


def reload_config():
    """Reload configuration from environment."""
    global config
    config = Config()
    return config
