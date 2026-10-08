"""Tests for WebSocket Transport."""

import asyncio

import pytest

from fixwire.transport.websocket import (
    WebSocketServer,
    WebSocketTransport,
    WebSocketTransportAdapter,
    _validate_binary_frame,
)


class TestValidateBinaryFrame:
    """Test binary frame validation."""

    def test_valid_binary_data(self):
        """Test that binary data passes validation."""
        # Arrange
        data = b"8=FIX.4.4\x0135=D\x01"

        # Act
        result = _validate_binary_frame(data)

        # Assert
        assert result == data

    def test_empty_binary_data(self):
        """Test that empty binary data passes validation."""
        # Arrange
        data = b""

        # Act
        result = _validate_binary_frame(data)

        # Assert
        assert result == data

    def test_text_data_raises(self):
        """Test that text data raises error."""
        # Arrange
        data = "invalid text"

        # Act & Assert
        with pytest.raises(ConnectionError, match="text frame"):
            _validate_binary_frame(data)

    def test_empty_text_raises(self):
        """Test that empty text data raises error."""
        # Arrange
        data = ""

        # Act & Assert
        with pytest.raises(ConnectionError, match="text frame"):
            _validate_binary_frame(data)


@pytest.fixture
async def ws_server():
    """Start a WebSocket server for testing."""
    server = WebSocketServer(host="127.0.0.1", port=8765)
    await server.start()
    yield server
    await server.stop()


class TestWebSocketTransport:
    """Test WebSocket client transport."""

    @pytest.mark.asyncio
    async def test_connect_to_server(self, ws_server):
        """Test connecting to a WebSocket server."""
        # Arrange
        transport = WebSocketTransport("ws://127.0.0.1:8765")

        # Act
        await transport.connect()

        # Assert
        assert transport.is_connected is True
        await transport.close()

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout."""
        # Arrange - Use non-routable IP
        transport = WebSocketTransport("ws://192.0.2.1:8765", timeout=0.5)

        # Act & Assert
        with pytest.raises((TimeoutError, ConnectionError)):
            await transport.connect()

    @pytest.mark.asyncio
    async def test_send_receive(self, ws_server):
        """Test sending and receiving data."""
        # Arrange
        received_data = []
        received_event = asyncio.Event()

        async def echo_handler(ws):
            async for message in ws:
                await ws.send(message)
                received_data.append(message)
                received_event.set()

        ws_server.on_connection(echo_handler)

        transport = WebSocketTransport("ws://127.0.0.1:8765")
        await transport.connect()

        # Act
        await transport.send(b"hello")
        await asyncio.wait_for(received_event.wait(), timeout=2.0)
        response = await asyncio.wait_for(transport.receive(), timeout=2.0)

        # Assert
        assert response == b"hello"
        assert received_data == [b"hello"]
        await transport.close()

    @pytest.mark.asyncio
    async def test_send_when_not_connected(self):
        """Test sending when not connected raises error."""
        # Arrange
        transport = WebSocketTransport("ws://127.0.0.1:8765")

        # Act & Assert
        with pytest.raises(ConnectionError, match="Transport not connected"):
            await transport.send(b"test")

    @pytest.mark.asyncio
    async def test_receive_when_not_connected(self):
        """Test receiving when not connected raises error."""
        # Arrange
        transport = WebSocketTransport("ws://127.0.0.1:8765")

        # Act & Assert
        with pytest.raises(ConnectionError, match="Transport not connected"):
            await transport.receive()

    @pytest.mark.asyncio
    async def test_close(self, ws_server):
        """Test closing connection."""
        # Arrange
        transport = WebSocketTransport("ws://127.0.0.1:8765")
        await transport.connect()

        # Act
        await transport.close()

        # Assert
        assert transport.is_connected is False


class TestWebSocketServer:
    """Test WebSocket server."""

    @pytest.mark.asyncio
    async def test_server_start_stop(self):
        """Test starting and stopping server."""
        # Arrange
        server = WebSocketServer(host="127.0.0.1", port=8766)

        # Act & Assert
        assert server.is_running is False
        await server.start()
        assert server.is_running is True
        await server.stop()
        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_server_start_twice_raises(self):
        """Test starting server twice raises error."""
        # Arrange
        server = WebSocketServer(host="127.0.0.1", port=8767)
        await server.start()

        # Act & Assert
        with pytest.raises(RuntimeError, match="Server already running"):
            await server.start()
        await server.stop()

    @pytest.mark.asyncio
    async def test_connection_count(self, ws_server):
        """Test connection count tracking."""
        # Arrange
        assert ws_server.connection_count == 0

        # Act
        transport = WebSocketTransport("ws://127.0.0.1:8765")
        await transport.connect()

        # Assert
        assert ws_server.connection_count == 1

        # Cleanup
        await transport.close()
        await asyncio.sleep(0.1)  # Give server time to clean up


class TestWebSocketTransportAdapter:
    """Test WebSocket server adapter."""

    @pytest.mark.asyncio
    async def test_adapter_send_receive(self, ws_server):
        """Test adapter can send and receive."""
        # Arrange
        adapter_received = []
        client_ready = asyncio.Event()
        adapter_ready = asyncio.Event()

        async def server_handler(ws):
            adapter = WebSocketTransportAdapter(ws)
            adapter_ready.set()
            # Wait for client to be ready
            await client_ready.wait()
            # Receive from client
            data = await adapter.receive()
            adapter_received.append(data)
            # Send back
            await adapter.send(b"response:" + data)

        ws_server.on_connection(server_handler)

        transport = WebSocketTransport("ws://127.0.0.1:8765")
        await transport.connect()

        # Act
        await adapter_ready.wait()
        client_ready.set()
        await transport.send(b"ping")
        response = await asyncio.wait_for(transport.receive(), timeout=2.0)

        # Assert
        assert response == b"response:ping"
        assert adapter_received == [b"ping"]
        await transport.close()

    @pytest.mark.asyncio
    async def test_adapter_not_connected(self):
        """Test adapter raises error when not connected."""
        # Arrange - Mock adapter with disconnected state
        adapter = WebSocketTransportAdapter.__new__(WebSocketTransportAdapter)
        adapter._connected = False
        adapter._ws = None

        # Act & Assert
        with pytest.raises(ConnectionError):
            await adapter.send(b"test")
