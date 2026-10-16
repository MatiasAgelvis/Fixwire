"""WebSocket Transport - FIX messages over WebSocket.

Provides WebSocket client and server implementations for FIX protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
import websockets
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import ServerConnection, serve

if TYPE_CHECKING:
    from fixwire.transport import Transport

logger = structlog.get_logger()


def _validate_binary_frame(data: str | bytes) -> bytes:
    """Validate that received data is binary (not text).

    Args:
        data: Received data from WebSocket.

    Returns:
        Binary data.

    Raises:
        ConnectionError: If data is text instead of binary.
    """
    if isinstance(data, str):
        raise ConnectionError("Received text frame, expected binary FIX message")
    return data


class WebSocketTransport:
    """WebSocket client transport.

    Connects to a WebSocket server and sends/receives FIX messages.

    Usage:
        transport = WebSocketTransport("ws://localhost:8001")
        await transport.connect()
        await transport.send(raw_bytes)
        data = await transport.receive()
        await transport.close()
    """

    # Class-level annotations let tests bypass __init__ via __new__
    # and still set attributes in a type-safe way.
    _ws: ClientConnection | None
    _connected: bool

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        """Initialize WebSocket client transport.

        Args:
            url: WebSocket server URL (ws:// or wss://).
            timeout: Connection timeout in seconds.
        """
        self.url = url
        self.timeout = timeout
        self._ws = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected and self._ws is not None

    @property
    def _connection(self) -> ClientConnection:
        """Get the WebSocket connection, raising if not connected.

        Returns the active ClientConnection narrowed away from None,
        so callers can use it without further None checks.
        """
        if self._ws is None:
            raise ConnectionError("Transport not connected")
        return self._ws

    async def connect(self) -> None:
        """Connect to WebSocket server.

        Raises:
            ConnectionError: If connection fails.
            TimeoutError: If connection times out.
        """
        try:
            self._ws = await asyncio.wait_for(
                connect(self.url),
                timeout=self.timeout
            )
            self._connected = True
            logger.info("transport.ws.connected", url=self.url)
        except TimeoutError:
            raise TimeoutError(f"Connection timed out: {self.url}") from None
        except Exception as e:
            raise ConnectionError(f"Failed to connect: {e}") from e

    async def send(self, data: bytes) -> None:
        """Send raw bytes to the remote endpoint.

        Args:
            data: Raw FIX message bytes.

        Raises:
            ConnectionError: If not connected.
        """
        try:
            await self._connection.send(data)
            logger.debug("transport.ws.sent", size=len(data))
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to send: {e}") from e

    async def receive(self) -> bytes:
        """Receive raw bytes from the remote endpoint.

        Returns:
            Raw FIX message bytes.

        Raises:
            ConnectionError: If not connected or received non-bytes.
        """
        try:
            data = await self._connection.recv()
            data = _validate_binary_frame(data)
            logger.debug("transport.ws.received", size=len(data))
            return data
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to receive: {e}") from e

    async def close(self) -> None:
        """Close the WebSocket connection (idempotent)."""
        try:
            await self._connection.close()
        except ConnectionError:
            # Already disconnected — close is idempotent.
            pass
        except Exception as e:
            logger.warning("transport.ws.close_error", error=str(e))
        finally:
            self._connected = False
            self._ws = None
            logger.info("transport.ws.closed", url=self.url)


# Type-level proof that WebSocketTransport satisfies the Transport Protocol.
if TYPE_CHECKING:
    _transport_conformance: Transport = WebSocketTransport("ws://localhost:1")


class WebSocketServer:
    """WebSocket server for accepting FIX connections.

    Accepts WebSocket connections and dispatches to handler.

    Usage:
        server = WebSocketServer("0.0.0.0", 8001)
        server.on_connection(handle_connection)
        await server.start()
        # ...
        await server.stop()
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        """Initialize WebSocket server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
        """
        self.host = host
        self.port = port
        self._server = None
        self._connections: dict[str, ServerConnection] = {}
        self._connection_handler: Callable | None = None

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._server is not None

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    def on_connection(self, handler: Callable) -> None:
        """Register connection handler.

        Args:
            handler: Async function called for each connection.
        """
        self._connection_handler = handler

    async def _handle_connection(self, ws: ServerConnection) -> None:
        """Handle a new WebSocket connection."""
        connection_id = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
        self._connections[connection_id] = ws

        logger.info("transport.ws.client_connected",
                    connection_id=connection_id,
                    total=self.connection_count)

        try:
            # All messages are processed by the connection handler
            if self._connection_handler:
                await self._connection_handler(ws)
            else:
                # If no handler, just keep connection alive
                # Log messages as they are received
                async for message in ws:
                    logger.debug("transport.ws.message_received",
                                connection_id=connection_id,
                                size=len(message))
        except websockets.ConnectionClosed:
            pass
        finally:
            del self._connections[connection_id]
            logger.info("transport.ws.client_disconnected",
                       connection_id=connection_id,
                       total=self.connection_count)

    async def start(self) -> None:
        """Start the WebSocket server.

        Raises:
            RuntimeError: If server is already running.
        """
        if self.is_running:
            raise RuntimeError("Server already running")

        self._server = await serve(
            self._handle_connection,
            self.host,
            self.port
        )
        logger.info("transport.ws.server_started",
                    host=self.host,
                    port=self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("transport.ws.server_stopped")


class WebSocketTransportAdapter:
    """Adapter that wraps a WebSocket server connection as a Transport.

    Used by the server-side session to send/receive through the WebSocket.

    Usage:
        # In server handler
        async def handle_connection(ws):
            transport = WebSocketTransportAdapter(ws)
            session = FIXSession(config, transport=transport)
            # ... use session
    """

    _ws: ServerConnection | None
    _connected: bool

    def __init__(self, ws: ServerConnection) -> None:
        """Initialize adapter with WebSocket connection.

        Args:
            ws: WebSocket server connection.
        """
        self._ws = ws
        self._connected = True

    async def connect(self) -> None:
        """No-op: the adapter wraps an already-accepted server connection.

        The WebSocketServer hands us an open ``ServerConnection`` on each
        accepted client, so there's nothing to dial. The method exists to
        satisfy the ``Transport`` protocol and to give the engine a single
        uniform entry point.
        """
        pass

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected

    @property
    def _connection(self) -> ServerConnection:
        """Get the WebSocket connection, raising if not connected.

        Returns the active ServerConnection narrowed away from None,
        so callers can use it without further None checks.
        """
        if not self._connected or self._ws is None:
            raise ConnectionError("Transport not connected")
        return self._ws

    async def send(self, data: bytes) -> None:
        """Send raw bytes to the client.

        Args:
            data: Raw FIX message bytes.

        Raises:
            ConnectionError: If not connected or send fails.
        """
        try:
            await self._connection.send(data)
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to send: {e}") from e

    async def receive(self) -> bytes:
        """Receive raw bytes from the client.

        Returns:
            Raw FIX message bytes.

        Raises:
            ConnectionError: If not connected, receive fails, or frame is text.
        """
        try:
            data = await self._connection.recv()
            return _validate_binary_frame(data)
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to receive: {e}") from e

    async def close(self) -> None:
        """Close the connection (idempotent).

        Calling close() on an already-closed adapter is a no-op.
        """
        try:
            await self._connection.close()
        except ConnectionError:
            # Already disconnected — close is idempotent
            pass
        except Exception as e:
            logger.warning("transport.ws.close_error", error=str(e))
        finally:
            self._connected = False
