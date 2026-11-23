"""Tests for FIXSession."""

import asyncio
import inspect
from datetime import timedelta

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.message import FIXMessage
from fixwire.core.parser import ParserConfig
from fixwire.core.session import (
    FIXSession,
    SessionConfig,
    SessionNotLoggedOnError,
    SessionStatus,
)
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

    def test_parser_config_is_honoured(self):
        """The session builds its parser from the configured settings."""
        # Arrange
        config = SessionConfig(
            sender_comp_id="CLIENT",
            target_comp_id="SERVER",
            parser=ParserConfig(strict=False, max_message_size=2048),
        )

        # Act
        session = FIXSession(config)

        # Assert
        assert session.parser.strict is False
        assert session.parser.config.max_message_size == 2048


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
        """Test that connect() creates no asyncio tasks; they live in the
        runner."""
        # Arrange
        tasks_before = asyncio.all_tasks()

        # Act
        await session.connect()

        # Assert
        assert asyncio.all_tasks() == tasks_before


class TestFIXSessionHeartbeatDecision:
    """Test check_peer_liveness() — the protocol decision behind monitoring."""

    @pytest.mark.asyncio
    async def test_noop_when_not_logged_on(self, session):
        """Test that check_peer_liveness() does nothing unless logged on."""
        # Act
        await session.check_peer_liveness()

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
        await session.check_peer_liveness()

        # Assert
        assert session._send_queue.empty()
        assert session._state.test_request_id is None

    @pytest.mark.asyncio
    async def test_noop_within_grace_window(self, session):
        """FIX 4.4 allows ~120% of the interval before probing.

        A peer silent for 1.1x the interval is still within the grace
        window and must not trigger a TestRequest.
        """
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 1.1
        )

        # Act
        await session.check_peer_liveness()

        # Assert
        assert session._send_queue.empty()
        assert session._state.test_request_id is None

    @pytest.mark.asyncio
    async def test_probes_after_grace_window(self, session):
        """A peer silent beyond 1.2x the interval triggers a TestRequest."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 1.3
        )

        # Act
        await session.check_peer_liveness()

        # Assert
        assert not session._send_queue.empty()
        msg = session._send_queue.get_nowait()
        assert msg[35] == MsgType.TEST_REQUEST

    @pytest.mark.asyncio
    async def test_sends_test_request_when_peer_silent(self, session):
        """Test that a silent peer triggers a TestRequest."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.check_peer_liveness()

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
        await session.check_peer_liveness()

        # Assert
        assert session.status == SessionStatus.ERROR

    @pytest.mark.asyncio
    async def test_heartbeat_timeout_queues_logout(self, session):
        """An unanswered TestRequest terminates with a Logout, per FIX 4.4.

        The peer should be told why the session is ending, not just have
        the transport cut.
        """
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.test_request_id = "PREV-REQ"
        session._state.last_received_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.check_peer_liveness()

        # Assert: Logout queued before the session parks in ERROR
        logout = session._send_queue.get_nowait()
        assert logout[35] == MsgType.LOGOUT
        assert session.status == SessionStatus.ERROR


class TestFIXSessionPendingOutbound:
    """Inspecting and discarding what is queued but not yet on the wire."""

    @pytest.mark.asyncio
    async def test_pending_send_count_tracks_the_queue(self, session):
        """The count reflects messages queued for the writer."""
        # Arrange
        assert session.pending_send_count() == 0

        # Act
        await session.send(
            FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        )

        # Assert
        assert session.pending_send_count() == 1

    @pytest.mark.asyncio
    async def test_discard_pending_send_returns_messages_and_rewinds(
        self, session
    ):
        """Discarded messages come back and their seq numbers are reusable.

        They were never handed to the transport, so rewinding keeps the
        peer from seeing a gap that would have to be gap-filled away.
        """
        # Arrange
        await session.send(
            FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        )
        await session.send(
            FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        )
        assert session.get_next_send_seq_num() == 3

        # Act
        discarded = session.discard_pending_send()

        # Assert
        assert [m.msg_type for m in discarded] == [MsgType.HEARTBEAT] * 2
        assert session.pending_send_count() == 0
        assert session.get_next_send_seq_num() == 1

    @pytest.mark.asyncio
    async def test_discard_pending_send_on_empty_queue_is_a_noop(self, session):
        """Nothing queued means nothing to rewind."""
        # Arrange
        seq_before = session.get_next_send_seq_num()

        # Act
        discarded = session.discard_pending_send()

        # Assert
        assert discarded == []
        assert session.get_next_send_seq_num() == seq_before


class TestFIXSessionSendGuard:
    """Application traffic is only accepted on a logged-on session.

    A message parked on a dead session either has to be flushed onto the
    next connection (invalid: it would precede the Logon) or dropped,
    which loses it silently. Refusing at submission time is the only point
    where the caller can still react.
    """

    @staticmethod
    def _order() -> FIXMessage:
        """A minimal application message (NewOrderSingle)."""
        msg = FIXMessage()
        msg.msg_type = MsgType.NEW_ORDER_SINGLE
        return msg

    @pytest.mark.asyncio
    async def test_rejects_application_message_when_disconnected(self, session):
        """The default state refuses application traffic."""
        # Act & Assert
        with pytest.raises(SessionNotLoggedOnError, match="disconnected"):
            await session.send(self._order())

    @pytest.mark.asyncio
    async def test_rejected_message_consumes_no_sequence_number(self, session):
        """A refused message must not leave a hole in the outgoing seq."""
        # Arrange
        seq_before = session.get_next_send_seq_num()

        # Act
        with pytest.raises(SessionNotLoggedOnError):
            await session.send(self._order())

        # Assert
        assert session.get_next_send_seq_num() == seq_before
        assert session.pending_send_count() == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [
            SessionStatus.CONNECTING,
            SessionStatus.WAITING_LOGON,
            SessionStatus.WAITING_LOGOUT,
            SessionStatus.ERROR,
        ],
    )
    async def test_rejects_application_message_in_any_other_state(
        self, session, status
    ):
        """Only LOGGED_ON accepts application traffic."""
        # Arrange
        session.status = status

        # Act & Assert
        with pytest.raises(SessionNotLoggedOnError):
            await session.send(self._order())

    @pytest.mark.asyncio
    async def test_accepts_application_message_when_logged_on(self, session):
        """A live session queues application traffic normally."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON

        # Act
        await session.send(self._order())

        # Assert
        assert session.pending_send_count() == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "msg_type",
        [
            MsgType.LOGON,
            MsgType.LOGOUT,
            MsgType.HEARTBEAT,
            MsgType.TEST_REQUEST,
            MsgType.RESEND_REQUEST,
            MsgType.SEQUENCE_RESET,
            MsgType.REJECT,
        ],
    )
    async def test_session_messages_are_allowed_before_logon(
        self, session, msg_type
    ):
        """The handshake must work before the session is logged on."""
        # Arrange: DISCONNECTED
        msg = FIXMessage()
        msg.msg_type = msg_type

        # Act
        await session.send(msg)

        # Assert
        assert session.pending_send_count() == 1


class TestFIXSessionHeartbeatSend:
    """Outbound heartbeats: send one when we have been quiet.

    FIX 4.4 expects each side to send a Heartbeat if nothing has gone out
    within HeartBtInt. Without this we only stay alive because the peer
    probes us.
    """

    @pytest.mark.asyncio
    async def test_sends_heartbeat_when_idle(self, session):
        """No outbound traffic for a full interval produces a Heartbeat."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_sent_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.send_heartbeat_if_idle()

        # Assert
        assert not session._send_queue.empty()
        msg = session._send_queue.get_nowait()
        assert msg[35] == MsgType.HEARTBEAT

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_recently_active(self, session):
        """Recent outbound traffic suppresses the idle Heartbeat."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_sent_time = utc_now()

        # Act
        await session.send_heartbeat_if_idle()

        # Assert
        assert session._send_queue.empty()

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_not_logged_on(self, session):
        """Nothing is sent before the session is established."""
        # Arrange: DISCONNECTED, last_sent long ago
        session._state.last_sent_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.send_heartbeat_if_idle()

        # Assert
        assert session._send_queue.empty()

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes_last_sent_time(self, session):
        """Sending the Heartbeat updates last_sent_time via send()."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        session._state.last_sent_time = utc_now() - timedelta(
            seconds=session.config.heartbeat_interval * 2
        )

        # Act
        await session.send_heartbeat_if_idle()

        # Assert
        assert session._state.last_sent_time is not None
        idle = (utc_now() - session._state.last_sent_time).total_seconds()
        assert idle < 1.0


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

    @pytest.mark.asyncio
    async def test_connect_preserves_sequence_numbers_by_default(self, session):
        """connect() must not reset sequence numbers unless configured to.

        FIX requires sequence continuity across a reconnect. Wiping the
        counters unconditionally makes the peer see a false gap.
        """
        # Arrange: a session mid-life, as after a reconnect
        session._state.outgoing_seq_num = 100
        session._state.incoming_seq_num = 50
        assert session.config.reset_seq_num is False  # the default

        # Act
        await session.connect()

        # Assert: the Logon continues the sequence, counters were not wiped
        logon = session._send_queue.get_nowait()
        assert logon.sequence == 101
        assert session.get_next_send_seq_num() == 102
        assert session.get_next_expected_seq_num() == 51

    @pytest.mark.asyncio
    async def test_connect_resets_sequence_numbers_when_configured(self, session):
        """connect() resets both counters when reset_seq_num is True."""
        # Arrange
        session.config.reset_seq_num = True
        session._state.outgoing_seq_num = 100
        session._state.incoming_seq_num = 50

        # Act
        await session.connect()

        # Assert: the Logon opens the session at seq 1
        logon = session._send_queue.get_nowait()
        assert logon.sequence == 1
        assert session.get_next_send_seq_num() == 2
        assert session.get_next_expected_seq_num() == 1


class TestFIXSessionLogonBaseline:
    """Receiving a Logon establishes the incoming sequence baseline.

    Both roles must set it, and it must reflect the Logon as *consumed*:
    after a Logon with MsgSeqNum N, the next expected message is N+1.
    Getting this wrong makes the first post-logon message look like a gap
    once incoming sequence verification is enabled.
    """

    @pytest.mark.asyncio
    async def test_initiator_logon_sets_baseline(self, session):
        """Initiator: the peer's Logon reply sets the baseline."""
        # Arrange: we sent the Logon and are awaiting the reply
        session.status = SessionStatus.WAITING_LOGON
        logon = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=42)

        # Act
        await session.receive(logon.serialize())

        # Assert: seq 42 consumed, so 43 is next expected
        assert session.status == SessionStatus.LOGGED_ON
        assert session._state.incoming_seq_num == 42
        assert session.get_next_expected_seq_num() == 43

    @pytest.mark.asyncio
    async def test_acceptor_logon_sets_baseline(self, session):
        """Acceptor: the peer's Logon establishes the baseline."""
        # Arrange: we are accepting an inbound Logon
        logon = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=7)

        # Act
        await session.receive(logon.serialize())

        # Assert: seq 7 consumed, so 8 is next expected
        assert session.status == SessionStatus.LOGGED_ON
        assert session._state.incoming_seq_num == 7
        assert session.get_next_expected_seq_num() == 8


class TestFIXSessionIncomingSequence:
    """Incoming sequence number verification (FIX 4.4).

    Every non-Logon, non-SequenceReset message is checked against the
    expected next incoming MsgSeqNum:

    - equal        -> process, advance
    - greater      -> gap: send ResendRequest, do not process
    - lower + PossDupFlag -> duplicate: ignore
    - lower        -> terminate: send Logout, move to ERROR
    """

    @pytest.mark.asyncio
    async def test_accepts_expected_sequence(self, session):
        """A message with the expected MsgSeqNum is processed and advances."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=1)

        # Act
        await session.receive(msg.serialize())

        # Assert
        assert session._state.incoming_seq_num == 1
        assert session.get_next_expected_seq_num() == 2

    @pytest.mark.asyncio
    async def test_accepts_ordered_stream(self, session):
        """Consecutive in-sequence messages are all processed."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON

        # Act
        for seq in (1, 2, 3):
            msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=seq)
            await session.receive(msg.serialize())

        # Assert
        assert session._state.incoming_seq_num == 3
        assert session._send_queue.empty()

    @pytest.mark.asyncio
    async def test_gap_sends_resend_request(self, session):
        """A MsgSeqNum above expected requests the missing range."""
        # Arrange: expecting 1, receive 5
        session.status = SessionStatus.LOGGED_ON
        msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=5)

        # Act
        await session.receive(msg.serialize())

        # Assert: ResendRequest for 1..4
        request = session._send_queue.get_nowait()
        assert request[35] == MsgType.RESEND_REQUEST
        assert request[7] == "1"
        assert request[16] == "4"

    @pytest.mark.asyncio
    async def test_gap_does_not_dispatch_message(self, session):
        """The out-of-order message is not handed to the application."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        received = []
        session.on_message(received.append)
        msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=5)

        # Act
        await session.receive(msg.serialize())

        # Assert
        assert received == []
        assert session._state.incoming_seq_num == 0  # not advanced

    @pytest.mark.asyncio
    async def test_duplicate_ignored_when_poss_dup(self, session):
        """A low MsgSeqNum with PossDupFlag=Y is silently ignored."""
        # Arrange: already at 5, receive a duplicate of 3
        session.status = SessionStatus.LOGGED_ON
        session._state.incoming_seq_num = 5
        msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=3)
        msg.set(43, "Y")

        # Act
        await session.receive(msg.serialize())

        # Assert: unchanged, nothing sent, still logged on
        assert session._state.incoming_seq_num == 5
        assert session._send_queue.empty()
        assert session.status == SessionStatus.LOGGED_ON

    @pytest.mark.asyncio
    async def test_low_sequence_logs_out(self, session):
        """A low MsgSeqNum without PossDupFlag terminates the session."""
        # Arrange: already at 5, receive 3
        session.status = SessionStatus.LOGGED_ON
        session._state.incoming_seq_num = 5
        msg = FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=3)

        # Act
        await session.receive(msg.serialize())

        # Assert: Logout queued with the expected/actual detail, session ERROR
        logout = session._send_queue.get_nowait()
        assert logout[35] == MsgType.LOGOUT
        assert "too low" in logout[58]
        assert session.status == SessionStatus.ERROR

    @pytest.mark.asyncio
    async def test_logon_exempt_from_sequence_check(self, session):
        """A Logon establishes the baseline instead of being checked."""
        # Arrange: not logged on, Logon arrives with an arbitrary seq
        logon = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=50)

        # Act
        await session.receive(logon.serialize())

        # Assert: no ResendRequest; baseline set from the Logon
        assert session.status == SessionStatus.LOGGED_ON
        assert session._state.incoming_seq_num == 50

    @pytest.mark.asyncio
    async def test_gap_fill_advances_expected(self, session):
        """SequenceReset-GapFill adjusts the expected next number."""
        # Arrange
        session.status = SessionStatus.LOGGED_ON
        reset = FIXMessageFactory.create_sequence_reset(
            "SERVER", "CLIENT", seq=1, new_seq_no=10, gap_fill=True
        )

        # Act
        await session.receive(reset.serialize())

        # Assert: next expected is the NewSeqNo
        assert session._state.incoming_seq_num == 9
        assert session.get_next_expected_seq_num() == 10


class TestFIXSessionLogonAdmission:
    """A validator can veto an inbound Logon before the session accepts it."""

    @pytest.mark.asyncio
    async def test_validator_can_reject_logon(self, session):
        """A rejecting validator queues a Logout and moves to ERROR."""
        # Arrange
        session.on_logon_request(lambda msg: False)
        logon = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=1)

        # Act
        await session.receive(logon.serialize())

        # Assert
        logout = session._send_queue.get_nowait()
        assert logout[35] == MsgType.LOGOUT
        assert "already logged on" in logout[58]
        assert session.status == SessionStatus.ERROR

    @pytest.mark.asyncio
    async def test_validator_can_accept_logon(self, session):
        """An accepting validator lets the session log on normally."""
        # Arrange
        session.on_logon_request(lambda msg: True)
        logon = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=1)

        # Act
        await session.receive(logon.serialize())

        # Assert
        assert session.status == SessionStatus.LOGGED_ON

    @pytest.mark.asyncio
    async def test_rejection_logout_targets_the_peer(self, session):
        """The rejection Logout is addressed to the peer's SenderCompID."""
        # Arrange
        session.on_logon_request(lambda msg: False)
        logon = FIXMessageFactory.create_logon("PEER01", "CLIENT", seq=1)

        # Act
        await session.receive(logon.serialize())

        # Assert: TargetCompID is the peer, not the configured placeholder
        logout = session._send_queue.get_nowait()
        assert logout[56] == "PEER01"


class TestFIXSessionDisconnect:
    """disconnect() is a pure state transition — it must not wait.

    Owning time is the caller's job (see FIXSessionRunner.disconnect). These tests
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
