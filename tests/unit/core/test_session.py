"""Tests for FIXSession."""

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus


@pytest.fixture
def session() -> FIXSession:
    """Create a test session."""
    config = SessionConfig(sender_comp_id="C", target_comp_id="S")
    return FIXSession(config)


class TestFIXSessionCreation:
    """Test session creation and initialization."""

    def test_create_session(self, session):
        """Test creating a session with config."""
        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert session.is_connected is False
        assert session.get_next_send_seq_num() == 1
        assert session.get_next_expected_seq_num() == 1


class TestFIXSessionSequenceNumbers:
    """Test sequence number management."""

    @pytest.mark.asyncio
    async def test_next_seq_num_increments(self, session):
        """Test that sequence numbers increment via send()."""
        # Act: send two heartbeat messages
        msg1 = FIXMessageFactory.create_heartbeat("C", "S", 0)
        msg2 = FIXMessageFactory.create_heartbeat("C", "S", 0)
        await session.send(msg1)
        await session.send(msg2)

        # Assert: send() increments seq and puts in queue
        assert msg1.sequence == 1
        assert msg2.sequence == 2

    def test_reset_sequence_numbers(self, session):
        """Test sequence number reset."""
        # Arrange
        session._state.outgoing_seq_num = 100
        session._state.incoming_seq_num = 50

        # Act
        session.reset_sequence_numbers()

        # Assert
        assert session._state.outgoing_seq_num == 0
        assert session._state.incoming_seq_num == 0
        assert session.get_next_send_seq_num() == 1
        assert session.get_next_expected_seq_num() == 1

    def test_incoming_seq_num_tracking(self, session):
        """Test incoming sequence number tracking."""
        # Act
        session._state.incoming_seq_num = 5

        # Assert
        assert session.get_next_expected_seq_num() == 6


class TestFIXSessionStatus:
    """Test session status management."""

    def test_initial_status(self, session):
        """Test initial session status."""
        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert session.is_connected is False

    def test_status_transitions(self, session):
        """Test status changes."""
        # Act & Assert
        session.status = SessionStatus.CONNECTING
        assert session.status == SessionStatus.CONNECTING

        session.status = SessionStatus.LOGGED_ON
        assert session.status == SessionStatus.LOGGED_ON
        assert session.is_connected is True

        session.status = SessionStatus.DISCONNECTED
        assert session.status == SessionStatus.DISCONNECTED
        assert session.is_connected is False


class TestFIXSessionMessageHandling:
    """Test message handling."""

    @pytest.mark.asyncio
    async def test_receive_heartbeat_clears_test_request(self, session):
        """Test that receiving heartbeat response clears test request state."""
        # Arrange

        # Simulate pending test request
        session._state.test_request_id = "TEST-123"

        # Create heartbeat response using factory
        heartbeat = FIXMessageFactory.create_heartbeat(
            sender="S", target="C", seq=1, test_req_id="TEST-123"
        )
        raw = heartbeat.serialize()

        # Act - receive the heartbeat
        messages = await session.receive(raw)

        # Assert
        assert len(messages) == 1
        assert session._state.test_request_id is None
