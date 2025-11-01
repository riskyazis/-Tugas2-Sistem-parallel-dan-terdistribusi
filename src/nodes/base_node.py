"""
Base Node implementation dengan FastAPI HTTP server.
Ini adalah foundation untuk semua distributed components.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn
import redis.asyncio as redis

from ..utils.config import get_config
from ..utils.metrics import MetricsCollector
from ..communication.message_passing import MessagePassing, MessageType
from ..communication.failure_detector import FailureDetector
from ..consensus.raft import RaftNode

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BaseNode:
    """
    Base distributed node dengan semua core functionality:
    - HTTP API server
    - Message passing
    - Failure detection  
    - Raft consensus
    - Redis connection
    - Metrics collection
    """
    
    def __init__(self, node_id: Optional[int] = None):
        """
        Initialize base node.
        
        Args:
            node_id: Node ID (dari config jika None)
        """
        self.config = get_config()
        self.node_id = node_id or self.config.node_id
        
        # Update config dengan node_id
        if node_id:
            self.config.node_id = node_id
        
        # FastAPI app
        self.app = FastAPI(
            title=f"Distributed Node {self.node_id}",
            description="Distributed Synchronization System Node",
            version="1.0.0"
        )
        
        # Core components
        self.metrics = MetricsCollector(self.node_id)
        self.message_passing = MessagePassing(
            self.node_id,
            self.config.node_host,
            self.config.node_port
        )
        self.failure_detector = FailureDetector(
            self.node_id,
            heartbeat_interval=self.config.heartbeat_interval / 1000,
            failure_timeout=5.0,
            max_missed_heartbeats=3
        )
        
        # Raft consensus
        cluster_nodes = self.config.get_cluster_nodes_list()
        self.raft = RaftNode(
            node_id=self.node_id,
            cluster_nodes=cluster_nodes,
            message_passing=self.message_passing,
            election_timeout_min=self.config.election_timeout_min,
            election_timeout_max=self.config.election_timeout_max,
            heartbeat_interval=self.config.heartbeat_interval
        )
        
        # Redis connection
        self.redis_client: Optional[redis.Redis] = None
        
        # Running state
        self.running = False
        
        # Setup routes
        self._setup_routes()
        
        logger.info(f"Base node {self.node_id} initialized")
    
    def _setup_routes(self):
        """Setup FastAPI routes."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint."""
            return {
                "node_id": self.node_id,
                "status": "running" if self.running else "stopped",
                "is_leader": self.raft.is_leader(),
                "current_leader": self.raft.get_leader(),
            }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "node_id": self.node_id,
                "timestamp": asyncio.get_event_loop().time()
            }
        
        @self.app.post("/api/message")
        async def handle_message(request: Request):
            """Handle incoming messages dari nodes lain."""
            try:
                message_data = await request.json()
                response = await self.message_passing.handle_message(message_data)
                return JSONResponse(content=response)
            except Exception as e:
                logger.error(f"Error handling message: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/metrics")
        async def get_metrics():
            """Prometheus metrics endpoint."""
            metrics_data = self.metrics.get_metrics()
            return PlainTextResponse(content=metrics_data.decode())
        
        @self.app.get("/stats")
        async def get_stats():
            """Get node statistics."""
            return {
                "node": {
                    "id": self.node_id,
                    "running": self.running,
                },
                "raft": self.raft.get_statistics(),
                "metrics": self.metrics.get_stats(),
                "message_passing": self.message_passing.get_statistics(),
                "failure_detector": self.failure_detector.get_statistics(),
            }
        
        @self.app.get("/cluster")
        async def get_cluster_info():
            """Get cluster information."""
            return {
                "cluster_nodes": self.config.get_cluster_nodes_list(),
                "alive_nodes": self.failure_detector.get_alive_nodes(),
                "failed_nodes": self.failure_detector.get_failed_nodes(),
                "current_leader": self.raft.get_leader(),
                "is_leader": self.raft.is_leader(),
            }
    
    async def start(self):
        """Start node and all components."""
        if self.running:
            logger.warning(f"Node {self.node_id} already running")
            return
        
        logger.info(f"Starting node {self.node_id}...")
        
        # Connect to Redis
        try:
            self.redis_client = redis.from_url(
                self.config.get_redis_url(),
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {e}")
            # Continue without Redis for demo purposes
        
        # Start components
        await self.message_passing.start()
        await self.failure_detector.start()
        await self.raft.start()
        
        # Register cluster nodes untuk failure detection
        for node in self.config.get_cluster_nodes_list():
            self.failure_detector.register_node(node)
        
        self.running = True
        logger.info(f"Node {self.node_id} started successfully")
    
    async def stop(self):
        """Stop node and cleanup."""
        if not self.running:
            return
        
        logger.info(f"Stopping node {self.node_id}...")
        
        self.running = False
        
        # Stop components
        await self.raft.stop()
        await self.failure_detector.stop()
        await self.message_passing.stop()
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info(f"Node {self.node_id} stopped")
    
    def run(self, host: Optional[str] = None, port: Optional[int] = None):
        """
        Run node dengan uvicorn server.
        
        Args:
            host: Host to bind to (dari config jika None)
            port: Port to bind to (dari config jika None)
        """
        host = host or self.config.node_host
        port = port or self.config.node_port
        
        # Startup event
        @self.app.on_event("startup")
        async def startup_event():
            await self.start()
        
        # Shutdown event
        @self.app.on_event("shutdown")
        async def shutdown_event():
            await self.stop()
        
        # Run server
        logger.info(f"Running node {self.node_id} on {host}:{port}")
        uvicorn.run(
            self.app,
            host=host,
            port=port,
            log_level="info"
        )


def main():
    """Main entry point untuk menjalankan single node."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run distributed node")
    parser.add_argument("--node-id", type=int, help="Node ID")
    parser.add_argument("--port", type=int, help="Node port")
    args = parser.parse_args()
    
    # Create and run node
    node = BaseNode(node_id=args.node_id)
    
    if args.port:
        node.config.node_port = args.port
    
    node.run()


if __name__ == "__main__":
    main()
