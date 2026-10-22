"""Tests for FIXSession."""

import asyncio
import inspect
from datetime import timedelta

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus
from fixwire.core.tags import MsgType
from fixwire.core.time import utc_now


@pytest.fixture
def session() -> FIXSession:
    """Create a test session (CLIENT sending to SERVER)."""
    config = SessionConfig(sender_comp_id="CLIENT", target_comp_id="SERVER")
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


class TestFIXSessionPurity:
    """FIXSession is a pure protocol layer: no transport, no asyncio tasks."""

    def test_constructor_rejects_transport_kwarg(self):
        """Test that FIXSession does not accept a Transport (engine owns I/O)."""
        # Arrange
        config = SessionConfig(sender_comp_id="CLIENT", target_comp_id="SERVER")

        # Act & Assert
        with pytest.raises(TypeError):
            FIXSession(config, transport=object())  # type: ignore[call-arg]

    def test_constructor_accepts_only_config(self):
        """Test that the constructor signature pins the session to protocol concerns."""
        # Assert
        params = inspect.signature(FIXSession.__init__).parameters
        assert set(params) == {"self", "config"}

    @pytest.mark.asyncio
    async def test_connect_spawns_no_background_tasks(self, session):
        """Test that connect() creates no asyncio tasks; tasks live in FIXEngine."""
        # Arrange
        tasks_before = asyncio.all_tasks()

        # Act
        await session.connect()

        # Assert
        assert asyncio.all_tasks() == tasks_before


class TestFIXSessionHeartbeatDecision:
    """Test check_heartbeat() — the protocol decision behind heartbeat monitoring."""

    @pytest.mark.asyncio
    async def test_noop_when_not_logged_on(self, session):
        """Test that check_heartbeat() does nothing unless logged on."""
        # Act
        await session.check_heartbeat()

        # Assert
        assert session._send_queue.empty()
        assert session._state.test_request_id is None

    @pytest.mark.asyncio
    async def test_noop_when_peer_active(self, session):
        """Test that a recently active peer triggers nothing."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_received_time = utc_now()

        # Act
        await session.check_heartbeat()

        # Assert
        assert session._send_queue.empty()
        assert session._state.test_request_id is None

    @pytest.mark.asyncio
    async def test_sends_test_request_when_peer_silent(self, session):
        """Test that a silent peer triggers a TestRequest."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.check_heartbeat()

        # Assert
        assert not session._send_queue.empty()
        msg = session._send_queue.get_nowait()
        assert msg[35] == MsgType.TEST_REQUEST
        assert session._state.test_request_id == msg[112]
        assert session._state.test_request_time is not None

    @pytest.mark.asyncio
    async def test_sets_error_when_test_request_unanswered(self, session):
        """Test that an unanswered TestRequest escalates to ERROR."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.test_request_id = "PREV-REQ"
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.check_heartbeat()

        # Assert
        assert session.status == SessionStatus.ERROR
        assert session._send_queue.empty()


class TestFIXSessionSequenceNumbers:
    """Test sequence number management."""

    @pytest.mark.asyncio
    async def test_next_seq_num_increments(self, session):
        """Test that sequence numbers increment via send()."""
        # Act: send two heartbeat messages
        msg1 = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        msg2 = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
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


class TestFIXSessionDisconnect:
    """disconnect() is a pure state transition — it must not wait.

    Owning time is the caller's job (see FIXEngine.disconnect). These tests
    pin that contract so the wait cannot silently creep back in.
    """

    @pytest.mark.asyncio
    async def test_disconnect_queues_logout_and_parks_waiting(self, session):
        """disconnect() queues a Logout and parks in WAITING_LOGOUT.

        Does not block on the peer's response — a caller driving the session
        directly owns the timeout.
        """
        # Arrange
        session.status = SessionStatus.LOGGED_ON

        # Act
        await session.disconnect()

        # Assert: Logout queued, session still waiting (not forced to end)
        logout = session._send_queue.get_nowait()
        assert logout[35] == MsgType.LOGOUT
        assert session.status == SessionStatus.WAITING_LOGOUT

    @pytest.mark.asyncio
    async def test_disconnect_from_not_logged_on_parks_disconnected(self, session):
        """disconnect() from a non-LOGGED_ON state parks at DISCONNECTED.

        No Logout is queued — there was no session to log out of.
        """
        # Act
        await session.disconnect()

        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert session._send_queue.empty()

    @pytest.mark.asyncio
    async def test_disconnect_creates_no_background_tasks(self, session):
        """disconnect() spawns no tasks — the session owns no concurrency."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        tasks_before = asyncio.all_tasks()

        # Act
        await session.disconnect()

        # Assert
        assert asyncio.all_tasks() == tasks_before


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
        session._state.test_request_id = "TEST-123"

        # Create heartbeat response using factory
        heartbeat = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=1, test_req_id="TEST-123"
        )
        raw = heartbeat.serialize()

        # Act - receive the heartbeat
        messages = await session.receive(raw)

        # Assert
        assert len(messages) == 1
        assert session._state.test_request_id is None

    @pytest.mark.asyncio
    async def test_test_request_sends_heartbeat_response(self, session):
        """Test that receiving TestRequest sends Heartbeat response."""
        # Arrange
        test_req_id = "REQ-001"
        test_request = FIXMessageFactory.create_test_request(
            sender="SERVER", target="CLIENT", seq=1, test_req_id=test_req_id
        )
        raw = test_request.serialize()

        # Act
        messages = await session.receive(raw)

        # Assert - heartbeat should be in send queue
        assert len(messages) == 1
        assert not session._send_queue.empty()

        # Verify the response is a heartbeat
        response = session._send_queue.get_nowait()
        assert response[35] == MsgType.HEARTBEAT, "Response should be a heartbeat"
        assert response[112] == test_req_id, "TestReqID should match"

    @pytest.mark.asyncio
    async def test_resend_request_sends_gap_fill(self, session):
        """Test that receiving ResendRequest sends SequenceReset-GapFill."""
        # Arrange
        begin_seq = 10
        end_seq = 20
        resend = FIXMessageFactory.create_resend_request(
            sender="SERVER", target="CLIENT", seq=1,
            begin_seq_no=begin_seq, end_seq_no=end_seq
        )
        raw = resend.serialize()

        # Act
        messages = await session.receive(raw)

        # Assert
        assert len(messages) == 1
        assert not session._send_queue.empty()

        # Verify the response is a SequenceReset with GapFill
        response = session._send_queue.get_nowait()
        assert response[35] == MsgType.SEQUENCE_RESET
        assert response[123] == "Y"  # GapFillFlag
        assert response[36] == str(end_seq + 1)  # NewSeqNo

    @pytest.mark.asyncio
    async def test_sequence_reset_updates_incoming_seq(self, session):
        """Test that receiving SequenceReset updates incoming sequence number."""
        # Arrange
        session._state.incoming_seq_num = 0
        new_seq_no = 51

        seq_reset = FIXMessageFactory.create_sequence_reset(
            sender="SERVER", target="CLIENT", seq=1,
            new_seq_no=new_seq_no, gap_fill=True
        )
        raw = seq_reset.serialize()

        # Act
        await session.receive(raw)

        # Assert
        assert session._state.incoming_seq_num == new_seq_no - 1
        assert session.get_next_expected_seq_num() == new_seq_no

    @pytest.mark.asyncio
    async def test_logon_response_transitions_status(self, session):
        """Test that receiving logon response transitions to LOGGED_ON."""
        # Arrange
        session.status = SessionStatus.WAITING_LOGON

        logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        raw = logon.serialize()

        # Act
        await session.receive(raw)

        # Assert
        assert session.status == SessionStatus.LOGGED_ON
        assert session.is_connected is True
        assert session._state.logon_time is not None

    @pytest.mark.asyncio
    async def test_logout_response_transitions_status(self, session):
        """Test that receiving logout response transitions to DISCONNECTED."""
        # Arrange
        session.status = SessionStatus.WAITING_LOGOUT

        logout = FIXMessageFactory.create_logout(
            sender="SERVER", target="CLIENT", seq=1
        )
        raw = logout.serialize()

        # Act
        await session.receive(raw)

        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert session.is_connected is False

    @pytest.mark.asyncio
    async def test_on_message_callback_invoked(self, session):
        """Test that registered callback is called on receive."""
        # Arrange
        received_messages = []

        async def callback(msg):
            received_messages.append(msg)

        session.on_message(callback)

        heartbeat = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=1
        )
        raw = heartbeat.serialize()

        # Act
        await session.receive(raw)

        # Assert
        assert len(received_messages) == 1
        assert received_messages[0][35] == MsgType.HEARTBEAT

    @pytest.mark.asyncio
    async def test_multiple_messages_processed(self, session):
        """Test that receive() handles multiple messages in one call."""
        # Arrange
        msg1 = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=1
        )
        msg2 = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=2
        )
        raw = msg1.serialize() + msg2.serialize()

        # Act
        messages = await session.receive(raw)

        # Assert
        assert len(messages) == 2
        assert messages[0][34] == "1"
        assert messages[1][34] == "2"
