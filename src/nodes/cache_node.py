"""
Distributed Cache dengan MESI Protocol untuk cache coherence.
Implementasi LRU replacement policy dan performance monitoring.

MESI States:
- Modified (M): Cache line modified, different dari memory
- Exclusive (E): Cache line clean, only in this cache
- Shared (S): Cache line clean, may be in other caches
- Invalid (I): Cache line invalid
"""

import asyncio
import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum
from collections import OrderedDict
import logging

from ..communication.message_passing import MessagePassing, Message, MessageType

logger = logging.getLogger(__name__)


class MESIState(Enum):
    """MESI Protocol states."""
    MODIFIED = "M"  # Modified - dirty, exclusive
    EXCLUSIVE = "E"  # Exclusive - clean, exclusive
    SHARED = "S"    # Shared - clean, may be in other caches
    INVALID = "I"   # Invalid - not valid


@dataclass
class CacheEntry:
    """Entry dalam distributed cache."""
    key: str
    value: Any
    state: MESIState
    timestamp: float
    last_accessed: float
    ttl: Optional[int] = None
    version: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry expired."""
        if self.ttl is None:
            return False
        return time.time() > (self.timestamp + self.ttl)
    
    def is_valid(self) -> bool:
        """Check if cache entry valid."""
        return self.state != MESIState.INVALID and not self.is_expired()


class LRUCache:
    """
    LRU (Least Recently Used) cache implementation.
    Using OrderedDict untuk efficient O(1) operations.
    """
    
    def __init__(self, max_size: int):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of entries
        """
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def get(self, key: str) -> Optional[CacheEntry]:
        """
        Get entry dari cache.
        
        Args:
            key: Cache key
            
        Returns:
            CacheEntry jika ada dan valid, None otherwise
        """
        if key not in self.cache:
            self.misses += 1
            return None
        
        entry = self.cache[key]
        
        # Check if valid
        if not entry.is_valid():
            del self.cache[key]
            self.misses += 1
            return None
        
        # Move to end (most recently used)
        self.cache.move_to_end(key)
        entry.last_accessed = time.time()
        self.hits += 1
        
        return entry
    
    def put(self, entry: CacheEntry) -> Optional[CacheEntry]:
        """
        Put entry ke cache.
        
        Args:
            entry: CacheEntry to store
            
        Returns:
            Evicted entry jika ada
        """
        evicted = None
        
        # Remove key jika sudah ada
        if entry.key in self.cache:
            del self.cache[entry.key]
        
        # Check if need to evict
        elif len(self.cache) >= self.max_size:
            # Evict LRU (first item)
            evicted_key, evicted = self.cache.popitem(last=False)
            self.evictions += 1
            logger.debug(f"Evicted cache entry: {evicted_key}")
        
        # Add new entry (most recently used)
        self.cache[entry.key] = entry
        
        return evicted
    
    def delete(self, key: str) -> bool:
        """Delete entry dari cache."""
        if key in self.cache:
            del self.cache[key]
            return True
        return False
    
    def invalidate(self, key: str):
        """Invalidate cache entry."""
        if key in self.cache:
            self.cache[key].state = MESIState.INVALID
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)
    
    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
    
    def get_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100


class DistributedCache:
    """
    Distributed cache dengan MESI coherence protocol.
    
    Features:
    1. MESI cache coherence protocol
    2. LRU replacement policy
    3. Automatic cache invalidation
    4. Performance monitoring
    5. TTL support
    """
    
    def __init__(
        self,
        node_id: int,
        message_passing: MessagePassing,
        cluster_nodes: List[str],
        max_size: int = 1000,
        default_ttl: Optional[int] = None
    ):
        """
        Initialize distributed cache.
        
        Args:
            node_id: This node's ID
            message_passing: Message passing instance
            cluster_nodes: List of cluster node addresses
            max_size: Maximum cache size
            default_ttl: Default TTL for entries (None = no expiration)
        """
        self.node_id = node_id
        self.message_passing = message_passing
        self.cluster_nodes = cluster_nodes
        self.default_ttl = default_ttl
        
        # Local cache with LRU policy
        self.cache = LRUCache(max_size)
        
        # Background tasks
        self.invalidation_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.invalidations_sent = 0
        self.invalidations_received = 0
        self.updates_sent = 0
        
        logger.info(f"Distributed Cache initialized for node {node_id} with MESI protocol")
    
    async def start(self):
        """Start cache dan background tasks."""
        if self.running:
            return
        
        self.running = True
        
        # Register message handlers
        self.message_passing.register_handler(
            MessageType.CACHE_INVALIDATE,
            self._handle_invalidation
        )
        self.message_passing.register_handler(
            MessageType.CACHE_UPDATE,
            self._handle_update
        )
        self.message_passing.register_handler(
            MessageType.CACHE_SYNC,
            self._handle_sync_request
        )
        
        # Start background invalidation checker
        self.invalidation_task = asyncio.create_task(self._periodic_invalidation())
        
        logger.info("Distributed Cache started")
    
    async def stop(self):
        """Stop cache."""
        self.running = False
        
        if self.invalidation_task:
            self.invalidation_task.cancel()
        
        logger.info("Distributed Cache stopped")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value dari cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value jika ada, None otherwise
        """
        entry = self.cache.get(key)
        
        if entry is None:
            return None
        
        # MESI state transition handling
        if entry.state == MESIState.INVALID:
            return None
        
        return entry.value
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        exclusive: bool = False
    ) -> bool:
        """
        Set value dalam cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (default_ttl if None)
            exclusive: Request exclusive access
            
        Returns:
            True if set successfully
        """
        # Check if key exists dalam cache
        existing = self.cache.get(key)
        
        # Determine MESI state
        if exclusive:
            # Request exclusive access - invalidate other caches
            await self._invalidate_other_caches(key)
            state = MESIState.MODIFIED
        else:
            if existing and existing.state in [MESIState.MODIFIED, MESIState.EXCLUSIVE]:
                state = MESIState.MODIFIED
            else:
                state = MESIState.SHARED
                # Notify other caches tentang update
                await self._broadcast_update(key, value)
        
        # Create cache entry
        entry = CacheEntry(
            key=key,
            value=value,
            state=state,
            timestamp=time.time(),
            last_accessed=time.time(),
            ttl=ttl or self.default_ttl,
            version=(existing.version + 1) if existing else 0
        )
        
        # Store dalam cache
        self.cache.put(entry)
        
        logger.debug(f"Cache set: key={key}, state={state.value}")
        return True
    
    async def delete(self, key: str) -> bool:
        """
        Delete key dari cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted
        """
        deleted = self.cache.delete(key)
        
        if deleted:
            # Invalidate pada other caches juga
            await self._invalidate_other_caches(key)
        
        return deleted
    
    async def _invalidate_other_caches(self, key: str):
        """
        Send invalidation message ke other caches.
        Implementasi MESI invalidation protocol.
        """
        message = Message(
            msg_type=MessageType.CACHE_INVALIDATE,
            sender_id=self.node_id,
            receiver_id=-1,  # Broadcast
            term=0,
            timestamp=time.time(),
            data={'key': key}
        )
        
        await self.message_passing.broadcast_message(
            self.cluster_nodes,
            message,
            wait_responses=False
        )
        
        self.invalidations_sent += 1
        logger.debug(f"Sent cache invalidation for key: {key}")
    
    async def _broadcast_update(self, key: str, value: Any):
        """Broadcast cache update ke other nodes."""
        message = Message(
            msg_type=MessageType.CACHE_UPDATE,
            sender_id=self.node_id,
            receiver_id=-1,
            term=0,
            timestamp=time.time(),
            data={'key': key, 'value': value}
        )
        
        await self.message_passing.broadcast_message(
            self.cluster_nodes,
            message,
            wait_responses=False
        )
        
        self.updates_sent += 1
    
    async def _handle_invalidation(self, message: Message) -> None:
        """Handle cache invalidation dari other node."""
        key = message.data['key']
        
        # Invalidate local cache entry
        self.cache.invalidate(key)
        self.invalidations_received += 1
        
        logger.debug(f"Cache invalidated: key={key} from node {message.sender_id}")
    
    async def _handle_update(self, message: Message) -> None:
        """Handle cache update dari other node."""
        key = message.data['key']
        value = message.data['value']
        
        # Update local cache dengan SHARED state
        existing = self.cache.get(key)
        
        entry = CacheEntry(
            key=key,
            value=value,
            state=MESIState.SHARED,
            timestamp=time.time(),
            last_accessed=time.time(),
            ttl=self.default_ttl,
            version=(existing.version + 1) if existing else 0
        )
        
        self.cache.put(entry)
        logger.debug(f"Cache updated: key={key} from node {message.sender_id}")
    
    async def _handle_sync_request(self, message: Message) -> Message:
        """Handle cache sync request dari other node."""
        # Return semua cache entries
        entries = []
        for entry in self.cache.cache.values():
            if entry.is_valid():
                entries.append({
                    'key': entry.key,
                    'value': entry.value,
                    'version': entry.version
                })
        
        return Message(
            msg_type=MessageType.CACHE_SYNC,
            sender_id=self.node_id,
            receiver_id=message.sender_id,
            term=0,
            timestamp=time.time(),
            data={'entries': entries}
        )
    
    async def _periodic_invalidation(self):
        """Periodic task untuk cleanup expired entries."""
        while self.running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Remove expired entries
                expired_keys = []
                for key, entry in list(self.cache.cache.items()):
                    if entry.is_expired():
                        expired_keys.append(key)
                
                for key in expired_keys:
                    self.cache.delete(key)
                    logger.debug(f"Expired cache entry removed: {key}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in invalidation task: {e}", exc_info=True)
    
    def get_statistics(self) -> Dict:
        """Get cache statistics."""
        return {
            'size': self.cache.size(),
            'max_size': self.cache.max_size,
            'hits': self.cache.hits,
            'misses': self.cache.misses,
            'evictions': self.cache.evictions,
            'hit_rate': self.cache.get_hit_rate(),
            'invalidations_sent': self.invalidations_sent,
            'invalidations_received': self.invalidations_received,
            'updates_sent': self.updates_sent,
        }
