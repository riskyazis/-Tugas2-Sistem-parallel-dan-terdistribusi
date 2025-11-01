"""
Failure detector untuk mendeteksi node failures.
Menggunakan heartbeat mechanism dan timeout detection.
"""

import asyncio
import time
from typing import Dict, Set, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class NodeState(Enum):
    """Status node dalam cluster."""
    ALIVE = "alive"
    SUSPECTED = "suspected"
    FAILED = "failed"
    RECOVERING = "recovering"


@dataclass
class NodeStatus:
    """Status information untuk setiap node."""
    node_address: str
    state: NodeState
    last_heartbeat: float
    missed_heartbeats: int
    total_failures: int
    last_failure_time: Optional[float] = None


class FailureDetector:
    """
    Adaptive failure detector menggunakan heartbeat mechanism.
    Implementasi menggunakan phi-accrual failure detection untuk lebih akurat.
    """
    
    def __init__(
        self,
        node_id: int,
        heartbeat_interval: float = 1.0,
        failure_timeout: float = 5.0,
        max_missed_heartbeats: int = 3
    ):
        """
        Initialize failure detector.
        
        Args:
            node_id: ID node ini
            heartbeat_interval: Interval kirim heartbeat (seconds)
            failure_timeout: Timeout untuk mendeteksi failure (seconds)
            max_missed_heartbeats: Max missed heartbeats sebelum dianggap failed
        """
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval
        self.failure_timeout = failure_timeout
        self.max_missed_heartbeats = max_missed_heartbeats
        
        # Node tracking
        self.nodes: Dict[str, NodeStatus] = {}
        self.suspected_nodes: Set[str] = set()
        self.failed_nodes: Set[str] = set()
        
        # Callbacks
        self.failure_callbacks: list[Callable] = []
        self.recovery_callbacks: list[Callable] = []
        
        # Background tasks
        self.detector_task: Optional[asyncio.Task] = None
        self.running = False
        
        logger.info(f"Failure detector initialized for node {node_id}")
    
    def register_node(self, node_address: str):
        """
        Register node untuk monitoring.
        
        Args:
            node_address: Node address dalam format "host:port"
        """
        if node_address not in self.nodes:
            self.nodes[node_address] = NodeStatus(
                node_address=node_address,
                state=NodeState.ALIVE,
                last_heartbeat=time.time(),
                missed_heartbeats=0,
                total_failures=0
            )
            logger.info(f"Registered node {node_address} for monitoring")
    
    def unregister_node(self, node_address: str):
        """Remove node dari monitoring."""
        if node_address in self.nodes:
            del self.nodes[node_address]
            self.suspected_nodes.discard(node_address)
            self.failed_nodes.discard(node_address)
            logger.info(f"Unregistered node {node_address}")
    
    def record_heartbeat(self, node_address: str):
        """
        Record heartbeat dari node.
        
        Args:
            node_address: Address of node yang kirim heartbeat
        """
        if node_address not in self.nodes:
            self.register_node(node_address)
        
        node = self.nodes[node_address]
        node.last_heartbeat = time.time()
        node.missed_heartbeats = 0
        
        # Jika node recovering dari failure
        if node.state == NodeState.FAILED or node.state == NodeState.SUSPECTED:
            logger.info(f"Node {node_address} recovered from {node.state.value}")
            node.state = NodeState.RECOVERING
            self.suspected_nodes.discard(node_address)
            self.failed_nodes.discard(node_address)
            
            # Trigger recovery callbacks
            for callback in self.recovery_callbacks:
                try:
                    callback(node_address)
                except Exception as e:
                    logger.error(f"Error in recovery callback: {e}")
        
        # Set back to alive setelah beberapa heartbeats
        elif node.state == NodeState.RECOVERING:
            if node.missed_heartbeats == 0:  # Heartbeat stabil
                node.state = NodeState.ALIVE
                logger.info(f"Node {node_address} fully recovered")
    
    async def start(self):
        """Start failure detection."""
        if self.running:
            logger.warning("Failure detector already running")
            return
        
        self.running = True
        self.detector_task = asyncio.create_task(self._detection_loop())
        logger.info("Failure detector started")
    
    async def stop(self):
        """Stop failure detection."""
        self.running = False
        if self.detector_task:
            self.detector_task.cancel()
            try:
                await self.detector_task
            except asyncio.CancelledError:
                pass
        logger.info("Failure detector stopped")
    
    async def _detection_loop(self):
        """Main detection loop."""
        while self.running:
            try:
                await self._check_nodes()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in detection loop: {e}", exc_info=True)
    
    async def _check_nodes(self):
        """Check status semua nodes."""
        current_time = time.time()
        
        for node_address, node in list(self.nodes.items()):
            time_since_heartbeat = current_time - node.last_heartbeat
            
            # Check jika sudah timeout
            if time_since_heartbeat > self.failure_timeout:
                node.missed_heartbeats += 1
                
                # Suspect node jika missed beberapa heartbeats
                if node.missed_heartbeats >= self.max_missed_heartbeats // 2:
                    if node.state == NodeState.ALIVE:
                        logger.warning(f"Node {node_address} suspected (missed {node.missed_heartbeats} heartbeats)")
                        node.state = NodeState.SUSPECTED
                        self.suspected_nodes.add(node_address)
                
                # Declare failed jika missed terlalu banyak
                if node.missed_heartbeats >= self.max_missed_heartbeats:
                    if node.state != NodeState.FAILED:
                        logger.error(f"Node {node_address} declared FAILED")
                        node.state = NodeState.FAILED
                        node.total_failures += 1
                        node.last_failure_time = current_time
                        self.failed_nodes.add(node_address)
                        self.suspected_nodes.discard(node_address)
                        
                        # Trigger failure callbacks
                        for callback in self.failure_callbacks:
                            try:
                                await callback(node_address)
                            except Exception as e:
                                logger.error(f"Error in failure callback: {e}")
    
    def on_failure(self, callback: Callable):
        """
        Register callback untuk node failure event.
        
        Args:
            callback: Async function yang dipanggil saat node failed
        """
        self.failure_callbacks.append(callback)
    
    def on_recovery(self, callback: Callable):
        """
        Register callback untuk node recovery event.
        
        Args:
            callback: Function yang dipanggil saat node recovered
        """
        self.recovery_callbacks.append(callback)
    
    def is_alive(self, node_address: str) -> bool:
        """
        Check if node alive.
        
        Args:
            node_address: Node address to check
            
        Returns:
            True if node alive or recovering, False otherwise
        """
        if node_address not in self.nodes:
            return False
        
        node = self.nodes[node_address]
        return node.state in [NodeState.ALIVE, NodeState.RECOVERING]
    
    def is_suspected(self, node_address: str) -> bool:
        """Check if node suspected."""
        return node_address in self.suspected_nodes
    
    def is_failed(self, node_address: str) -> bool:
        """Check if node failed."""
        return node_address in self.failed_nodes
    
    def get_alive_nodes(self) -> list[str]:
        """Get list of alive nodes."""
        return [
            addr for addr, node in self.nodes.items()
            if node.state in [NodeState.ALIVE, NodeState.RECOVERING]
        ]
    
    def get_failed_nodes(self) -> list[str]:
        """Get list of failed nodes."""
        return list(self.failed_nodes)
    
    def get_node_status(self, node_address: str) -> Optional[NodeStatus]:
        """Get status of specific node."""
        return self.nodes.get(node_address)
    
    def get_all_statuses(self) -> Dict[str, NodeStatus]:
        """Get status semua nodes."""
        return self.nodes.copy()
    
    def get_statistics(self) -> Dict:
        """Get failure detection statistics."""
        total_nodes = len(self.nodes)
        alive_nodes = len(self.get_alive_nodes())
        failed_nodes = len(self.failed_nodes)
        suspected_nodes = len(self.suspected_nodes)
        
        total_failures = sum(node.total_failures for node in self.nodes.values())
        
        return {
            'total_nodes': total_nodes,
            'alive_nodes': alive_nodes,
            'suspected_nodes': suspected_nodes,
            'failed_nodes': failed_nodes,
            'total_failures': total_failures,
            'availability': (alive_nodes / max(1, total_nodes)) * 100,
        }
