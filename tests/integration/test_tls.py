"""WSS and mTLS round-trips.

TLS is a connection concern, so it is proven at the connection: a real
WebSocket over a real socket, with certificates generated for the run. The
unit tests cover policy; these cover the handshake actually completing — and
the transports reporting it truthfully afterwards.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest

from fixwire.transport import TransportSecurity
from fixwire.transport.tls import TLSConfig
from fixwire.transport.websocket import (
    WebSocketServer,
    WebSocketTransport,
    WebSocketTransportAdapter,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@asynccontextmanager
async def _echo_server(server_tls: TLSConfig, port: int):
    """Run a WSS server that echoes binary frames, and record its posture."""
    server = WebSocketServer(host="127.0.0.1", port=port, tls=server_tls)
    observed: dict[str, TransportSecurity] = {}
    connected = asyncio.Event()

    async def handle(connection) -> None:
        adapter = WebSocketTransportAdapter(connection)
        observed["security"] = adapter.security
        connected.set()
        try:
            while True:
                data = await adapter.receive()
                await adapter.send(data)
        except Exception:
            return
        finally:
            await adapter.close()

    server.on_connection(handle)
    await server.start()
    try:
        yield observed, connected
    finally:
        await server.stop()


def _client_tls(certs, *, client_cert: bool) -> TLSConfig:
    return TLSConfig(
        ca_file=certs.ca,
        cert_file=certs.client_cert if client_cert else None,
        key_file=certs.client_key if client_cert else None,
    )


def _server_tls(certs, *, require_client_cert: bool) -> TLSConfig:
    return TLSConfig(
        server_side=True,
        ca_file=certs.ca if require_client_cert else None,
        cert_file=certs.server_cert,
        key_file=certs.server_key,
        require_client_cert=require_client_cert,
    )


class TestWSS:
    """Encryption in one direction of trust: server certificate only."""

    @pytest.mark.asyncio
    async def test_round_trip_over_tls(self, tls_certs):
        """Bytes survive the handshake, and both ends report TLS."""
        # Arrange
        port = _free_port()
        async with _echo_server(
            _server_tls(tls_certs, require_client_cert=False), port
        ) as (observed, connected):
            transport = WebSocketTransport(
                f"wss://localhost:{port}",
                tls=_client_tls(tls_certs, client_cert=False),
            )

            # Act
            await transport.connect()
            await transport.send(b"8=FIX.4.4\x01")
            echoed = await asyncio.wait_for(transport.receive(), timeout=5.0)
            await asyncio.wait_for(connected.wait(), timeout=5.0)

            # Assert
            assert echoed == b"8=FIX.4.4\x01"
            assert transport.security == TransportSecurity.TLS
            assert observed["security"] == TransportSecurity.TLS
            await transport.close()

    @pytest.mark.asyncio
    async def test_a_plain_client_is_refused_by_a_tls_listener(self, tls_certs):
        """The listener does not fall back to plaintext."""
        # Arrange
        port = _free_port()
        async with _echo_server(
            _server_tls(tls_certs, require_client_cert=False), port
        ):
            transport = WebSocketTransport(f"ws://127.0.0.1:{port}")

            # Act & Assert
            with pytest.raises(ConnectionError):
                await transport.connect()
                await asyncio.wait_for(transport.receive(), timeout=5.0)


class TestMutualTLS:
    """Both sides authenticate, which is what a venue-side FIX link needs."""

    @pytest.mark.asyncio
    async def test_round_trip_with_client_certificates(self, tls_certs):
        """A client that presents a certificate is accepted."""
        # Arrange
        port = _free_port()
        async with _echo_server(
            _server_tls(tls_certs, require_client_cert=True), port
        ) as (observed, connected):
            transport = WebSocketTransport(
                f"wss://localhost:{port}",
                tls=_client_tls(tls_certs, client_cert=True),
            )

            # Act
            await transport.connect()
            await transport.send(b"hello")
            echoed = await asyncio.wait_for(transport.receive(), timeout=5.0)
            await asyncio.wait_for(connected.wait(), timeout=5.0)

            # Assert
            assert echoed == b"hello"
            assert transport.security == TransportSecurity.TLS
            assert observed["security"] == TransportSecurity.TLS
            await transport.close()

    @pytest.mark.asyncio
    async def test_a_client_without_a_certificate_is_refused(self, tls_certs):
        """Presenting nothing is not the same as presenting a valid cert.

        TLS 1.3 may report the rejection during the first read rather than
        during connect, so both are accepted as the failure point.
        """
        # Arrange
        port = _free_port()
        async with _echo_server(
            _server_tls(tls_certs, require_client_cert=True), port
        ):
            transport = WebSocketTransport(
                f"wss://localhost:{port}",
                tls=_client_tls(tls_certs, client_cert=False),
            )

            # Act & Assert
            with pytest.raises(ConnectionError):
                await transport.connect()
                await asyncio.wait_for(transport.receive(), timeout=5.0)
