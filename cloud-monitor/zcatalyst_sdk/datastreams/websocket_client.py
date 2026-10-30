"""
Enhanced WebSocket DataStreams Client

A modern Python implementation of the DataStreams WebSocket client
with improved error handling, type safety, and cross-platform support.
"""

import json
import logging
import threading
from typing import Optional, Callable, Any, Dict, List
from urllib.parse import urlencode

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

from ..types.datastreams import (
    DataStreamsConfig,
    MessageType,
    CustomEvent,
    DataStreamMessageEvent,
    ConnectionState,
    SubscribePayload,
    AckPayload,
    UnsubscribePayload,
    ServerPingPayload,
    SessionInfo,
    WebSocketProtocol
)

# Allowlist of DataStreams WebSocket hosts, used to validate the connection
# URL before opening a socket, in order to prevent server-side request
# forgery (SSRF) via a malicious/untrusted host value.
ALLOWED_DATASTREAM_HOSTS = frozenset(
    host.lower() for host in [
        # US
        'us4-dms.zoho.com',
        'us3-dms.zoho.com',
        # US PRE
        'predms.zoho.com',
        # EU
        'eu1-dms.zoho.eu',
        'eu2-dms.zoho.eu',
        # IN
        'in2-dms.zoho.in',
        'in1-dms.zoho.in',
        # AU
        'au1-dms.zoho.com.au',
        'au2-dms.zoho.com.au',
        # CN
        'cn2-dms.zoho.com.cn',
        'cn3-dms.zoho.com.cn',
        # JP
        'jp1-dms.zoho.jp',
        'jp2-dms.zoho.jp',
        # CA
        'ca1-dms.zohocloud.ca',
        'ca2-dms.zohocloud.ca',
        # UK
        'uk1-dms.zoho.uk',
        'uk2-dms.zoho.uk',
        # LOCAL
        'local-dms.localzoho.com',
        'ct2-dms.localzoho.com',
        # LOCAL PRE
        'predms.localzoho.com',
        'ct2-predms.localzoho.com',
        # SA
        'sa1-dms.zoho.sa',
        'sa2-dms.zoho.sa',
        # UAE
        'uae1-dms.zoho.ae',
        'uae2-dms.zoho.ae'
    ]
)


class DataStreamsWebSocket:
    """
    Enhanced DataStreams WebSocket client with modern Python features.

    This client provides real-time communication with Catalyst DataStreams service
    using WebSocket protocol with automatic reconnection, ping/pong handling,
    and comprehensive error management.
    """

    def __init__(
        self,
        config: Optional[DataStreamsConfig] = None,
        url: Optional[str] = None,
        zuid: Optional[str] = None,
        key: Optional[str] = None
    ):
        """
        Initialize DataStreams WebSocket client.

        Args:
            config: DataStreams configuration object (preferred)
            url: WebSocket server URL (legacy)
            zuid: Zone User ID (legacy)
            key: Authentication key (legacy)

        Raises:
            ImportError: If websocket-client is not installed
            ValueError: If required parameters are missing
        """
        if not WEBSOCKET_AVAILABLE:
            raise ImportError(
                "websocket-client is required for DataStreams WebSocket functionality. "
                "Install it with: pip install websocket-client"
            )

        # Support both new object-style and legacy parameter-style constructors
        if config is not None:
            self.config = config
        elif url and zuid and key:
            self.config = DataStreamsConfig(url=url, zuid=zuid, key=key)
        else:
            raise ValueError("Either config object or url/zuid/key parameters are required")

        # Initialize logging
        self.logger = logging.getLogger(__name__)
        if self.config.enable_logging:
            self.logger.setLevel(logging.DEBUG)
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter('[DataStreams] %(levelname)s: %(message)s')
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)

        # Configuration
        self.prd_value = "CY"
        self.path = "/wsconnect"

        # Connection properties
        self.url = self._validate_datastream_host(self.config.url)
        self.key_value = self.config.key
        self.zuid_value = self.config.zuid
        self.session_info = SessionInfo()

        # WebSocket instance
        self.conn: Optional[WebSocketProtocol] = None
        self.ws_thread: Optional[threading.Thread] = None

        # State management
        self.is_open = False
        self.manual_closure = False
        self.ack_sent = False
        self.ack_trigger_received = False
        self.reconnect = False
        self.prev_streaming_id = ""

        # Threading and intervals
        self.ping_timer: Optional[threading.Timer] = None
        self.reconnect_timer: Optional[threading.Timer] = None
        self.server_ping_timer: Optional[threading.Timer] = None
        self._stop_event = threading.Event()

        # Payload templates
        self.subscribe_payload = SubscribePayload()
        self.ack_payload = AckPayload()
        self.unsubscribe_payload = UnsubscribePayload()
        self.server_ping_payload = ServerPingPayload()

        # Event callbacks
        self.on_open: Optional[Callable[[CustomEvent], None]] = None
        self.on_message: Optional[Callable[[DataStreamMessageEvent], None]] = None
        self.on_error: Optional[Callable[[CustomEvent], None]] = None
        self.on_close: Optional[Callable[[Any], None]] = None
        self.on_pong: Optional[Callable[[CustomEvent], None]] = None

        # Fallback connection count for key mismatch scenario
        self.fallback_connection_attempts = 0

        # Build initial WebSocket URL
        self._build_websocket_url()

    @staticmethod
    def _validate_datastream_host(url: str) -> str:
        """
        Validate that the given DataStreams host is part of the known
        allowlist of Catalyst DataStreams hosts, to prevent server-side
        request forgery (SSRF) via an untrusted/attacker-controlled URL.

        Args:
            url: The DataStreams host (e.g. "us4-dms.zoho.com")

        Returns:
            The validated host string.

        Raises:
            ValueError: If the host is missing or not in the allowlist.
        """
        host = DataStreamsWebSocket._strip_scheme(url)
        if not host or host not in ALLOWED_DATASTREAM_HOSTS:
            raise ValueError(
                f"Invalid or untrusted DataStreams host: '{url}'. "
                "The host must be one of the officially supported Catalyst "
                "DataStreams domains."
            )
        return host

    @staticmethod
    def _strip_scheme(url: Optional[str]) -> str:
        """Remove any protocol prefix (https://, wss://, ...) and trailing slashes."""
        host = (url or "").strip().lower()
        if "://" in host:
            host = host.split("://", 1)[1]
        return host.rstrip("/")

    def _build_websocket_url(self) -> None:
        """Build the WebSocket connection URL."""
        params = {
            'prd': self.prd_value,
            'zuid': self.zuid_value,
            'key': self.key_value
        }

        if self.session_info.sid and self.session_info.uid:
            # Reconnection URL with session info
            params = {
                'key': self.key_value,
                'i': self.session_info.sid,
                'c': self.session_info.uid
            }

        query_string = urlencode(params)
        # Re-validate on every build so no code path can send the key to an unlisted hos
        host = self._validate_datastream_host(self.url)
        self.final_url = f"wss://{host}{self.path}?{query_string}"

    def _log(self, message: str, level: str = "info") -> None:
        """Log messages if logging is enabled."""
        if self.config.enable_logging:
            getattr(self.logger, level)(message)

    def connect(self) -> None:
        """
        Create WebSocket connection.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            self._log("Creating WebSocket connection")

            # Create WebSocket with event handlers
            self.conn = websocket.WebSocketApp(
                self.final_url,
                on_open=self._on_websocket_open,
                on_message=self._on_websocket_message,
                on_error=self._on_websocket_error,
                on_close=self._on_websocket_close
            )

            # Start WebSocket in a separate thread
            self.ws_thread = threading.Thread(
                target=self.conn.run_forever,
                kwargs={'ping_interval': 0}  # We handle ping manually
            )
            self.ws_thread.daemon = True
            self.ws_thread.start()

        except Exception as err:
            error_msg = f"Error creating WebSocket connection: {err}"
            self._log(error_msg, "error")
            if self.on_error:
                self.on_error(CustomEvent(1006, "Failed to create WebSocket connection", str(err)))
            raise ConnectionError(error_msg) from err

    def _on_websocket_open(self, _ws) -> None:
        """Handle WebSocket open event."""
        self._log("WebSocket connection opened")

        if self.reconnect:
            self._log("Reconnection event successful!")

            if self._is_websocket_open():
                self._log(f"Subscribe payload: {json.dumps(self.subscribe_payload.to_dict())}")
                if self.ack_sent:
                    self.subscribe_payload.streaming_id = "-2"
                    self.conn.send(json.dumps(self.subscribe_payload.to_dict()))

            # Subsequent ping and reconnection will be handled here
            self._start_ping()
            self._start_ping_to_server()
            self._start_close_and_reconnect()
            self.reconnect = False

        self.is_open = True

    def _on_websocket_close(self, wsock, close_status_code, close_msg) -> None:
        """Handle WebSocket close event."""
        if wsock is not self.conn:
            # Stale connection that was replaced by a newer one; don't tear down the new state
            return
        if not self.manual_closure:
            # When connection is closed by user / due to other interference
            if self.on_close:
                self.on_close({'code': close_status_code, 'message': close_msg})
            self._clear_all_timers()
            self.is_open = False
            self.manual_closure = False
        # else will be closed via code for reconnect operation

    def _on_websocket_error(self, _ws, error) -> None:
        """Handle WebSocket error event."""
        error_msg = f"WebSocket error: {error}"
        if self.on_error:
            self.on_error(CustomEvent(1006, error_msg, str(error)))

    def _on_websocket_message(self, _ws, message) -> None:
        """Handle WebSocket message event."""
        self._handle_dms_events(message)

    def _handle_dms_events(self, event: str) -> None:
        """
        Handle DataStreams events - main message processing logic.

        ALL Catalyst connection and data events will be handled here:
        1. Connection based on mtype key
        2. Data events (catalyst) will be handled in data key

        mtypes:
        -1 -> to connect using RO/new RW url during switch/issue in DMS servers
        -2 -> Param key is missing in connection
        -5 -> Authentication failed from service (catalyst) team
        -11 -> Current session gets expired after 30 mins; should reconnect with sid and uid
        0 -> Connection established after successful authentication
        660 -> Connection is blocked due DDOS attack from zoho side
        650 -> Actual service data events will be handled here
        670 -> When service (catalyst) server is not reachable
        """
        if not event or event == "":
            # Handle pong event
            if self.on_pong:
                self.on_pong(CustomEvent(200, "Pong received"))
            return

        try:
            json_data: List[Dict[str, Any]] = json.loads(event)
            mtype = json_data[0].get('mtype')

            if mtype == MessageType.SWITCH_URL:
                payload = json_data[0]
                nested = payload.get('msg')
                source = nested if isinstance(nested, dict) and 'primarydc' in nested else payload
                new_host = source.get(source.get('primarydc', ''))
                if not new_host:
                    self._log("SWITCH_URL message has no usable primary host; ignoring", "error")
                    return
                try:
                    # Server-supplied host must pass the same allowlist as the initial URL
                    self.url = self._validate_datastream_host(new_host)
                except ValueError as err:
                    self._log(f"Ignoring SWITCH_URL: {err}", "error")
                    if self.on_error:
                        self.on_error(CustomEvent(
                            1014,
                            "Received an untrusted DataStreams host; connection not switched"))
                    return

                if self._is_websocket_open():
                    self.manual_closure = False
                    self.conn.close()
                    if self.on_close:
                        self.on_close({
                            'code': 1000,
                            'message': 'Closing this connection and opening new connection!'})
                    self._make_new_connection()

            elif mtype == MessageType.MISSING_KEY:
                # Mandatory param 'key' is missing
                if self.on_error:
                    self.on_error(CustomEvent(1014, "Mandatory param key is missing"))

            elif mtype == MessageType.AUTH_FAILED:
                # Authentication failed from catalyst side
                # DMS cannot reach Catalyst server, on timeout this event will be given
                # User should generate new token pair
                self._log("-5 triggered")
                if self.on_error:
                    self.on_error(CustomEvent(
                        3000,
                        "Authentication failed, please generate valid credentials "
                        "and try again after some time!"
                    ))

            elif mtype == MessageType.SESSION_EXPIRED:
                # Current connections expired in 30 mins

                # New connections should be made with new credentials
                is_key_mismatch = 'key_mismatch' in str(json_data[0].get('reason'))

                is_invalid_request = 'Invalid Request' in str(json_data[0].get('reason'))

                is_connection_alive = is_key_mismatch or is_invalid_request
                # previous connection is still alive, try connecting again with same credentials
                if is_connection_alive and self.fallback_connection_attempts == 0:
                    self.fallback_connection_attempts += 1
                    previous_conn = self.conn
                    self.connect()
                    # Close the old socket so two run_forever threads never stay open together
                    if previous_conn is not None:
                        previous_conn.close()
                else:
                    if self.on_error:
                        self.on_error(CustomEvent(
                            1000,
                            "Current session will be closed. New connection to be established."
                        ))
                    self._log("WebSocket connection got expired. "
                              "Please generate new credentials to connect again")

            elif mtype == MessageType.AUTH_SUCCESS:
                # Authentication is success from catalyst
                # Subscribe request has to be made from here to actually receive data from channel
                msg = json_data[0].get('msg', {})
                self.session_info.sid = msg.get('sid', '')
                self.session_info.uid = msg.get('uid', '')

                if self.on_open:
                    self.on_open(CustomEvent(
                        200,
                        "Streams connection established, please subscribe with appropriate "
                        "subscribe type to start streaming."
                    ))

                # First time ping and reconnection will be called here
                self._start_ping()
                self._start_ping_to_server()
                # self._start_close_and_reconnect()  # Uncomment if needed

            elif mtype == MessageType.BLOCKED:
                # Connection is blocked from DMS due to DOS
                if self.on_error:
                    self.on_error(CustomEvent(
                        1013,
                        "Data streams connection is blocked! Please contact support!"
                    ))

            elif mtype == MessageType.DATA_EVENT:
                # Actual data event from catalyst will be handled here
                self._handle_data_events(json_data)

            elif mtype == MessageType.SERVER_DOWN:
                # When catalyst app server is down - Retry connection in 5 mins
                self._log("-> 670 server is down")
                self._start_ping_to_server()
                if self.on_error:
                    self.on_error(CustomEvent(
                        1011,
                        "Internal server error. Please retry after a minute"
                    ))
            else:
                self._log(f"Unknown message type: {mtype}")

        except json.JSONDecodeError as err:
            self._log(f"Error parsing WebSocket message: {err}", "error")
        except Exception as err:  # pylint: disable=broad-except
            self._log(f"Error handling WebSocket message: {err}", "error")

    def _handle_data_events(self, json_data: List[Dict[str, Any]]) -> None:
        """Handle data events (message type 650)."""
        for data_item in json_data:
            msg = data_item.get('msg', {})
            data = msg.get('data', {})

            streaming_id = data.get('streamingId', '')

            if self.prev_streaming_id == streaming_id and self.ack_sent:
                # Skipping if streaming id already processed
                self._log(f"prev :: {self.prev_streaming_id}, current :: {streaming_id}")
                self.ack_payload.streaming_id = self.prev_streaming_id
                if self._is_websocket_open():
                    self.conn.send(json.dumps(self.ack_payload.to_dict()))
            else:
                operation = msg.get('opr', '')

                if operation == 'event':
                    self.ack_sent = False
                    self.prev_streaming_id = streaming_id
                    self.ack_payload.streaming_id = streaming_id

                    if self.on_message:
                        self.on_message(DataStreamMessageEvent(
                            streaming_id=streaming_id,
                            data=data.get('data')
                        ))

                elif operation == 'api':
                    self.ack_sent = False
                    self.ack_payload.streaming_id = streaming_id
                    self.prev_streaming_id = streaming_id

                    if self.on_message:
                        self.on_message(DataStreamMessageEvent(
                            streaming_id=streaming_id,
                            url=data.get('url'),
                            method=data.get('method')
                        ))

                elif operation == 'connect':
                    # clearing ping to server on interval process
                    # Sending ack to start streaming
                    if self.ack_sent and self._is_websocket_open():
                        ack_payload = AckPayload("-2")
                        self._log("Ack payload for pong")
                        self.conn.send(json.dumps(ack_payload.to_dict()))

                elif operation == 'error':
                    error_code = data.get('code')
                    self._log(f"Error event received: {error_code}", "error")
                    if self.on_error and (error_code in ("e3", "e5")):
                        self.on_error(CustomEvent(1000,
                                    "Subscription failed. Invalid subscription type."))

    def _is_websocket_open(self) -> bool:
        """Check if WebSocket is open and ready."""
        return (self.conn is not None and
                hasattr(self.conn, 'sock') and
                self.conn.sock is not None and
                self.conn.sock.connected)

    def _make_new_connection(self) -> None:
        """Create new WebSocket connection for reconnection."""
        if self.session_info.sid and self.session_info.uid:
            self._build_websocket_url()
            # Query string carries key/session secrets; never log it
            self._log(
                f"New connection URL: wss://{self._strip_scheme(self.url)}{self.path}?<redacted>")
            self.connect()

    def _clear_all_timers(self) -> None:
        """Clear all active timers."""
        self._clear_ping_timer()
        self._clear_reconnect_timer()
        self._clear_server_ping_timer()

    def _clear_ping_timer(self) -> None:
        """Clear ping timer."""
        if self.ping_timer:
            self.ping_timer.cancel()
            self.ping_timer = None

    def _clear_reconnect_timer(self) -> None:
        """Clear reconnect timer."""
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            self.reconnect_timer = None

    def _clear_server_ping_timer(self) -> None:
        """Clear server ping timer."""
        if self.server_ping_timer:
            self.server_ping_timer.cancel()
            self.server_ping_timer = None

    def _start_ping(self) -> None:
        """Start ping timer (every 15 seconds)."""
        self._clear_ping_timer()

        def ping_function():
            if not self._stop_event.is_set() and self._is_websocket_open():
                self._log("-")
                self.conn.send("-")
                # Schedule next ping
                self._start_ping()
            else:
                self._log("Clearing ping timer")

        self.ping_timer = threading.Timer(self.config.ping_interval, ping_function)
        self.ping_timer.start()

    def _start_ping_to_server(self) -> None:
        """Start ping to server (when server is down)."""
        self._clear_server_ping_timer()

        def server_ping_function():
            if not self._stop_event.is_set() and self._is_websocket_open():
                self._log("Ping server to reconnect")
                self.conn.send(json.dumps(self.server_ping_payload.to_dict()))
                # Schedule next server ping
                self._start_ping_to_server()
            else:
                self._log("Clearing ping server timer")

        self.server_ping_timer = threading.Timer(self.config.server_ping_interval,
                        server_ping_function)
        self.server_ping_timer.start()

    def _start_close_and_reconnect(self) -> None:
        """Start close and reconnect timer (every 27 minutes)."""
        self._clear_reconnect_timer()

        def reconnect_function():
            if not self._stop_event.is_set() and self._is_websocket_open():
                self._clear_all_timers()

                self._log("Closing current connection and making new connection using sid and uid")
                self.manual_closure = True
                self.conn.close()
                if self.on_close:
                    self.on_close({'code': 1000,
                        'message': 'Closing this connection and opening new connection!'})

                # Wait a bit then reconnec
                def delayed_reconnect():
                    if not self._stop_event.is_set():
                        self.reconnect = True
                        self._make_new_connection()

                reconnect_timer = threading.Timer(0.05, delayed_reconnect)  # 50ms delay
                reconnect_timer.start()

        self.reconnect_timer = threading.Timer(self.config.reconnect_timeout, reconnect_function)
        self.reconnect_timer.start()

    # Public API methods

    def subscribe(self, subscribe_type: str = "0") -> None:
        """
        Subscribe to a channel with specified type.

        Args:
            subscribe_type: Type of subscription
                          "0" - live events
                          "-1" - earliest available events
                          "-2" - resume from previous left off
                          specific streaming id - resume from that ID

        Raises:
            ValueError: If subscribe_type is None
            ConnectionError: If WebSocket is not connected
        """
        if subscribe_type is None:
            raise ValueError("Subscribe type is required")

        self.subscribe_payload.streaming_id = subscribe_type

        if self._is_websocket_open():
            payload = json.dumps(self.subscribe_payload.to_dict())
            self._log(f"Subscribing with payload: {payload}")
            self.conn.send(payload)
        else:
            raise ConnectionError("WebSocket connection is not open")

    def unsubscribe(self) -> None:
        """
        Unsubscribe from channel.

        Raises:
            ConnectionError: If WebSocket is not connected
        """
        if self._is_websocket_open():
            self.conn.send(json.dumps(self.unsubscribe_payload.to_dict()))
            self._log("Unsubscribed from channel")
        else:
            raise ConnectionError("WebSocket connection is not open")

    def send_ack(self) -> None:
        """
        Send acknowledgement to receive next stream data if available.

        Raises:
            ConnectionError: If WebSocket is not connected or no streaming ID available
        """
        self.ack_trigger_received = True

        if (self._is_websocket_open() and
            self.ack_payload.streaming_id != ""):
            self.conn.send(json.dumps(self.ack_payload.to_dict()))
            self.ack_sent = True
            self.ack_trigger_received = False
            self._log(f"Sent ack for streaming ID: {self.ack_payload.streaming_id}")
        else:
            self._log("Cannot send ack: connection not open or no streaming ID")

    def close(self) -> None:
        """Close the WebSocket connection."""
        self._stop_event.set()  # Signal all timers to stop

        if self._is_websocket_open():
            self.manual_closure = True
            self.conn.close()
            self._log("WebSocket connection closed manually")
            if self.on_close:
                self.on_close({'code': 1001, 'message': 'Connection closed!'})

        # Clean up timers
        self._clear_all_timers()

    def is_connected(self) -> bool:
        """
        Check if the connection is open.

        Returns:
            True if connected, False otherwise
        """
        return self._is_websocket_open() and self.is_open

    def get_connection_state(self) -> ConnectionState:
        """
        Get current connection state.

        Returns:
            Current connection state
        """
        if not self.conn:
            return ConnectionState.DISCONNECTED

        if not hasattr(self.conn, 'sock') or not self.conn.sock:
            return ConnectionState.DISCONNECTED

        if self.conn.sock.connected:
            return ConnectionState.CONNECTED
        return ConnectionState.CLOSED

    def get_session_info(self) -> Dict[str, str]:
        """
        Get session information.

        Returns:
            Dictionary containing session ID and user ID
        """
        return {
            "sid": self.session_info.sid,
            "uid": self.session_info.uid
        }

    # Event handler registration methods

    def set_on_open(self, callback: Callable[[CustomEvent], None]) -> None:
        """Set callback for connection open events."""
        self.on_open = callback

    def set_on_message(self, callback: Callable[[DataStreamMessageEvent], None]) -> None:
        """Set callback for message events."""
        self.on_message = callback

    def set_on_error(self, callback: Callable[[CustomEvent], None]) -> None:
        """Set callback for error events."""
        self.on_error = callback

    def set_on_close(self, callback: Callable[[Any], None]) -> None:
        """Set callback for connection close events."""
        self.on_close = callback

    def set_on_pong(self, callback: Callable[[CustomEvent], None]) -> None:
        """Set callback for pong events."""
        self.on_pong = callback
