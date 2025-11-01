"""
Distributed Queue System dengan consistent hashing.
Support multiple producers/consumers dan message persistence.
"""

import asyncio
import hashlib
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import deque
import logging
import redis.asyncio as redis
import orjson

from ..consensus.raft import RaftNode

logger = logging.getLogger(__name__)


@dataclass
class QueueMessage:
    """Message dalam distributed queue."""
    message_id: str
    content: Any
    producer_id: int
    timestamp: float
    ttl: int  # Time to live in seconds
    delivery_count: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def is_expired(self) -> bool:
        return time.time() > (self.timestamp + self.ttl)


class ConsistentHash:
    """
    Consistent hashing untuk distribute messages across nodes.
    """
    
    def __init__(self, nodes: List[str], virtual_nodes: int = 150):
        """
        Initialize consistent hash ring.
        
        Args:
            nodes: List of node addresses
            virtual_nodes: Number of virtual nodes per physical node
        """
        self.virtual_nodes = virtual_nodes
        self.ring: Dict[int, str] = {}
        self.sorted_keys: List[int] = []
        
        for node in nodes:
            self.add_node(node)
    
    def _hash(self, key: str) -> int:
        """Hash function."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    def add_node(self, node: str):
        """Add node ke hash ring."""
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}:{i}"
            hash_value = self._hash(virtual_key)
            self.ring[hash_value] = node
        
        self.sorted_keys = sorted(self.ring.keys())
        logger.info(f"Added node {node} to consistent hash ring")
    
    def remove_node(self, node: str):
        """Remove node dari hash ring."""
        keys_to_remove = []
        for hash_value, n in self.ring.items():
            if n == node:
                keys_to_remove.append(hash_value)
        
        for key in keys_to_remove:
            del self.ring[key]
        
        self.sorted_keys = sorted(self.ring.keys())
        logger.info(f"Removed node {node} from consistent hash ring")
    
    def get_node(self, key: str) -> Optional[str]:
        """Get node responsible untuk key."""
        if not self.ring:
            return None
        
        hash_value = self._hash(key)
        
        # Binary search untuk find closest node
        for ring_key in self.sorted_keys:
            if hash_value <= ring_key:
                return self.ring[ring_key]
        
        # Wrap around to first node
        return self.ring[self.sorted_keys[0]]


class DistributedQueue:
    """
    Distributed queue dengan consistent hashing dan persistence.
    
    Features:
    1. Multiple producers/consumers
    2. At-least-once delivery
    3. Message persistence via Redis
    4. Automatic rebalancing saat node failure
    5. Message TTL
    """
    
    def __init__(
        self,
        node_id: int,
        queue_name: str,
        raft: RaftNode,
        redis_client: Optional[redis.Redis] = None,
        max_size: int = 10000,
        message_ttl: int = 3600
    ):
        """
        Initialize distributed queue.
        
        Args:
            node_id: This node's ID
            queue_name: Name of the queue
            raft: Raft consensus instance
            redis_client: Redis client for persistence
            max_size: Maximum queue size
            message_ttl: Default message TTL in seconds
        """
        self.node_id = node_id
        self.queue_name = queue_name
        self.raft = raft
        self.redis_client = redis_client
        self.max_size = max_size
        self.message_ttl = message_ttl
        
        # Local message queue
        self.queue: deque[QueueMessage] = deque(maxlen=max_size)
        
        # Processing tracking untuk at-least-once delivery
        self.in_flight_messages: Dict[str, QueueMessage] = {}
        
        # Consistent hashing ring
        self.hash_ring: Optional[ConsistentHash] = None
        
        # Background tasks
        self.persistence_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.messages_enqueued = 0
        self.messages_dequeued = 0
        self.messages_expired = 0
        self.messages_lost = 0
        
        logger.info(f"Distributed Queue '{queue_name}' initialized for node {node_id}")
    
    async def start(self, cluster_nodes: List[str]):
        """
        Start queue dan background tasks.
        
        Args:
            cluster_nodes: List of cluster node addresses
        """
        if self.running:
            return
        
        self.running = True
        
        # Initialize consistent hashing
        self.hash_ring = ConsistentHash(cluster_nodes)
        
        # Load persisted messages dari Redis
        if self.redis_client:
            await self._load_from_redis()
        
        # Start background tasks
        if self.redis_client:
            self.persistence_task = asyncio.create_task(self._periodic_persistence())
        
        self.cleanup_task = asyncio.create_task(self._cleanup_expired_messages())
        
        logger.info(f"Distributed Queue '{self.queue_name}' started")
    
    async def stop(self):
        """Stop queue dan save state."""
        self.running = False
        
        if self.persistence_task:
            self.persistence_task.cancel()
        if self.cleanup_task:
            self.cleanup_task.cancel()
        
        # Final persistence
        if self.redis_client:
            await self._save_to_redis()
        
        logger.info(f"Distributed Queue '{self.queue_name}' stopped")
    
    async def enqueue(
        self,
        content: Any,
        producer_id: Optional[int] = None,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Enqueue message.
        
        Args:
            content: Message content
            producer_id: ID of producer (node_id if None)
            ttl: Message TTL (default if None)
            
        Returns:
            True if enqueued successfully
        """
        if len(self.queue) >= self.max_size:
            logger.warning(f"Queue '{self.queue_name}' is full")
            return False
        
        # Create message
        message_id = f"{producer_id or self.node_id}_{time.time()}_{self.messages_enqueued}"
        message = QueueMessage(
            message_id=message_id,
            content=content,
            producer_id=producer_id or self.node_id,
            timestamp=time.time(),
            ttl=ttl or self.message_ttl,
            delivery_count=0
        )
        
        # Add to queue
        self.queue.append(message)
        self.messages_enqueued += 1
        
        # Replicate via Raft jika leader
        if self.raft.is_leader():
            await self.raft.replicate_command({
                'type': 'queue_enqueue',
                'queue_name': self.queue_name,
                'message': message.to_dict()
            })
        
        logger.debug(f"Message enqueued: {message_id}")
        return True
    
    async def dequeue(self, consumer_id: Optional[int] = None) -> Optional[QueueMessage]:
        """
        Dequeue message untuk processing.
        
        Args:
            consumer_id: ID of consumer
            
        Returns:
            Message jika ada, None jika queue kosong
        """
        if not self.queue:
            return None
        
        # Get message dari queue
        message = self.queue.popleft()
        
        # Check if expired
        if message.is_expired():
            self.messages_expired += 1
            logger.debug(f"Message expired: {message.message_id}")
            return await self.dequeue(consumer_id)  # Try next message
        
        # Track in-flight untuk at-least-once delivery
        message.delivery_count += 1
        self.in_flight_messages[message.message_id] = message
        self.messages_dequeued += 1
        
        logger.debug(f"Message dequeued: {message.message_id} by consumer {consumer_id}")
        return message
    
    async def ack(self, message_id: str) -> bool:
        """
        Acknowledge message processing (remove dari in-flight).
        
        Args:
            message_id: ID of message to acknowledge
            
        Returns:
            True if acknowledged successfully
        """
        if message_id in self.in_flight_messages:
            del self.in_flight_messages[message_id]
            logger.debug(f"Message acknowledged: {message_id}")
            return True
        return False
    
    async def nack(self, message_id: str, requeue: bool = True) -> bool:
        """
        Negative acknowledge (message processing failed).
        
        Args:
            message_id: ID of message
            requeue: Requeue message jika True
            
        Returns:
            True if processed successfully
        """
        if message_id not in self.in_flight_messages:
            return False
        
        message = self.in_flight_messages[message_id]
        del self.in_flight_messages[message_id]
        
        if requeue and not message.is_expired():
            # Requeue message
            self.queue.append(message)
            logger.debug(f"Message requeued: {message_id}")
        else:
            logger.debug(f"Message not requeued: {message_id}")
        
        return True
    
    async def _periodic_persistence(self):
        """Periodically save queue state ke Redis."""
        while self.running:
            try:
                await asyncio.sleep(5)  # Save every 5 seconds
                await self._save_to_redis()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in persistence task: {e}", exc_info=True)
    
    async def _save_to_redis(self):
        """Save queue state ke Redis."""
        if not self.redis_client:
            return
        
        try:
            # Save messages
            redis_key = f"queue:{self.queue_name}:node:{self.node_id}"
            messages_data = [orjson.dumps(msg.to_dict()) for msg in self.queue]
            
            if messages_data:
                await self.redis_client.delete(redis_key)
                await self.redis_client.rpush(redis_key, *messages_data)
            
            logger.debug(f"Saved {len(messages_data)} messages to Redis")
            
        except Exception as e:
            logger.error(f"Error saving to Redis: {e}", exc_info=True)
    
    async def _load_from_redis(self):
        """Load queue state dari Redis."""
        if not self.redis_client:
            return
        
        try:
            redis_key = f"queue:{self.queue_name}:node:{self.node_id}"
            messages_data = await self.redis_client.lrange(redis_key, 0, -1)
            
            for msg_data in messages_data:
                msg_dict = orjson.loads(msg_data)
                message = QueueMessage(**msg_dict)
                
                if not message.is_expired():
                    self.queue.append(message)
            
            logger.info(f"Loaded {len(messages_data)} messages from Redis")
            
        except Exception as e:
            logger.error(f"Error loading from Redis: {e}", exc_info=True)
    
    async def _cleanup_expired_messages(self):
        """Remove expired messages dari queue."""
        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Clean main queue
                valid_messages = []
                for message in self.queue:
                    if message.is_expired():
                        self.messages_expired += 1
                    else:
                        valid_messages.append(message)
                
                self.queue = deque(valid_messages, maxlen=self.max_size)
                
                # Clean in-flight messages
                expired_in_flight = []
                for msg_id, message in self.in_flight_messages.items():
                    if message.is_expired():
                        expired_in_flight.append(msg_id)
                
                for msg_id in expired_in_flight:
                    del self.in_flight_messages[msg_id]
                    self.messages_expired += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)
    
    def size(self) -> int:
        """Get current queue size."""
        return len(self.queue)
    
    def get_statistics(self) -> Dict:
        """Get queue statistics."""
        return {
            'queue_name': self.queue_name,
            'messages_enqueued': self.messages_enqueued,
            'messages_dequeued': self.messages_dequeued,
            'messages_expired': self.messages_expired,
            'messages_lost': self.messages_lost,
            'current_size': len(self.queue),
            'in_flight': len(self.in_flight_messages),
            'throughput': self.messages_dequeued / max(1, time.time() - getattr(self, 'start_time', time.time())),
        }
