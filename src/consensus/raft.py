"""
Raft Consensus Algorithm Implementation.
Implementasi yang disederhanakan untuk distributed lock coordination.

Referensi: 
- Raft Paper: https://raft.github.io/raft.pdf
- Raft Visualization: https://raft.github.io/

Raft memiliki 3 state: Follower, Candidate, Leader
"""

import asyncio
import random
import time
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
import logging

from ..communication.message_passing import MessagePassing, Message, MessageType

logger = logging.getLogger(__name__)


class RaftState(Enum):
    """State dalam Raft consensus."""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


@dataclass
class LogEntry:
    """
    Entry dalam Raft log.
    Setiap entry berisi command yang akan di-replicate.
    """
    term: int
    index: int
    command: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class RaftNode:
    """
    Implementasi Raft Consensus Algorithm.
    
    Fitur utama:
    1. Leader Election
    2. Log Replication
    3. Safety (consistency guarantee)
    """
    
    def __init__(
        self,
        node_id: int,
        cluster_nodes: List[str],
        message_passing: MessagePassing,
        election_timeout_min: int = 150,
        election_timeout_max: int = 300,
        heartbeat_interval: int = 50
    ):
        """
        Initialize Raft node.
        
        Args:
            node_id: Unique node ID
            cluster_nodes: List of all node addresses
            message_passing: Message passing instance
            election_timeout_min: Min election timeout (ms)
            election_timeout_max: Max election timeout (ms)
            heartbeat_interval: Heartbeat interval (ms)
        """
        self.node_id = node_id
        self.cluster_nodes = cluster_nodes
        self.message_passing = message_passing
        self.election_timeout_min = election_timeout_min / 1000  # Convert to seconds
        self.election_timeout_max = election_timeout_max / 1000
        self.heartbeat_interval = heartbeat_interval / 1000
        
        # Persistent state (harus di-persist di storage)
        self.current_term = 0
        self.voted_for: Optional[int] = None
        self.log: List[LogEntry] = []
        
        # Volatile state (semua nodes)
        self.commit_index = 0
        self.last_applied = 0
        
        # Volatile state (leader only)
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}
        
        # State management
        self.state = RaftState.FOLLOWER
        self.current_leader: Optional[str] = None
        self.last_heartbeat_time = time.time()
        
        # Election management
        self.votes_received = set()
        
        # Background tasks
        self.election_timer_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.elections_initiated = 0
        self.elections_won = 0
        self.heartbeats_sent = 0
        
        logger.info(f"Raft node {node_id} initialized")
    
    async def start(self):
        """Start Raft node."""
        if self.running:
            return
        
        self.running = True
        
        # Register message handlers
        self.message_passing.register_handler(
            MessageType.REQUEST_VOTE,
            self._handle_request_vote
        )
        self.message_passing.register_handler(
            MessageType.VOTE_RESPONSE,
            self._handle_vote_response
        )
        self.message_passing.register_handler(
            MessageType.APPEND_ENTRIES,
            self._handle_append_entries
        )
        self.message_passing.register_handler(
            MessageType.HEARTBEAT,
            self._handle_heartbeat
        )
        
        # Start election timer
        self.election_timer_task = asyncio.create_task(self._election_timer())
        
        logger.info(f"Raft node {self.node_id} started as {self.state.value}")
    
    async def stop(self):
        """Stop Raft node."""
        self.running = False
        
        if self.election_timer_task:
            self.election_timer_task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        
        logger.info(f"Raft node {self.node_id} stopped")
    
    def _reset_election_timer(self):
        """Reset election timer dengan random timeout."""
        self.last_heartbeat_time = time.time()
    
    def _get_election_timeout(self) -> float:
        """Get random election timeout."""
        return random.uniform(self.election_timeout_min, self.election_timeout_max)
    
    async def _election_timer(self):
        """
        Election timer loop.
        Jika tidak menerima heartbeat dalam timeout, start election.
        """
        while self.running:
            try:
                await asyncio.sleep(0.01)  # Check every 10ms
                
                # Only followers dan candidates perlu election timer
                if self.state == RaftState.LEADER:
                    continue
                
                elapsed = time.time() - self.last_heartbeat_time
                timeout = self._get_election_timeout()
                
                if elapsed >= timeout:
                    logger.info(f"Node {self.node_id}: Election timeout, starting election")
                    await self._start_election()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in election timer: {e}", exc_info=True)
    
    async def _start_election(self):
        """
        Start leader election.
        
        Process:
        1. Increment term
        2. Vote for self
        3. Request votes dari nodes lain
        4. Jika dapat majority votes, become leader
        """
        self.elections_initiated += 1
        
        # Convert to candidate
        self.state = RaftState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = {self.node_id}
        self._reset_election_timer()
        
        logger.info(f"Node {self.node_id}: Starting election for term {self.current_term}")
        
        # Prepare vote request
        last_log_index = len(self.log) - 1 if self.log else -1
        last_log_term = self.log[-1].term if self.log else 0
        
        vote_request = Message(
            msg_type=MessageType.REQUEST_VOTE,
            sender_id=self.node_id,
            receiver_id=-1,  # Broadcast
            term=self.current_term,
            timestamp=time.time(),
            data={
                'candidate_id': self.node_id,
                'last_log_index': last_log_index,
                'last_log_term': last_log_term,
            }
        )
        
        # Broadcast vote request
        await self.message_passing.broadcast_message(
            self.cluster_nodes,
            vote_request,
            wait_responses=False
        )
    
    async def _handle_request_vote(self, message: Message) -> Optional[Message]:
        """
        Handle vote request dari candidate.
        
        Vote granted jika:
        1. Candidate term >= current term
        2. Haven't voted atau voted for this candidate
        3. Candidate log as up-to-date as ours
        """
        candidate_id = message.data['candidate_id']
        candidate_term = message.term
        candidate_last_log_index = message.data['last_log_index']
        candidate_last_log_term = message.data['last_log_term']
        
        vote_granted = False
        
        # Update term jika candidate term lebih besar
        if candidate_term > self.current_term:
            self.current_term = candidate_term
            self.voted_for = None
            self.state = RaftState.FOLLOWER
        
        # Check if we can vote for this candidate
        if candidate_term == self.current_term:
            if self.voted_for is None or self.voted_for == candidate_id:
                # Check if candidate log up-to-date
                our_last_log_index = len(self.log) - 1 if self.log else -1
                our_last_log_term = self.log[-1].term if self.log else 0
                
                log_ok = (
                    candidate_last_log_term > our_last_log_term or
                    (candidate_last_log_term == our_last_log_term and
                     candidate_last_log_index >= our_last_log_index)
                )
                
                if log_ok:
                    vote_granted = True
                    self.voted_for = candidate_id
                    self._reset_election_timer()
        
        logger.debug(
            f"Node {self.node_id}: Vote {'granted' if vote_granted else 'denied'} "
            f"to candidate {candidate_id} for term {candidate_term}"
        )
        
        # Send vote response
        return Message(
            msg_type=MessageType.VOTE_RESPONSE,
            sender_id=self.node_id,
            receiver_id=candidate_id,
            term=self.current_term,
            timestamp=time.time(),
            data={
                'vote_granted': vote_granted,
                'voter_id': self.node_id,
            }
        )
    
    async def _handle_vote_response(self, message: Message) -> None:
        """
        Handle vote response dari voter.
        Jika dapat majority votes, become leader.
        """
        if self.state != RaftState.CANDIDATE:
            return
        
        vote_granted = message.data.get('vote_granted', False)
        voter_id = message.data.get('voter_id')
        
        if vote_granted and message.term == self.current_term:
            self.votes_received.add(voter_id)
            
            # Check if we have majority
            majority = (len(self.cluster_nodes) + 1) // 2 + 1
            
            if len(self.votes_received) >= majority:
                logger.info(
                    f"Node {self.node_id}: Won election for term {self.current_term} "
                    f"with {len(self.votes_received)} votes"
                )
                await self._become_leader()
    
    async def _become_leader(self):
        """Convert to leader state."""
        self.state = RaftState.LEADER
        self.current_leader = f"node-{self.node_id}"
        self.elections_won += 1
        
        # Initialize leader state
        last_log_index = len(self.log) - 1 if self.log else -1
        for node in self.cluster_nodes:
            self.next_index[node] = last_log_index + 1
            self.match_index[node] = -1
        
        # Start sending heartbeats
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        self.heartbeat_task = asyncio.create_task(self._send_heartbeats())
        
        logger.info(f"Node {self.node_id}: Became leader for term {self.current_term}")
    
    async def _send_heartbeats(self):
        """Send periodic heartbeats ke followers."""
        while self.running and self.state == RaftState.LEADER:
            try:
                await self.message_passing.send_heartbeat(
                    self.cluster_nodes,
                    self.current_term
                )
                self.heartbeats_sent += 1
                
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error sending heartbeats: {e}", exc_info=True)
    
    async def _handle_heartbeat(self, message: Message) -> Optional[Message]:
        """Handle heartbeat dari leader."""
        if message.term >= self.current_term:
            self.current_term = message.term
            self.state = RaftState.FOLLOWER
            self._reset_election_timer()
            
            # Update current leader
            self.current_leader = f"node-{message.sender_id}"
        
        return None
    
    async def _handle_append_entries(self, message: Message) -> Optional[Message]:
        """Handle append entries RPC dari leader."""
        # Simplified implementation untuk demo
        # Production implementation perlu handle log replication properly
        
        if message.term >= self.current_term:
            self.current_term = message.term
            self.state = RaftState.FOLLOWER
            self._reset_election_timer()
        
        return Message(
            msg_type=MessageType.APPEND_ENTRIES_RESPONSE,
            sender_id=self.node_id,
            receiver_id=message.sender_id,
            term=self.current_term,
            timestamp=time.time(),
            data={'success': True}
        )
    
    def is_leader(self) -> bool:
        """Check if this node is leader."""
        return self.state == RaftState.LEADER
    
    def get_leader(self) -> Optional[str]:
        """Get current leader address."""
        return self.current_leader
    
    async def replicate_command(self, command: Dict[str, Any]) -> bool:
        """
        Replicate command ke cluster (leader only).
        
        Args:
            command: Command to replicate
            
        Returns:
            True if successfully replicated to majority
        """
        if not self.is_leader():
            logger.warning(f"Node {self.node_id} is not leader, cannot replicate")
            return False
        
        # Add to log
        entry = LogEntry(
            term=self.current_term,
            index=len(self.log),
            command=command
        )
        self.log.append(entry)
        
        # TODO: Implement proper log replication
        # Simplified version assumes immediate success
        self.commit_index = len(self.log) - 1
        
        logger.info(f"Leader {self.node_id}: Replicated command {command}")
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get Raft statistics."""
        return {
            'node_id': self.node_id,
            'state': self.state.value,
            'current_term': self.current_term,
            'current_leader': self.current_leader,
            'log_size': len(self.log),
            'commit_index': self.commit_index,
            'elections_initiated': self.elections_initiated,
            'elections_won': self.elections_won,
            'heartbeats_sent': self.heartbeats_sent,
        }
