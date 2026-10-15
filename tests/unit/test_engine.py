"""Tests for FIXEngine."""

import asyncio

import pytest

from fixwire.core.session import FIXSession, SessionConfig, SessionStatus
from fixwire.core.tags import MsgType
from fixwire.engine import FIXEngine
from fixwire.transport import InMemoryTransport


@pytest.fixture
def session() -> FIXSession:
    """Create a test session (CLIENT sending to SERVER)."""
    config = SessionConfig(sender_comp_id="CLIENT", target_comp_id="SERVER")
    return FIXSession(config)


@pytest.fixture
def transport() -> InMemoryTransport:
    """Create a recording in-memory transport."""
    return InMemoryTransport()


@pytest.fixture
def engine(session: FIXSession, transport: InMemoryTransport) -> FIXEngine:
    """Create an engine over the in-memory transport."""
    return FIXEngine(session, transport)


class TestFIXEngineCreation:
    """Test engine construction and wiring."""

    def test_create_engine(self, engine, session, transport):
        """Test creating an engine with a session and transport."""
        # Assert
        assert engine.session is session
        assert engine.transport is transport

    @pytest.mark.asyncio
    async def test_constructor_spawns_no_tasks(self, session, transport):
        """Test that construction creates no asyncio tasks."""
        # Arrange
        tasks_before = asyncio.all_tasks()

        # Act
        FIXEngine(session, transport)

        # Assert
        assert asyncio.all_tasks() == tasks_before

    def test_status_delegates_to_session(self, engine, session):
        """Test that engine.status mirrors session.status."""
        # Assert
        assert engine.status == SessionStatus.DISCONNECTED

        # Act
        session.status = SessionStatus.LOGGED_ON

        # Assert
        assert engine.status == SessionStatus.LOGGED_ON

    def test_is_connected_delegates_to_session(self, engine, session):
        """Test that engine.is_connected mirrors session.is_connected."""
        # Assert
        assert engine.is_connected is False

        # Act
        session.status = SessionStatus.LOGGED_ON

        # Assert
        assert engine.is_connected is True


class TestFIXEngineDisconnect:
    """Test engine teardown."""

    @pytest.mark.asyncio
    async def test_disconnect_closes_transport(self, engine, transport):
        """Test that disconnect() closes the transport."""
        # Act
        await engine.disconnect()

        # Assert
        assert transport.close_count == 1
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self, engine, transport):
        """Test that repeated disconnect() calls tear down only once."""
        # Act
        await engine.disconnect()
        await engine.disconnect()

        # Assert
        assert transport.close_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_parks_session_disconnected(self, engine, session):
        """Test that disconnect() parks the session in DISCONNECTED."""
        # Act
        await engine.disconnect()

        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert engine.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_recovers_from_error(self, engine, session):
        """Test that disconnect() moves an ERROR session to DISCONNECTED."""
        # Arrange
        session.status = SessionStatus.ERROR

        # Act
        await engine.disconnect()

        # Assert
        assert session.status == SessionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_sends_logout_when_logged_on(
        self, engine, session, transport
    ):
        """Test that disconnect() drives the session logout handshake."""
        # Arrange
        session.config.logout_timeout = 0
        session.status = SessionStatus.LOGGED_ON

        # Act
        await engine.disconnect()

        # Assert: logout queued on the session, session parked, transport closed
        logout = session._send_queue.get_nowait()
        assert logout[35] == MsgType.LOGOUT
        assert session.status == SessionStatus.DISCONNECTED
        assert transport.close_count == 1


class TestFIXEngineReconnect:
    """Test the reconnect stub (wired in M3)."""

    @pytest.mark.asyncio
    async def test_reconnect_not_implemented(self, engine):
        """Test that reconnect() raises until M3."""
        # Act & Assert
        with pytest.raises(NotImplementedError):
            await engine.reconnect()


class TestFIXEngineConnect:
    """Test the connect stub (wired in the lifecycle slice)."""

    @pytest.mark.asyncio
    async def test_connect_not_implemented(self, engine):
        """Test that connect() raises until the lifecycle slice wires it."""
        # Act & Assert
        with pytest.raises(NotImplementedError):
            await engine.connect()
