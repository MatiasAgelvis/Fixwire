"""WebSocket frame-size and keepalive settings.

These tests never bind a socket: they assert the adapter forwards its
settings to ``websockets``, which is where the behaviour actually lives.
"""

import pytest

from fixwire.core.parser import ParserConfig
from fixwire.transport import websocket as ws_module
from fixwire.transport.websocket import WebSocketServer, WebSocketTransport


class _FakeServer:
    """Stand-in for the object ``serve()`` returns."""

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class TestWebSocketTransportSettings:
    """Client transport forwards frame and keepalive settings."""

    def test_defaults_leave_keepalive_to_the_fix_layer(self):
        """No WebSocket pings by default; FIX heartbeats are the keepalive."""
        # Arrange & Act
        transport = WebSocketTransport("ws://localhost:1")

        # Assert
        assert transport.ping_interval is None
        assert transport.ping_timeout is None

    def test_default_frame_limit_matches_parser_limit(self):
        """The transport must not reject a frame the parser would accept."""
        # Arrange & Act
        transport = WebSocketTransport("ws://localhost:1")
        parser_limit = ParserConfig().max_message_size

        # Assert
        assert transport.max_size >= parser_limit

    @pytest.mark.asyncio
    async def test_connect_passes_settings_through(self, monkeypatch):
        """connect() forwards every setting to websockets.connect."""
        # Arrange
        captured: dict[str, object] = {}

        async def fake_connect(url: str, **kwargs: object) -> object:
            captured["url"] = url
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(ws_module, "connect", fake_connect)
        transport = WebSocketTransport(
            "ws://localhost:1",
            max_size=2048,
            ping_interval=5.0,
            ping_timeout=2.0,
        )

        # Act
        await transport.connect()

        # Assert
        assert captured == {
            "url": "ws://localhost:1",
            "max_size": 2048,
            "ping_interval": 5.0,
            "ping_timeout": 2.0,
        }


class TestWebSocketServerSettings:
    """Server forwards frame and keepalive settings."""

    @pytest.mark.asyncio
    async def test_start_passes_settings_through(self, monkeypatch):
        """start() forwards every setting to websockets.serve."""
        # Arrange
        captured: dict[str, object] = {}

        async def fake_serve(handler, host, port, **kwargs):
            captured.update({"host": host, "port": port, **kwargs})
            return _FakeServer()

        monkeypatch.setattr(ws_module, "serve", fake_serve)
        server = WebSocketServer("127.0.0.1", 9001, max_size=4096, ping_interval=10.0)

        # Act
        await server.start()

        # Assert
        assert captured == {
            "host": "127.0.0.1",
            "port": 9001,
            "max_size": 4096,
            "ping_interval": 10.0,
            "ping_timeout": None,
        }
