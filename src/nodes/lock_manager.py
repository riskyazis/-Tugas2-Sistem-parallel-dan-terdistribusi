"""
Distributed Lock Manager dengan Raft Consensus.
Implementasi shared dan exclusive locks dengan deadlock detection.
"""

import asyncio
import time
from typing import Dict, Optional, Set, List
from dataclasses import dataclass
from enum import Enum
import logging
from collections import defaultdict

from ..consensus.raft import RaftNode
from ..communication.message_passing import MessagePassing, Message, MessageType

logger = logging.getLogger(__name__)


class LockType(Enum):
    """Tipe distributed lock."""
    SHARED = "shared"  # Multiple readers
    EXCLUSIVE = "exclusive"  # Single writer


@dataclass
class Lock:
    """Representation of a distributed lock."""
    resource_id: str
    lock_type: LockType
    holder_id: int
    acquired_at: float
    expires_at: float
    
    def is_expired(self) -> bool:
        """Check if lock expired."""
        return time.time() > self.expires_at


class DistributedLockManager:
    """
    Distributed Lock Manager using Raft consensus.
    
    Features:
    1. Shared (read) locks - multiple holders
    2. Exclusive (write) locks - single holder
    3. Deadlock detection
    4. Automatic lock expiration
    5. Wait queue untuk lock requests
    """
    
    def __init__(
        self,
        node_id: int,
        raft: RaftNode,
        message_passing: MessagePassing,
        default_timeout: int = 30
    ):
        """
        Initialize distributed lock manager.
        
        Args:
            node_id: This node's ID
            raft: Raft consensus instance
            message_passing: Message passing instance
            default_timeout: Default lock timeout in seconds
        """
        self.node_id = node_id
        self.raft = raft
        self.message_passing = message_passing
        self.default_timeout = default_timeout
        
        # Lock storage
        # resource_id -> List[Lock]
        self.locks: Dict[str, List[Lock]] = defaultdict(list)
        
        # Wait queue for lock requests
        # resource_id -> List[(node_id, lock_type, timestamp)]
        self.wait_queue: Dict[str, List[tuple]] = defaultdict(list)
        
        # Deadlock detection
        # node_id -> Set[resource_id] (resources yang di-hold)
        self.held_resources: Dict[int, Set[str]] = defaultdict(set)
        
        # node_id -> Set[resource_id] (resources yang di-wait)
        self.waiting_resources: Dict[int, Set[str]] = defaultdict(set)
        
        # Background tasks
        self.cleanup_task: Optional[asyncio.Task] = None
        self.deadlock_detector_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.locks_acquired = 0
        self.locks_released = 0
        self.lock_denials = 0
        self.deadlocks_detected = 0
        
        logger.info(f"Distributed Lock Manager initialized for node {node_id}")
    
    async def start(self):
        """Start lock manager background tasks."""
        if self.running:
            return
        
        self.running = True
        
        # Start cleanup task (remove expired locks)
        self.cleanup_task = asyncio.create_task(self._cleanup_expired_locks())
        
        # Start deadlock detector
        self.deadlock_detector_task = asyncio.create_task(self._detect_deadlocks())
        
        # Register message handlers
        self.message_passing.register_handler(
            MessageType.LOCK_REQUEST,
            self._handle_lock_request
        )
        self.message_passing.register_handler(
            MessageType.LOCK_RELEASE,
            self._handle_lock_release
        )
        
        logger.info("Distributed Lock Manager started")
    
    async def stop(self):
        """Stop lock manager."""
        self.running = False
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
        if self.deadlock_detector_task:
            self.deadlock_detector_task.cancel()
        
        logger.info("Distributed Lock Manager stopped")
    
    async def acquire_lock(
        self,
        resource_id: str,
        lock_type: LockType = LockType.EXCLUSIVE,
        timeout: Optional[int] = None,
        wait: bool = True
    ) -> bool:
        """
        Acquire distributed lock untuk resource.
        
        Args:
            resource_id: ID of resource to lock
            lock_type: Type of lock (SHARED/EXCLUSIVE)
            timeout: Lock timeout in seconds (default_timeout if None)
            wait: Wait if lock not immediately available
            
        Returns:
            True if lock acquired, False otherwise
        """
        timeout = timeout or self.default_timeout
        
        # Jika bukan leader, forward request ke leader
        if not self.raft.is_leader():
            leader = self.raft.get_leader()
            if not leader:
                logger.warning("No leader available for lock acquisition")
                return False
            
            # Forward request ke leader
            return await self._forward_lock_request(leader, resource_id, lock_type, timeout)
        
        # Leader handles lock acquisition
        return await self._acquire_lock_local(resource_id, lock_type, timeout, wait)
    
    async def _acquire_lock_local(
        self,
        resource_id: str,
        lock_type: LockType,
        timeout: int,
        wait: bool
    ) -> bool:
        """Handle lock acquisition locally (leader only)."""
        
        # Check if lock can be granted
        if self._can_grant_lock(resource_id, lock_type):
            # Grant lock
            lock = Lock(
                resource_id=resource_id,
                lock_type=lock_type,
                holder_id=self.node_id,
                acquired_at=time.time(),
                expires_at=time.time() + timeout
            )
            
            self.locks[resource_id].append(lock)
            self.held_resources[self.node_id].add(resource_id)
            self.locks_acquired += 1
            
            # Replicate via Raft
            await self.raft.replicate_command({
                'type': 'acquire_lock',
                'resource_id': resource_id,
                'lock_type': lock_type.value,
                'node_id': self.node_id,
                'timeout': timeout
            })
            
            logger.info(
                f"Lock acquired: resource={resource_id}, type={lock_type.value}, "
                f"holder={self.node_id}"
            )
            return True
        
        # Lock not available
        if wait:
            # Add to wait queue
            self.wait_queue[resource_id].append((
                self.node_id,
                lock_type,
                time.time()
            ))
            self.waiting_resources[self.node_id].add(resource_id)
            logger.info(f"Added to wait queue: resource={resource_id}, node={self.node_id}")
            # TODO: Implement wait mechanism dengan timeout
            return False
        else:
            self.lock_denials += 1
            return False
    
    def _can_grant_lock(self, resource_id: str, lock_type: LockType) -> bool:
        """
        Check if lock can be granted.
        
        Rules:
        - EXCLUSIVE lock: no other locks on resource
        - SHARED lock: no EXCLUSIVE locks on resource
        """
        current_locks = self.locks.get(resource_id, [])
        
        # Remove expired locks
        current_locks = [lock for lock in current_locks if not lock.is_expired()]
        self.locks[resource_id] = current_locks
        
        if not current_locks:
            return True
        
        if lock_type == LockType.EXCLUSIVE:
            # Exclusive lock needs no other locks
            return len(current_locks) == 0
        else:
            # Shared lock allowed if no exclusive locks
            return all(lock.lock_type == LockType.SHARED for lock in current_locks)
    
    async def release_lock(self, resource_id: str) -> bool:
        """
        Release lock untuk resource.
        
        Args:
            resource_id: ID of resource to unlock
            
        Returns:
            True if lock released, False otherwise
        """
        # Jika bukan leader, forward ke leader
        if not self.raft.is_leader():
            leader = self.raft.get_leader()
            if not leader:
                logger.warning("No leader available for lock release")
                return False
            
            return await self._forward_lock_release(leader, resource_id)
        
        # Leader handles release
        return await self._release_lock_local(resource_id)
    
    async def _release_lock_local(self, resource_id: str) -> bool:
        """Handle lock release locally (leader only)."""
        current_locks = self.locks.get(resource_id, [])
        
        # Find and remove locks held by this node
        removed = False
        new_locks = []
        
        for lock in current_locks:
            if lock.holder_id == self.node_id:
                removed = True
                self.locks_released += 1
                logger.info(f"Lock released: resource={resource_id}, holder={self.node_id}")
            else:
                new_locks.append(lock)
        
        self.locks[resource_id] = new_locks
        
        if removed:
            self.held_resources[self.node_id].discard(resource_id)
            
            # Replicate via Raft
            await self.raft.replicate_command({
                'type': 'release_lock',
                'resource_id': resource_id,
                'node_id': self.node_id
            })
            
            # Process wait queue
            await self._process_wait_queue(resource_id)
        
        return removed
    
    async def _process_wait_queue(self, resource_id: str):
        """Process wait queue setelah lock released."""
        wait_queue = self.wait_queue.get(resource_id, [])
        
        if not wait_queue:
            return
        
        # Try to grant locks dari wait queue
        remaining_queue = []
        
        for node_id, lock_type, timestamp in wait_queue:
            if self._can_grant_lock(resource_id, lock_type):
                # Grant lock
                lock = Lock(
                    resource_id=resource_id,
                    lock_type=lock_type,
                    holder_id=node_id,
                    acquired_at=time.time(),
                    expires_at=time.time() + self.default_timeout
                )
                self.locks[resource_id].append(lock)
                self.held_resources[node_id].add(resource_id)
                self.waiting_resources[node_id].discard(resource_id)
                
                logger.info(f"Lock granted from wait queue: resource={resource_id}, node={node_id}")
            else:
                remaining_queue.append((node_id, lock_type, timestamp))
        
        self.wait_queue[resource_id] = remaining_queue
    
    async def _cleanup_expired_locks(self):
        """Background task untuk cleanup expired locks."""
        while self.running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                for resource_id, locks in list(self.locks.items()):
                    valid_locks = []
                    
                    for lock in locks:
                        if lock.is_expired():
                            logger.info(f"Lock expired: resource={resource_id}, holder={lock.holder_id}")
                            self.held_resources[lock.holder_id].discard(resource_id)
                        else:
                            valid_locks.append(lock)
                    
                    if valid_locks:
                        self.locks[resource_id] = valid_locks
                    else:
                        del self.locks[resource_id]
                        # Process wait queue
                        await self._process_wait_queue(resource_id)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)
    
    async def _detect_deadlocks(self):
        """
        Background task untuk detect deadlocks.
        Menggunakan wait-for graph cycle detection.
        """
        while self.running:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                
                # Build wait-for graph
                # node -> set of nodes it's waiting for
                wait_for_graph: Dict[int, Set[int]] = defaultdict(set)
                
                for node_id, waiting_resources in self.waiting_resources.items():
                    for resource_id in waiting_resources:
                        # Find who holds this resource
                        holders = [
                            lock.holder_id
                            for lock in self.locks.get(resource_id, [])
                        ]
                        wait_for_graph[node_id].update(holders)
                
                # Detect cycles using DFS
                visited = set()
                rec_stack = set()
                
                def has_cycle(node: int) -> bool:
                    visited.add(node)
                    rec_stack.add(node)
                    
                    for neighbor in wait_for_graph.get(node, set()):
                        if neighbor not in visited:
                            if has_cycle(neighbor):
                                return True
                        elif neighbor in rec_stack:
                            return True
                    
                    rec_stack.remove(node)
                    return False
                
                # Check for cycles
                for node in wait_for_graph:
                    if node not in visited:
                        if has_cycle(node):
                            self.deadlocks_detected += 1
                            logger.warning(f"Deadlock detected involving node {node}")
                            # TODO: Implement deadlock resolution strategy
                            # For now, just log it
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in deadlock detector: {e}", exc_info=True)
    
    async def _forward_lock_request(
        self,
        leader: str,
        resource_id: str,
        lock_type: LockType,
        timeout: int
    ) -> bool:
        """Forward lock request ke leader."""
        message = Message(
            msg_type=MessageType.LOCK_REQUEST,
            sender_id=self.node_id,
            receiver_id=-1,
            term=self.raft.current_term,
            timestamp=time.time(),
            data={
                'resource_id': resource_id,
                'lock_type': lock_type.value,
                'timeout': timeout
            }
        )
        
        response = await self.message_passing.send_message(leader, message)
        return response and response.data.get('granted', False)
    
    async def _forward_lock_release(self, leader: str, resource_id: str) -> bool:
        """Forward lock release ke leader."""
        message = Message(
            msg_type=MessageType.LOCK_RELEASE,
            sender_id=self.node_id,
            receiver_id=-1,
            term=self.raft.current_term,
            timestamp=time.time(),
            data={'resource_id': resource_id}
        )
        
        response = await self.message_passing.send_message(leader, message)
        return response and response.data.get('released', False)
    
    async def _handle_lock_request(self, message: Message) -> Message:
        """Handle lock request dari node lain."""
        resource_id = message.data['resource_id']
        lock_type = LockType(message.data['lock_type'])
        timeout = message.data.get('timeout', self.default_timeout)
        
        granted = await self._acquire_lock_local(resource_id, lock_type, timeout, wait=False)
        
        return Message(
            msg_type=MessageType.LOCK_RESPONSE,
            sender_id=self.node_id,
            receiver_id=message.sender_id,
            term=self.raft.current_term,
            timestamp=time.time(),
            data={'granted': granted, 'resource_id': resource_id}
        )
    
    async def _handle_lock_release(self, message: Message) -> Message:
        """Handle lock release dari node lain."""
        resource_id = message.data['resource_id']
        released = await self._release_lock_local(resource_id)
        
        return Message(
            msg_type=MessageType.LOCK_RESPONSE,
            sender_id=self.node_id,
            receiver_id=message.sender_id,
            term=self.raft.current_term,
            timestamp=time.time(),
            data={'released': released, 'resource_id': resource_id}
        )
    
    def get_lock_info(self, resource_id: str) -> Dict:
        """Get information tentang locks untuk resource."""
        locks = self.locks.get(resource_id, [])
        wait_queue = self.wait_queue.get(resource_id, [])
        
        return {
            'resource_id': resource_id,
            'active_locks': [
                {
                    'holder_id': lock.holder_id,
                    'type': lock.lock_type.value,
                    'acquired_at': lock.acquired_at,
                    'expires_at': lock.expires_at,
                }
                for lock in locks if not lock.is_expired()
            ],
            'wait_queue_size': len(wait_queue),
        }
    
    def get_statistics(self) -> Dict:
        """Get lock manager statistics."""
        total_locks = sum(len(locks) for locks in self.locks.values())
        total_waiting = sum(len(queue) for queue in self.wait_queue.values())
        
        return {
            'locks_acquired': self.locks_acquired,
            'locks_released': self.locks_released,
            'lock_denials': self.lock_denials,
            'deadlocks_detected': self.deadlocks_detected,
            'active_locks': total_locks,
            'waiting_requests': total_waiting,
            'success_rate': (
                self.locks_acquired / max(1, self.locks_acquired + self.lock_denials)
            ) * 100
        }
