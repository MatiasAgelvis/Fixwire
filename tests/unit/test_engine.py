"""Tests for FIXEngine."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from fixwire.core.factory import FIXMessageFactory
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
    """Test that reconnect() is not yet implemented."""

    @pytest.mark.asyncio
    async def test_reconnect_not_implemented(self, engine):
        """Test that reconnect() raises NotImplementedError."""
        # Act & Assert
        with pytest.raises(NotImplementedError):
            await engine.reconnect()


class TestFIXEngineConnect:
    """Test FIXEngine.connect(): open transport, spawn tasks, drive logon.

    Covers the happy path (transport opens, both tasks spawn, logon handshake
    reaches LOGGED_ON), idempotency, and every failure mode we expect
    connect() to surface: transport failure, logon timeout, and a malformed
    peer response. These tests are the contract for connect() — they pin the
    observable behaviour the implementation must satisfy.
    """

    # --- happy path ---

    @pytest.mark.asyncio
    async def test_connect_opens_transport(self, engine, transport):
        """After connect(), transport.is_connected is True."""
        # Arrange: pre-feed a Logon so the handshake can complete
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        # Act
        await engine.connect()

        # Assert
        assert transport.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_spawns_writer_and_reader_tasks(self, engine):
        """After connect(), both _writer_task and _reader_task are not None."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        engine._transport.feed(peer_logon.serialize())  # type: ignore[attr-defined]

        # Act
        await engine.connect()

        # Assert
        assert engine._writer_task is not None
        assert engine._reader_task is not None

    @pytest.mark.asyncio
    async def test_connect_sends_logon_on_wire(
        self, engine, session, transport
    ):
        """First message on transport.sent is a Logon (tag 35='A')."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        # Act
        await engine.connect()
        await _drain_writer(engine)

        # Assert
        assert transport.sent, "Expected a Logon to be sent"
        assert b"35=A\x01" in transport.sent[0]

    @pytest.mark.asyncio
    async def test_connect_drives_session_to_logged_on(
        self, engine, session, transport
    ):
        """When peer replies Logon, session.status reaches LOGGED_ON and
        _state.logon_time is set."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        # Act
        await engine.connect()

        # Assert
        assert session.status == SessionStatus.LOGGED_ON
        assert session._state.logon_time is not None

    @pytest.mark.asyncio
    async def test_connect_logon_timeout_raises_and_tears_down(
        self, engine, session, transport
    ):
        """If peer never replies Logon, connect() raises TimeoutError within
        session.config.logon_timeout AND tears down cleanly: session moves
        out of WAITING_LOGON, transport is closed, both tasks are stopped."""
        # Arrange: nothing fed → the logon handshake will time out
        session.config.logon_timeout = 0.1

        # Act + Assert: bounded by 2s as a hang-safety guardrail;
        # the engine itself must raise TimeoutError within logon_timeout
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(engine.connect(), timeout=2.0)

        # Post-conditions: clean teardown
        assert session.status != SessionStatus.LOGGED_ON
        assert not transport.is_connected
        assert engine._writer_task is None
        assert engine._reader_task is None

    # --- idempotency ---

    @pytest.mark.asyncio
    async def test_connect_is_idempotent(self, engine, transport):
        """A second connect() is a no-op: no extra tasks, no second Logon."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        # Act
        await engine.connect()
        sent_after_first = len(transport.sent)
        first_writer_task = engine._writer_task
        first_reader_task = engine._reader_task

        await engine.connect()

        # Assert
        assert len(transport.sent) == sent_after_first
        assert engine._writer_task is first_writer_task
        assert engine._reader_task is first_reader_task

    # --- failure paths ---

    @pytest.mark.asyncio
    async def test_connect_propagates_transport_connect_failure(
        self, engine, transport, session
    ):
        """If transport.connect() raises, the exception surfaces, no tasks
        are spawned, no Logon is sent, session stays DISCONNECTED."""
        # Arrange: configure the transport to fail on connect()
        transport.connect = AsyncMock(
            side_effect=ConnectionError("can't reach peer")
        )

        # Act + Assert
        with pytest.raises(ConnectionError):
            await engine.connect()

        # Post-conditions
        assert engine._writer_task is None
        assert engine._reader_task is None
        assert transport.sent == []
        assert session.status == SessionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_recovers_from_malformed_logon_response(
        self, engine, session, transport
    ):
        """If peer's Logon response is malformed, the reader's task guard
        moves session.status to ERROR and connect() surfaces the failure as
        a ConnectionError; transport is closed; tasks are stopped."""
        # Arrange: feed bytes that start with '8=' but aren't a valid FIX
        # message — this triggers the strict-mode BeginString check in
        # FIXParser, which raises FIXParseError.
        transport.feed(b"8=NOPE\x01")

        # Act: the connect() attempt fails. ConnectionError is the engine's
        # standard "the connection could not be established" exception
        # (consistent with how _safe_send wraps transport failures).
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(engine.connect(), timeout=2.0)

        # Assert: post-conditions
        assert session.status == SessionStatus.ERROR
        assert not transport.is_connected
        assert engine._writer_task is None
        assert engine._reader_task is None


class TestFIXEngineWriterTask:
    """Test the writer task: drain session._send_queue, serialize, transport.send."""

    @pytest.mark.asyncio
    async def test_writer_drains_queued_message(self, engine, session, transport):
        """Test that the writer task serializes and sends a queued message."""
        # Arrange
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        await session.send(msg)
        expected = msg.serialize()

        # Act
        await engine.start()
        await _drain_writer(engine)

        # Assert
        assert transport.sent == [expected]

    @pytest.mark.asyncio
    async def test_writer_drains_multiple_messages_in_order(
        self, engine, session, transport
    ):
        """Test that queued messages are sent in FIFO order."""
        # Arrange
        msg1 = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        msg2 = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        await session.send(msg1)
        await session.send(msg2)
        expected = [msg1.serialize(), msg2.serialize()]

        # Act
        await engine.start()
        await _drain_writer(engine)

        # Assert
        assert transport.sent == expected

    @pytest.mark.asyncio
    async def test_writer_serializes_to_fix_bytes(
        self, engine, session, transport
    ):
        """Test that the writer produces valid FIX bytes (BeginString 8=FIX.4.4)."""
        # Arrange
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        await session.send(msg)

        # Act
        await engine.start()
        await _drain_writer(engine)

        # Assert
        assert transport.sent[0].startswith(b"8=FIX.4.4\x01")

    @pytest.mark.asyncio
    async def test_writer_idle_on_empty_queue(self, engine, session, transport):
        """Test that the writer stays alive with nothing queued and sends nothing."""
        # Act
        await engine.start()
        await asyncio.sleep(0)  # yield to let the writer loop once
        await engine.stop()

        # Assert
        assert transport.sent == []

    @pytest.mark.asyncio
    async def test_writer_transport_error_sets_error_status(
        self, engine, session, transport
    ):
        """Test that a transport.send() failure sets session.status to ERROR."""
        # Arrange: arrange a transport that raises on first send
        async def boom(_: bytes) -> None:
            raise ConnectionError("write failed")
        transport.send = boom  # type: ignore[method-assign]
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)
        await session.send(msg)

        # Act
        await engine.start()
        await _wait_for_status(session, SessionStatus.ERROR, timeout=1.0)

        # Assert
        assert session.status == SessionStatus.ERROR


class TestFIXEngineReaderTask:
    """Test the reader task: drain transport, feed session.receive().

    Mirror image of TestFIXEngineWriterTask. Covers happy path (transport
    bytes are processed by the session), failure paths (transport failure
    and parser failure both escalate to session.status = ERROR), and
    lifecycle (clean stop is not treated as an error).
    """

    @pytest.mark.asyncio
    async def test_reader_feeds_transport_bytes_into_session(
        self, engine, session, transport
    ):
        """Feeding a Heartbeat via InMemoryTransport causes session to
        process it. We use a previously-set test_request_id: a matching
        Heartbeat response from the peer should clear it.
        """
        # Arrange: set a known test_request_id on our side
        session._state.test_request_id = "TEST-123"

        # Build a Heartbeat that echoes the test request id (tag 112)
        peer_hb = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=1, test_req_id="TEST-123"
        )
        transport.feed(peer_hb.serialize())

        # Act: start the engine so the reader runs, then drain
        await engine.start()
        await _drain_reader(engine)

        # Assert: the test request was cleared by the reader's payload
        assert session._state.test_request_id is None

        # Cleanup: stop the engine so the tasks don't outlive the test
        await engine.stop()

    @pytest.mark.asyncio
    async def test_reader_drains_multiple_messages_in_order(
        self, engine, session, transport
    ):
        """Multiple bytes fed to transport are processed in order. We verify
        ordering by feeding two heartbeats with distinct test_req_ids and
        checking the session clears the first one before the second."""
        # Arrange
        session._state.test_request_id = "FIRST"
        first = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=1, test_req_id="FIRST"
        )
        transport.feed(first.serialize())
        # second arrives with no pending test request — just a vanilla heartbeat
        second = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=2
        )
        transport.feed(second.serialize())

        # Act
        await engine.start()
        await _drain_reader(engine)

        # Assert: first id was cleared by the first heartbeat
        assert session._state.test_request_id is None

        # Cleanup: stop the engine so the tasks don't outlive the test
        await engine.stop()

    @pytest.mark.asyncio
    async def test_reader_transport_failure_sets_error_status(
        self, engine, session, transport
    ):
        """When transport.receive() raises ConnectionError (mid-read
        disconnect), the reader's task guard sets session.status = ERROR
        and tears the engine down."""
        # Arrange: replace receive to raise
        async def boom() -> bytes:
            raise ConnectionError("peer dropped")
        transport.receive = boom  # type: ignore[method-assign]

        # Act
        await engine.start()
        await _wait_for_status(session, SessionStatus.ERROR, timeout=1.0)

        # Assert
        assert session.status == SessionStatus.ERROR

    @pytest.mark.asyncio
    async def test_reader_session_parse_failure_sets_error_status(
        self, engine, session, transport
    ):
        """When session.receive() raises on malformed bytes, the reader's
        task guard sets session.status = ERROR."""
        # Arrange
        transport.feed(b"not a fix message\x01")

        # Act
        await engine.start()
        await _wait_for_status(session, SessionStatus.ERROR, timeout=1.0)

        # Assert
        assert session.status == SessionStatus.ERROR

        # Cleanup: task guard already called stop(), but be explicit for symmetry
        await engine.stop()

    @pytest.mark.asyncio
    async def test_reader_does_not_set_error_on_clean_stop(
        self, engine, session
    ):
        """When stop() signals shutdown, the reader exits cleanly without
        setting ERROR. Confirms task guards only fire on real errors, not
        on lifecycle."""
        # Arrange: engine running, no errors anywhere
        await engine.start()
        await asyncio.sleep(0)  # let the reader loop once

        # Act
        await engine.stop()

        # Assert: session is untouched
        assert session.status == SessionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_reader_idle_on_empty_transport(
        self, engine, session, transport
    ):
        """Reader stays alive on a transport with no inbound bytes and
        changes nothing. Symmetric to the writer's idle test."""
        # Act
        await engine.start()
        await asyncio.sleep(0)
        await engine.stop()

        # Assert
        assert session.status == SessionStatus.DISCONNECTED
        assert transport.sent == []


class TestFIXEngineCoordination:
    """Test the interaction between connect(), reader, writer, and session.

    These tests verify that after connect() returns, the engine is fully
    wired: a queued send actually reaches the wire, and an inbound feed
    actually reaches the session. Proves the engine isn't a façade.
    """

    @pytest.mark.asyncio
    async def test_after_connect_writer_sends_queued_message(
        self, engine, session, transport
    ):
        """After connect(), a Heartbeat queued via session.send() reaches
        transport.sent. Proves the writer is wired up post-connect."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)

        # Act
        await engine.connect()
        await session.send(msg)
        await _drain_writer(engine)

        # Assert
        assert msg.serialize() in transport.sent

    @pytest.mark.asyncio
    async def test_after_connect_reader_processes_inbound_message(
        self, engine, session, transport
    ):
        """After connect(), feeding a Heartbeat via the transport is
        observed by the session. Proves the reader is wired up post-connect."""
        # Arrange
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        transport.feed(peer_logon.serialize())

        # Act: connect first, then feed a follow-up heartbeat
        await engine.connect()
        session._state.test_request_id = "POST-CONNECT"
        follow_up = FIXMessageFactory.create_heartbeat(
            sender="SERVER", target="CLIENT", seq=2, test_req_id="POST-CONNECT"
        )
        transport.feed(follow_up.serialize())
        await _drain_reader(engine)

        # Assert
        assert session._state.test_request_id is None


async def _drain_writer(engine: FIXEngine) -> None:
    """Wait until the writer task has drained the session queue.

    Gives the event loop a few turns to process queued messages plus a
    settle window so callers don't race the task.
    """
    # Wake the writer up to four times so it gets every queued item.
    for _ in range(4):
        if engine._session._send_queue.empty():
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0)  # let the final put_nowait() in serialize() settle


async def _drain_reader(engine: FIXEngine, turns: int = 4) -> None:
    """Yield to the event loop a few times so the reader task can process
    anything the transport has already received.
    """
    for _ in range(turns):
        await asyncio.sleep(0)


async def _wait_for_status(
    session: FIXSession, target: SessionStatus, timeout: float
) -> None:
    """Wait until session.status reaches target or raise TimeoutError."""
    deadline = asyncio.get_event_loop().time() + timeout
    while session.status != target:
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(
                f"session.status did not reach {target} within {timeout}s"
            )
        await asyncio.sleep(0.01)
