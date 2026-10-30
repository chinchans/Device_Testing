"""
Type definitions for Catalyst Datastreams module.

This module contains type definitions and interfaces for the Catalyst Datastreams service,
including token responses, channel details, and API responses.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Union, TypedDict


class TokenResponse(TypedDict):
    """
    Token response when getting token pair for datastream channel authentication.

    Attributes:
        wss-id: WebSocket session identifier
        channel-id: Channel identifier
        key: Authentication key for the connection
        url: WebSocket URL for connection
    """
    wss_id: str  # Using wss_id instead of 'wss-id' for Python naming convention
    channel_id: str  # Using channel_id instead of 'channel-id' for Python naming convention
    key: str
    url: str


class ChannelDetails(TypedDict):
    """
    Individual channel information.

    Attributes:
        parentId: Parent channel ID
        id: Unique channel identifier
        name: Channel name
        service: Service type (typically "catalyst")
        created_by: ID of user who created the channel
        modified_by: ID of user who last modified the channel
        created_time: Timestamp when channel was created
        modified_time: Timestamp when channel was last modified
        project_id: Project ID this channel belongs to
        control_type: Control type for the channel
        control_ids: Comma-separated control IDs
        source: Source information
        status: Channel status (e.g., "open")
    """
    parentId: int
    id: int
    name: str
    service: str
    created_by: int
    modified_by: int
    created_time: int
    modified_time: int
    project_id: int
    control_type: int
    control_ids: str
    source: str
    status: str


class ChannelLiveCountResponse(TypedDict):
    """
    Channel live count response.

    Attributes:
        connections: Number of active connections to the channel
    """
    connections: int


class PublishDataResponse(TypedDict, total=False):
    """
    Publish data response.

    Attributes:
        message: Success message or response data (optional)
        Additional fields can be included as key-value pairs
    """
    message: Optional[str]
    # Additional fields can be added dynamically


class DatastreamErrorResponse(TypedDict, total=False):
    """
    Datastream API error response.

    Attributes:
        code: Error code
        message: Error message
        details: Additional error details (optional)
    """
    code: str
    message: str
    details: Optional[Any]


# Type aliases for API responses
GetChannelResponse = ChannelDetails
GetAllChannelsResponse = List[ChannelDetails]

# Union types for common parameters
ChannelIdentifier = Union[str, int]
UserIdentifier = Union[str, int]

# Response type for general API calls
DatastreamsResponse = Dict[str, Any]

# Type for token pair request payload
class TokenPairPayload(TypedDict, total=False):
    """
    Payload for token pair request.

    Attributes:
        app_user_id: Application user ID (optional)
        connection_name: Connection name (optional)
    """
    app_user_id: Optional[int]
    connection_name: Optional[str]


# Type for publish data payload
class PublishDataPayload(TypedDict):
    """
    Payload for publishing data to a channel.

    Attributes:
        data: The data to be published
    """
    data: str


# Enumeration-like constants for channel status
class ChannelStatus:
    """Constants for channel status values."""
    OPEN = "open"
    CLOSED = "closed"
    ACTIVE = "active"
    INACTIVE = "inactive"


# Enumeration-like constants for service types
class ServiceType:
    """Constants for service type values."""
    CATALYST = "catalyst"


# Type for HTTP method constants
HttpMethod = str

# Type for API endpoints
ApiEndpoint = str

# Generic response wrapper
class ApiResponse(TypedDict, total=False):
    """
    Generic API response wrapper.

    Attributes:
        status: Response status
        data: Response data
        error: Error information (if any)
        timestamp: Response timestamp
    """
    status: str
    data: Optional[Any]
    error: Optional[DatastreamErrorResponse]
    timestamp: Optional[str]

# Type definitions for DataStreams WebSocket client.


class MessageType(str, Enum):
    """Message types for DataStreams WebSocket communication."""
    SWITCH_URL = "-1"
    MISSING_KEY = "-2"
    AUTH_FAILED = "-5"
    SESSION_EXPIRED = "-11"
    AUTH_SUCCESS = "0"
    BLOCKED = "660"
    DATA_EVENT = "650"
    SERVER_DOWN = "670"


class ConnectionState(str, Enum):
    """WebSocket connection states."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class DataStreamsConfig:
    """Configuration for DataStreams WebSocket client."""

    def __init__(
        self,
        url: str,
        zuid: str,
        key: str,
        enable_logging: bool = False,
        ping_interval: int = 15,
        reconnect_timeout: int = 27 * 60,  # 27 minutes
        server_ping_interval: int = 60
    ):
        """
        Initialize DataStreams configuration.

        Args:
            url: The WebSocket server URL
            zuid: Zone User ID for authentication
            key: Authentication key
            enable_logging: Whether to enable debug logging
            ping_interval: Interval between ping messages (seconds)
            reconnect_timeout: Time before automatic reconnection (seconds)
            server_ping_interval: Interval for server ping when down (seconds)
        """
        self.url = url
        self.zuid = zuid
        self.key = key
        self.enable_logging = enable_logging
        self.ping_interval = ping_interval
        self.reconnect_timeout = reconnect_timeout
        self.server_ping_interval = server_ping_interval


class CustomEvent:
    """Custom event for DataStreams client."""

    def __init__(self, code: int, message: str, data: Optional[Any] = None):
        """
        Initialize custom event.

        Args:
            code: Event code
            message: Event message
            data: Optional event data
        """
        self.code = code
        self.message = message
        self.data = data

class DataStreamMessageEvent:
    """Data stream message event."""

    def __init__(
        self,
        streaming_id: str,
        data: Optional[str] = None,
        url: Optional[str] = None,
        method: Optional[str] = None
    ):
        """
        Initialize data stream message event.

        Args:
            streaming_id: Unique streaming identifier
            data: Message data (for event operations)
            url: API URL (for api operations)
            method: HTTP method (for api operations)
        """
        self.streaming_id = streaming_id
        self.data = data
        self.url = url
        self.method = method

class DataStreamErrorEvent(CustomEvent):
    """Error event raised for DataStreams subscription failures."""

    def __init__(self, message: str, code: int = 0, data: Optional[Any] = None):
        super().__init__(code, message, data)


class SubscribePayload:
    """Payload for subscription requests."""

    def __init__(self, streaming_id: Union[str, int] = "0"):
        """
        Initialize subscribe payload.

        Args:
            streaming_id: Streaming ID for subscription type
                         "0" - live events
                         "-1" - earliest available events
                         "-2" - resume from previous
                         specific ID - resume from that ID
        """
        self.type = "con"
        self.value = "subscribe"
        self.streaming_id = str(streaming_id)

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "value": self.value,
            "streamingId": self.streaming_id
        }


class AckPayload:
    """Payload for acknowledgment messages."""

    def __init__(self, streaming_id: str = ""):
        """
        Initialize acknowledgment payload.

        Args:
            streaming_id: Streaming ID to acknowledge
        """
        self.type = "ack"
        self.streaming_id = streaming_id

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "streamingId": self.streaming_id
        }


class UnsubscribePayload:
    """Payload for unsubscription requests."""

    def __init__(self):
        """Initialize unsubscribe payload."""
        self.type = "con"
        self.value = "unsubscribe"

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "value": self.value
        }


class ServerPingPayload:
    """Payload for server ping messages."""

    def __init__(self):
        """Initialize server ping payload."""
        self.type = "con"
        self.value = "ping"

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "value": self.value
        }


class SessionInfo:
    """Session information for reconnection."""

    def __init__(self, sid: str = "", uid: str = ""):
        """
        Initialize session info.

        Args:
            sid: Session ID
            uid: User ID
        """
        self.sid = sid
        self.uid = uid


# Protocol for WebSocket-like interface
class WebSocketProtocol(Protocol):
    """Protocol defining WebSocket-like interface."""

    def send(self, data: str) -> None:
        """Send data through WebSocket."""

    def close(self, code: int = 1000, reason: str = "") -> None:
        """Close WebSocket connection."""

    @property
    def readyState(self) -> int:  # pylint: disable=invalid-name
        """Get WebSocket ready state."""

    # WebSocket ready state constants
    CONNECTING: int
    OPEN: int
    CLOSING: int
    CLOSED: int
