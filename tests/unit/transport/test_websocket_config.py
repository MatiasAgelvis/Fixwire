"""WebSocket frame-size and keepalive settings.

These tests never bind a socket: they assert the adapter forwards its
settings to ``websockets``, which is where the behaviour actually lives.
"""

import ssl

import pytest

from fixwire.core.parser import ParserConfig
from fixwire.transport import websocket as ws_module
from fixwire.transport.tls import TLSConfig, TLSError
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


class TestWebSocketTLSWiring:
    """TLS is optional, explicit, and fails early when misconfigured."""

    @pytest.mark.asyncio
    async def test_connect_passes_the_tls_context(self, monkeypatch):
        """A configured context reaches websockets.connect as ``ssl``."""
        # Arrange
        captured: dict[str, object] = {}

        async def fake_connect(url: str, **kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(ws_module, "connect", fake_connect)
        transport = WebSocketTransport(
            "wss://localhost:1", tls=TLSConfig(verify=False)
        )

        # Act
        await transport.connect()

        # Assert
        assert isinstance(captured["ssl"], ssl.SSLContext)
        assert captured["ssl"].verify_mode == ssl.CERT_NONE

    def test_a_bad_tls_config_fails_at_construction(self, tmp_path):
        """Misconfiguration must not wait for the first handshake."""
        # Act & Assert
        with pytest.raises(TLSError, match="ca_file"):
            WebSocketTransport(
                "wss://localhost:1", tls=TLSConfig(ca_file=tmp_path / "no.pem")
            )

    def test_no_tls_config_leaves_websockets_defaults(self):
        """Without TLS settings the transport must not override verification."""
        # Act
        transport = WebSocketTransport("wss://localhost:1")

        # Assert
        assert transport.tls is None


class TestTransportSecurityReporting:
    """Transports report their security posture; they are never asked."""

    def test_plain_websocket_is_plaintext(self):
        """No TLS config means no claim of encryption."""
        from fixwire.transport import TransportSecurity

        assert (
            WebSocketTransport("ws://localhost:1").security
            == TransportSecurity.PLAINTEXT
        )

    def test_configured_websocket_is_tls(self):
        """A built context means the connection will be encrypted."""
        from fixwire.transport import TransportSecurity

        transport = WebSocketTransport(
            "wss://localhost:1", tls=TLSConfig(verify=False)
        )
        assert transport.security == TransportSecurity.TLS

    def test_adapter_reports_what_actually_happened(self):
        """The server adapter derives posture from the live connection."""
        from fixwire.transport import TransportSecurity
        from fixwire.transport.websocket import WebSocketTransportAdapter

        class _Underlying:
            def __init__(self, ssl_object) -> None:
                self._ssl_object = ssl_object

            def get_extra_info(self, name: str):
                return self._ssl_object if name == "ssl_object" else None

        class _Connection:
            def __init__(self, ssl_object) -> None:
                self.transport = _Underlying(ssl_object)

        encrypted = WebSocketTransportAdapter(_Connection(object()))
        plain = WebSocketTransportAdapter(_Connection(None))

        assert encrypted.security == TransportSecurity.TLS
        assert plain.security == TransportSecurity.PLAINTEXT

    def test_tls_with_a_plain_url_is_rejected(self):
        """TLS settings on a ws:// URL are a configuration error."""
        with pytest.raises(TLSError, match="wss"):
            WebSocketTransport("ws://localhost:1", tls=TLSConfig(verify=False))


class TestUrlRedactionInLogs:
    """Connection URLs are logged, so credentials in them are not."""

    @pytest.mark.asyncio
    async def test_connected_log_hides_credentials(self, monkeypatch):
        """A password in the URL must not appear in the log event."""
        # Arrange
        from structlog.testing import capture_logs

        async def fake_connect(url: str, **kwargs: object) -> object:
            return object()

        monkeypatch.setattr(ws_module, "connect", fake_connect)
        transport = WebSocketTransport("ws://user:secret@localhost:1")

        # Act
        with capture_logs() as logs:
            await transport.connect()

        # Assert: the log is still useful, but not the credential
        assert any(e["event"] == "transport.ws.connected" for e in logs)
        assert "secret" not in str(logs)
        assert "localhost" in str(logs)
