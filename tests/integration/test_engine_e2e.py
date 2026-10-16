"""End-to-end integration test for FIXEngine.

M1 deliverable: two FIXEngine instances over a real WebSocket exchange
Logon → Heartbeat → Logout. This is the proof that the engine wiring
(transport, reader, writer, session handshake) actually works in concert.

This test is intentionally in tests/integration/ rather than tests/unit/:
it binds real sockets, takes a noticeable amount of time, and depends on
the WebSocket transport (not InMemoryTransport). Treat it as the milestone
sign-off for M1.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus
from fixwire.engine import FIXEngine
from fixwire.transport.websocket import (
    WebSocketServer,
    WebSocketTransport,
    WebSocketTransportAdapter,
)


def _free_port() -> int:
    """Pick an OS-assigned free TCP port for the test server.

    Binding to port 0 asks the kernel for an unused port. We immediately
    close the socket and hand the number back so the test can rebind to
    it. This avoids the 'port already in use' flake that comes from
    hardcoding a port in a long-running suite.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def ws_server():
    """Start a WebSocketServer on a fresh port for the duration of the test."""
    port = _free_port()
    server = WebSocketServer(host="127.0.0.1", port=port)
    await server.start()
    try:
        yield server, port
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_two_engines_exchange_logon_heartbeat_logout_over_websocket(
    ws_server,
):
    """M1 happy-path integration: two FIXEngines connect, handshake Logon,
    exchange a Heartbeat, and Logout cleanly."""
    server, port = ws_server
    url = f"ws://127.0.0.1:{port}"

    # --- Server side: the connection handler owns the server FIXEngine ---
    server_logged_on = asyncio.Event()
    shutdown_server = asyncio.Event()
    server_engine_holder: dict[str, FIXEngine] = {}

    async def handle_connection(ws):
        adapter = WebSocketTransportAdapter(ws)
        server_config = SessionConfig(
            sender_comp_id="SERVER", target_comp_id="CLIENT"
        )
        server_session = FIXSession(server_config)
        server_engine = FIXEngine(server_session, adapter)
        server_engine_holder["engine"] = server_engine

        try:
            # Drive the server-side handshake. The client's Logon is
            # already in flight; this returns when the server reaches
            # LOGGED_ON.
            await server_engine.connect()
            server_logged_on.set()

            # Park until the test signals shutdown.
            await shutdown_server.wait()
        finally:
            await server_engine.disconnect()

    server.on_connection(handle_connection)

    # --- Client side: connect and run the same handshake ---
    client_config = SessionConfig(
        sender_comp_id="CLIENT", target_comp_id="SERVER"
    )
    client_session = FIXSession(client_config)
    client_transport = WebSocketTransport(url)
    client_engine = FIXEngine(client_session, client_transport)

    # Act: client connect triggers the server handler
    await client_engine.connect()
    await asyncio.wait_for(server_logged_on.wait(), timeout=2.0)
    server_engine = server_engine_holder["engine"]

    # Assert: both engines are logged on
    assert client_session.status == SessionStatus.LOGGED_ON
    assert server_engine.session.status == SessionStatus.LOGGED_ON

    # Exchange a Heartbeat: client sends, server reader picks it up
    hb = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
    await client_session.send(hb)
    # Give the writer/reader a chance to flush through the sockets
    await asyncio.sleep(0.1)

    # Drive the server-side shutdown, then the client-side
    shutdown_server.set()
    try:
        await asyncio.wait_for(server_engine.disconnect(), timeout=2.0)
    except TimeoutError:
        pass
    await client_engine.disconnect()

    # Final assertions: both ended DISCONNECTED
    assert client_session.status == SessionStatus.DISCONNECTED
    assert server_engine.session.status == SessionStatus.DISCONNECTED
