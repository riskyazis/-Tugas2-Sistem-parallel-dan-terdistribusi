"""
Message passing system untuk inter-node communication.
Menggunakan aiohttp untuk async HTTP communication.
"""

import asyncio
import aiohttp
import orjson
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Tipe-tipe message dalam distributed system."""
    # Raft messages
    REQUEST_VOTE = "request_vote"
    VOTE_RESPONSE = "vote_response"
    APPEND_ENTRIES = "append_entries"
    APPEND_ENTRIES_RESPONSE = "append_entries_response"
    
    # Lock messages
    LOCK_REQUEST = "lock_request"
    LOCK_RESPONSE = "lock_response"
    LOCK_RELEASE = "lock_release"
    DEADLOCK_DETECT = "deadlock_detect"
    
    # Queue messages
    QUEUE_ENQUEUE = "queue_enqueue"
    QUEUE_DEQUEUE = "queue_dequeue"
    QUEUE_ACK = "queue_ack"
    
    # Cache messages
    CACHE_INVALIDATE = "cache_invalidate"
    CACHE_UPDATE = "cache_update"
    CACHE_SYNC = "cache_sync"
    
    # Health check
    HEARTBEAT = "heartbeat"
    PING = "ping"
    PONG = "pong"


@dataclass
class Message:
    """
    Base message class untuk semua komunikasi antar node.
    """
    msg_type: MessageType
    sender_id: int
    receiver_id: int
    term: int  # Raft term
    timestamp: float
    data: Dict[str, Any]
    message_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        result = asdict(self)
        result['msg_type'] = self.msg_type.value
        return result
    
    def to_json(self) -> bytes:
        """Serialize message to JSON."""
        return orjson.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary."""
        data['msg_type'] = MessageType(data['msg_type'])
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_data: bytes) -> 'Message':
        """Deserialize message from JSON."""
        data = orjson.loads(json_data)
        return cls.from_dict(data)


class MessagePassing:
    """
    Handler untuk sending dan receiving messages antar nodes.
    Menggunakan HTTP/JSON untuk simplicity, bisa diganti dengan gRPC untuk production.
    """
    
    def __init__(self, node_id: int, node_host: str, node_port: int):
        self.node_id = node_id
        self.node_host = node_host
        self.node_port = node_port
        self.session: Optional[aiohttp.ClientSession] = None
        self.message_handlers = {}
        self.pending_responses = {}
        
        # Statistics
        self.messages_sent = 0
        self.messages_received = 0
        self.failed_sends = 0
    
    async def start(self):
        """Initialize HTTP client session."""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            logger.info(f"Message passing initialized for node {self.node_id}")
    
    async def stop(self):
        """Close HTTP client session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info(f"Message passing stopped for node {self.node_id}")
    
    def register_handler(self, msg_type: MessageType, handler):
        """
        Register handler function untuk message type tertentu.
        
        Args:
            msg_type: Tipe message
            handler: Async function yang akan handle message
        """
        self.message_handlers[msg_type] = handler
        logger.debug(f"Registered handler for {msg_type.value}")
    
    async def send_message(
        self,
        target_node: str,
        message: Message,
        wait_response: bool = True,
        timeout: float = 5.0
    ) -> Optional[Message]:
        """
        Send message ke target node.
        
        Args:
            target_node: Address dalam format "host:port"
            message: Message object to send
            wait_response: Wait for response jika True
            timeout: Response timeout in seconds
            
        Returns:
            Response message jika wait_response=True, None otherwise
        """
        if not self.session:
            await self.start()
        
        url = f"http://{target_node}/api/message"
        
        try:
            async with self.session.post(
                url,
                data=message.to_json(),
                headers={'Content-Type': 'application/json'}
            ) as response:
                self.messages_sent += 1
                
                if wait_response:
                    if response.status == 200:
                        response_data = await response.json()
                        return Message.from_dict(response_data)
                    else:
                        logger.warning(
                            f"Received non-200 status from {target_node}: {response.status}"
                        )
                        return None
                
                return None
                
        except asyncio.TimeoutError:
            logger.error(f"Timeout sending message to {target_node}")
            self.failed_sends += 1
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Error sending message to {target_node}: {e}")
            self.failed_sends += 1
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending message to {target_node}: {e}")
            self.failed_sends += 1
            return None
    
    async def broadcast_message(
        self,
        target_nodes: List[str],
        message: Message,
        wait_responses: bool = False
    ) -> List[Optional[Message]]:
        """
        Broadcast message ke multiple nodes.
        
        Args:
            target_nodes: List of node addresses
            message: Message to broadcast
            wait_responses: Wait for all responses
            
        Returns:
            List of responses if wait_responses=True
        """
        tasks = []
        for node in target_nodes:
            # Skip sending to self
            if node == f"{self.node_host}:{self.node_port}":
                continue
            
            task = self.send_message(node, message, wait_response=wait_responses)
            tasks.append(task)
        
        if tasks:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            # Filter out exceptions
            return [r for r in responses if isinstance(r, Message) or r is None]
        
        return []
    
    async def handle_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming message dari node lain.
        
        Args:
            message_data: Raw message data
            
        Returns:
            Response data dictionary
        """
        try:
            message = Message.from_dict(message_data)
            self.messages_received += 1
            
            # Check if handler registered untuk message type ini
            if message.msg_type in self.message_handlers:
                handler = self.message_handlers[message.msg_type]
                response = await handler(message)
                
                if response:
                    return response.to_dict()
                    
            else:
                logger.warning(f"No handler registered for {message.msg_type.value}")
            
            # Default response
            return {
                'status': 'ok',
                'node_id': self.node_id,
                'timestamp': time.time()
            }
            
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e),
                'node_id': self.node_id
            }
    
    async def send_heartbeat(self, target_nodes: List[str], term: int):
        """
        Send heartbeat ke semua nodes (untuk Raft).
        
        Args:
            target_nodes: List of target node addresses
            term: Current Raft term
        """
        message = Message(
            msg_type=MessageType.HEARTBEAT,
            sender_id=self.node_id,
            receiver_id=-1,  # Broadcast
            term=term,
            timestamp=time.time(),
            data={}
        )
        
        await self.broadcast_message(target_nodes, message, wait_responses=False)
    
    async def ping(self, target_node: str) -> bool:
        """
        Ping target node untuk health check.
        
        Args:
            target_node: Target node address
            
        Returns:
            True if node is alive, False otherwise
        """
        message = Message(
            msg_type=MessageType.PING,
            sender_id=self.node_id,
            receiver_id=-1,
            term=0,
            timestamp=time.time(),
            data={}
        )
        
        response = await self.send_message(target_node, message, wait_response=True, timeout=2.0)
        return response is not None and response.msg_type == MessageType.PONG
    
    def get_statistics(self) -> Dict[str, int]:
        """Get message passing statistics."""
        return {
            'messages_sent': self.messages_sent,
            'messages_received': self.messages_received,
            'failed_sends': self.failed_sends,
            'success_rate': (
                self.messages_sent / max(1, self.messages_sent + self.failed_sends)
            ) * 100
        }
