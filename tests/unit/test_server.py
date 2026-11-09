"""Tests for FIXServer — the overseer for concurrent client sessions.

FIXServer is transport-agnostic: it adopts an already-connected Transport
and owns the FIXEngine lifecycle for it. The WebSocket layer is a thin
adapter on top, so these tests use InMemoryTransport and need no sockets.
"""

import asyncio

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.session import SessionConfig, SessionStatus
from fixwire.server import FIXServer
from fixwire.transport import InMemoryTransport


def _config_factory() -> SessionConfig:
    """Server-side config with short timeouts for fast tests."""
    return SessionConfig(
        sender_comp_id="SERVER",
        target_comp_id="CLIENT",
        logon_timeout=1.0,
        logout_timeout=0.05,
    )


def _peer_logon(seq: int = 1) -> bytes:
    return FIXMessageFactory.create_logon("CLIENT", "SERVER", seq=seq).serialize()


def _peer_logout(seq: int = 2) -> bytes:
    return FIXMessageFactory.create_logout("CLIENT", "SERVER", seq=seq).serialize()


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    """Wait until ``predicate()`` is truthy, or raise TimeoutError."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.01)


@pytest.fixture
def server() -> FIXServer:
    return FIXServer(_config_factory, max_sessions=10)


@pytest.fixture
def transport() -> InMemoryTransport:
    return InMemoryTransport()


class TestFIXServerAccept:
    """Adopting connections and tracking their engines."""

    @pytest.mark.asyncio
    async def test_serve_connection_registers_engine(self, server, transport):
        """An accepted connection produces one registered, logged-on engine."""
        # Arrange: the peer's Logon is already in flight
        transport.feed(_peer_logon())

        # Act
        task = asyncio.create_task(server.serve_connection(transport))
        await _wait_until(lambda: server.session_count == 1)
        await _wait_until(
            lambda: server.sessions()[0].session.status == SessionStatus.LOGGED_ON
        )

        # Assert
        assert server.session_count == 1
        assert server.sessions()[0].session.config.sender_comp_id == "SERVER"

        # Cleanup
        await server.stop()
        await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_two_connections_get_independent_engines(self, server):
        """Each connection gets its own session and engine."""
        # Arrange
        t1 = InMemoryTransport()
        t2 = InMemoryTransport()
        t1.feed(_peer_logon())
        t2.feed(_peer_logon())

        # Act
        task1 = asyncio.create_task(server.serve_connection(t1))
        task2 = asyncio.create_task(server.serve_connection(t2))
        await _wait_until(lambda: server.session_count == 2)

        # Assert
        first, second = server.sessions()
        assert first is not second
        assert first.session is not second.session

        # Cleanup
        await server.stop()
        await asyncio.wait_for(
            asyncio.gather(task1, task2, return_exceptions=True), timeout=2.0
        )

    @pytest.mark.asyncio
    async def test_session_end_deregisters_engine(
        self, server, transport, monkeypatch
    ):
        """When the session ends, the engine is torn down and deregistered."""
        # Arrange: fast heartbeat tick so peer logout is noticed promptly
        monkeypatch.setattr("fixwire.engine._HEARTBEAT_POLL", 0.01)
        transport.feed(_peer_logon())
        task = asyncio.create_task(server.serve_connection(transport))
        await _wait_until(lambda: server.session_count == 1)
        await _wait_until(
            lambda: server.sessions()[0].session.status == SessionStatus.LOGGED_ON
        )

        # Act: the peer logs out
        transport.feed(_peer_logout())
        await asyncio.wait_for(task, timeout=2.0)

        # Assert: deregistered and the transport was closed
        assert server.sessions() == []
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_max_sessions_closes_extra_connection(self):
        """Beyond the cap, a new connection is closed and not registered."""
        # Arrange
        server = FIXServer(_config_factory, max_sessions=1)
        t1 = InMemoryTransport()
        t1.feed(_peer_logon())
        task1 = asyncio.create_task(server.serve_connection(t1))
        await _wait_until(lambda: server.session_count == 1)

        # Act
        t2 = InMemoryTransport()
        await asyncio.wait_for(server.serve_connection(t2), timeout=1.0)

        # Assert
        assert t2.is_connected is False
        assert server.session_count == 1

        # Cleanup
        await server.stop()
        await asyncio.wait_for(task1, timeout=2.0)

    @pytest.mark.asyncio
    async def test_stop_disconnects_all_sessions(self, server):
        """stop() tears down every active session."""
        # Arrange
        t1 = InMemoryTransport()
        t2 = InMemoryTransport()
        t1.feed(_peer_logon())
        t2.feed(_peer_logon())
        task1 = asyncio.create_task(server.serve_connection(t1))
        task2 = asyncio.create_task(server.serve_connection(t2))
        await _wait_until(lambda: server.session_count == 2)

        # Act
        await server.stop()
        await asyncio.wait_for(
            asyncio.gather(task1, task2, return_exceptions=True), timeout=2.0
        )

        # Assert
        assert server.sessions() == []
        assert t1.is_connected is False
        assert t2.is_connected is False
