"""Tests for FIXServer — the overseer for concurrent client sessions.

FIXServer is transport-agnostic: it adopts an already-connected Transport
and owns the FIXSessionRunner lifecycle for it. The WebSocket layer is a thin
adapter on top, so these tests use InMemoryTransport and need no sockets.
"""

import asyncio

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus
from fixwire.runner import FIXSessionRunner
from fixwire.server import FIXServer, ServerConfig
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


def _peer_logon_from(sender: str, seq: int = 1) -> bytes:
    """A Logon from a specific counterparty."""
    return FIXMessageFactory.create_logon(sender, "SERVER", seq=seq).serialize()


def _peer_logout(seq: int = 2) -> bytes:
    return FIXMessageFactory.create_logout("CLIENT", "SERVER", seq=seq).serialize()


def _logon_msg(sender: str):
    """A Logon message object from ``sender`` addressed to the server."""
    return FIXMessageFactory.create_logon(sender, "SERVER", seq=1)


def _bare_engine() -> FIXSessionRunner:
    """A runner with no I/O driven — enough to exercise the registry."""
    config = SessionConfig(sender_comp_id="SERVER", target_comp_id="CLIENT")
    return FIXSessionRunner(FIXSession(config), InMemoryTransport())


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    """Wait until ``predicate()`` is truthy, or raise TimeoutError."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.01)


@pytest.fixture
def server() -> FIXServer:
    return FIXServer(_config_factory, config=ServerConfig(max_sessions=10))


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
        t1.feed(_peer_logon_from("CLIENT_A"))
        t2.feed(_peer_logon_from("CLIENT_B"))

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
        monkeypatch.setattr("fixwire.runner._HEARTBEAT_POLL", 0.01)
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
        server = FIXServer(_config_factory, config=ServerConfig(max_sessions=1))
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
        t1.feed(_peer_logon_from("CLIENT_A"))
        t2.feed(_peer_logon_from("CLIENT_B"))
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


class TestFIXServerRegistry:
    """The identity registry stays consistent with the live engines."""

    def test_admit_registers_both_directions(self, server):
        """A successful admission is visible from identity and engine."""
        engine = _bare_engine()
        logon = _logon_msg("CLIENT_A")

        assert server._admit(logon, engine) is True

        assert server._sessions == {("CLIENT_A", "SERVER"): engine}
        assert server._identity == {engine: ("CLIENT_A", "SERVER")}

    def test_release_frees_only_the_engines_own_identity(self, server):
        """Releasing one engine leaves other sessions untouched."""
        first, second = _bare_engine(), _bare_engine()
        server._admit(_logon_msg("CLIENT_A"), first)
        server._admit(_logon_msg("CLIENT_B"), second)

        server._release(first)

        assert server._sessions == {("CLIENT_B", "SERVER"): second}
        assert server._identity == {second: ("CLIENT_B", "SERVER")}

    def test_release_of_unregistered_engine_is_a_noop(self, server):
        """A never-admitted engine cannot disturb the registry."""
        owner = _bare_engine()
        stranger = _bare_engine()
        server._admit(_logon_msg("CLIENT_A"), owner)

        server._release(stranger)

        assert server._sessions == {("CLIENT_A", "SERVER"): owner}
        assert server._identity == {owner: ("CLIENT_A", "SERVER")}

    def test_rejected_duplicate_is_not_registered(self, server):
        """A vetoed Logon must not overwrite the owner's identity."""
        owner, newcomer = _bare_engine(), _bare_engine()
        logon = _logon_msg("CLIENT_A")
        server._admit(logon, owner)

        assert server._admit(logon, newcomer) is False

        assert server._sessions == {("CLIENT_A", "SERVER"): owner}
        assert server._identity == {owner: ("CLIENT_A", "SERVER")}

    def test_release_after_rejection_keeps_owner_registered(self, server):
        """Tearing down a rejected newcomer must not free the live session."""
        owner, newcomer = _bare_engine(), _bare_engine()
        logon = _logon_msg("CLIENT_A")
        server._admit(logon, owner)
        server._admit(logon, newcomer)

        server._release(newcomer)

        assert server._sessions == {("CLIENT_A", "SERVER"): owner}


class TestFIXServerDuplicateLogon:
    """Only one live session per (SenderCompID, TargetCompID) identity."""

    @pytest.mark.asyncio
    async def test_duplicate_logon_is_rejected(self, server):
        """A second Logon for a live identity is refused and disconnected."""
        # Arrange: CLIENT_A is already logged on
        t1 = InMemoryTransport()
        t1.feed(_peer_logon_from("CLIENT_A"))
        task1 = asyncio.create_task(server.serve_connection(t1))
        await _wait_until(lambda: server.session_count == 1)
        await _wait_until(
            lambda: server.sessions()[0].session.status == SessionStatus.LOGGED_ON
        )

        # Act: a second connection claims the same identity
        t2 = InMemoryTransport()
        t2.feed(_peer_logon_from("CLIENT_A"))
        await asyncio.wait_for(server.serve_connection(t2), timeout=2.0)

        # Assert: the newcomer was closed; the original session survives
        assert t2.is_connected is False
        assert server.session_count == 1
        assert t1.is_connected is True

        # Cleanup
        await server.stop()
        await asyncio.wait_for(task1, timeout=2.0)

    @pytest.mark.asyncio
    async def test_distinct_identities_both_active(self, server):
        """Different counterparties coexist."""
        # Arrange
        t1 = InMemoryTransport()
        t2 = InMemoryTransport()
        t1.feed(_peer_logon_from("CLIENT_A"))
        t2.feed(_peer_logon_from("CLIENT_B"))

        # Act
        task1 = asyncio.create_task(server.serve_connection(t1))
        task2 = asyncio.create_task(server.serve_connection(t2))
        await _wait_until(lambda: server.session_count == 2)

        # Assert
        assert server.session_count == 2

        # Cleanup
        await server.stop()
        await asyncio.wait_for(
            asyncio.gather(task1, task2, return_exceptions=True), timeout=2.0
        )

    @pytest.mark.asyncio
    async def test_identity_released_on_session_end(self, server):
        """Once a session ends, its identity can log on again."""
        # Arrange: first session logs on, then ends
        t1 = InMemoryTransport()
        t1.feed(_peer_logon_from("CLIENT_A"))
        task1 = asyncio.create_task(server.serve_connection(t1))
        await _wait_until(lambda: server.session_count == 1)
        await _wait_until(
            lambda: server.sessions()[0].session.status == SessionStatus.LOGGED_ON
        )
        await server.stop()
        await asyncio.wait_for(task1, timeout=2.0)
        assert server.session_count == 0

        # Act: the same identity reconnects
        t2 = InMemoryTransport()
        t2.feed(_peer_logon_from("CLIENT_A"))
        task2 = asyncio.create_task(server.serve_connection(t2))
        await _wait_until(lambda: server.session_count == 1)
        await _wait_until(
            lambda: server.sessions()[0].session.status == SessionStatus.LOGGED_ON
        )

        # Assert
        assert server.session_count == 1

        # Cleanup
        await server.stop()
        await asyncio.wait_for(task2, timeout=2.0)


class TestFIXServerStop:
    """stop() tears sessions down concurrently and can be bounded.

    Sequential disconnects would make shutdown take ``logout_timeout`` per
    session, so a SIGTERM with 100 stuck sessions could take minutes.
    """

    @pytest.mark.asyncio
    async def test_stop_disconnects_sessions_concurrently(self, server):
        """Both sessions must be mid-disconnect at the same time."""
        # Arrange
        started = asyncio.Event()
        release = asyncio.Event()
        running = 0

        async def disconnect() -> None:
            nonlocal running
            running += 1
            if running == 2:
                started.set()
            await release.wait()

        class _Engine:
            async def disconnect(self) -> None:
                await disconnect()

        server._engines.update({_Engine(), _Engine()})

        # Act
        task = asyncio.create_task(server.stop())
        # Sequential teardown would never reach the second engine
        await asyncio.wait_for(started.wait(), timeout=1.0)
        release.set()
        await asyncio.wait_for(task, timeout=1.0)

        # Assert
        assert running == 2

    @pytest.mark.asyncio
    async def test_stop_timeout_bounds_a_stuck_session(self, server):
        """A wedged session cannot make shutdown unbounded."""
        # Arrange
        class _Stuck:
            async def disconnect(self) -> None:
                await asyncio.Event().wait()

        server._engines.add(_Stuck())
        loop = asyncio.get_running_loop()

        # Act
        began = loop.time()
        await server.stop(timeout=0.05)

        # Assert
        assert loop.time() - began < 1.0
