"""M3 chaos scenarios: crash mid-write, drop mid-message, restart.

These are the failure modes the persistence layers exist for. Each test puts
the session in a state a crash or a dropped wire can produce, then checks
that sequence integrity survives — which is the one thing FIX will not
forgive.
"""

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.message import FIXMessage
from fixwire.core.outbox import InMemoryOutbox, OutboxError
from fixwire.core.sequence import InMemorySequenceStore
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus

KEY = ("CLIENT", "SERVER")


def _config(**overrides) -> SessionConfig:
    return SessionConfig(
        sender_comp_id="CLIENT", target_comp_id="SERVER", **overrides
    )


def _heartbeat(seq: int = 1) -> FIXMessage:
    return FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=seq)


class _FailingAppendOutbox:
    """A real outbox that fails on append.

    Models the process dying between the sequence write and the outbox
    write.
    """

    def __init__(self, inner: InMemoryOutbox) -> None:
        self._inner = inner

    async def append(self, key, seq: int, data: bytes) -> None:
        raise OutboxError("process died")

    async def get_range(self, key, begin: int, end: int = 0) -> list[bytes]:
        return await self._inner.get_range(key, begin, end)

    async def prune(self, key, through: int) -> None:
        await self._inner.prune(key, through)

    async def truncate(self, key, after: int) -> None:
        await self._inner.truncate(key, after)

    async def clear(self, key) -> None:
        await self._inner.clear(key)

    async def count(self, key) -> int:
        return await self._inner.count(key)


class TestCrashBetweenWrites:
    """A crash between the two write-ahead steps must not corrupt history."""

    @pytest.mark.asyncio
    async def test_crash_after_sequence_before_outbox_leaves_a_gap(self):
        """The number is spent; the message is gone; the peer sees a gap.

        This is the deliberate trade-off in ``send()``: a gap is
        recoverable (the peer asks, and M5 will gap-fill), whereas reusing a
        number the peer may already have seen is not.
        """
        # Arrange
        sequences = InMemorySequenceStore()
        outbox = InMemoryOutbox()
        session = FIXSession(
            _config(
                sequence_store=sequences,
                outbox=_FailingAppendOutbox(outbox),
            )
        )
        session.status = SessionStatus.LOGGED_ON

        # Act: the sequence is persisted, then the process dies
        with pytest.raises(OutboxError):
            await session.send(_heartbeat())

        # Assert: number spent, nothing stored, nothing queued
        stored = await sequences.load(KEY)
        assert stored is not None and stored.outgoing == 1
        assert await outbox.count(KEY) == 0
        assert session.pending_send_count() == 0

        # And a restart must not hand out sequence 1 again
        resumed = FIXSession(
            _config(sequence_store=sequences, outbox=outbox)
        )
        await resumed.connect()
        assert resumed._send_queue.get_nowait().sequence == 2

    @pytest.mark.asyncio
    async def test_crash_after_outbox_before_the_wire_is_replayable(self):
        """The message never reached the peer, but it is not lost either.

        The number is spent (no reuse) and the bytes are in the outbox, so
        a resend can answer the peer's request instead of gap-filling.
        """
        # Arrange: both writes succeed, then the process dies before the
        # writer runs
        sequences = InMemorySequenceStore()
        outbox = InMemoryOutbox()
        session = FIXSession(
            _config(sequence_store=sequences, outbox=outbox)
        )
        session.status = SessionStatus.LOGGED_ON
        sent = _heartbeat()

        # Act
        await session.send(sent)

        # Assert: stored and replayable
        assert await outbox.get_range(KEY, 1, 1) == [sent.serialize()]

        # Restart resumes past it, without reusing sequence 1
        resumed = FIXSession(
            _config(sequence_store=sequences, outbox=outbox)
        )
        await resumed.connect()
        assert resumed._send_queue.get_nowait().sequence == 2


class TestDropMidMessage:
    """A connection that dies mid-message must not poison what follows."""

    @pytest.mark.asyncio
    async def test_partial_message_is_not_dispatched(self):
        """Half a message produces nothing: no event, no sequence advance."""
        # Arrange
        session = FIXSession(_config())
        session.status = SessionStatus.LOGGED_ON
        received: list[FIXMessage] = []
        session.on_message(received.append)
        raw = _heartbeat().serialize()

        # Act: the first half arrives, then the wire dies
        await session.receive(raw[: len(raw) // 2])

        # Assert
        assert received == []
        assert session.get_next_expected_seq_num() == 1

    @pytest.mark.asyncio
    async def test_stale_bytes_do_not_survive_a_reconnect(self):
        """A new connection starts a new byte stream.

        The half-message left in the parser buffer must be discarded, or
        the peer's first message on the new connection is parsed as a
        continuation of the dead one.
        """
        # Arrange: a partial message, then a reconnect
        session = FIXSession(_config())
        session.status = SessionStatus.LOGGED_ON
        raw = _heartbeat().serialize()
        await session.receive(raw[: len(raw) // 2])

        # Act
        await session.connect()

        # Assert: the peer's Logon parses cleanly instead of colliding
        peer_logon = FIXMessageFactory.create_logon(
            sender="SERVER", target="CLIENT", seq=1
        )
        await session.receive(peer_logon.serialize())

        assert session.status == SessionStatus.LOGGED_ON

    @pytest.mark.asyncio
    async def test_the_new_connection_resumes_normally(self):
        """After the reconnect, messages flow and advance exactly once."""
        # Arrange
        session = FIXSession(_config())
        session.status = SessionStatus.LOGGED_ON
        seen: list[str] = []
        session.on_message(lambda msg: seen.append(msg.msg_type))
        raw = _heartbeat().serialize()

        # Act: partial bytes, then a clean reconnect and a normal exchange
        await session.receive(raw[: len(raw) // 2])
        await session.connect()
        await session.receive(
            FIXMessageFactory.create_logon(
                sender="SERVER", target="CLIENT", seq=1
            ).serialize()
        )
        await session.receive(_heartbeat(seq=2).serialize())

        # Assert: both parsed messages dispatched, sequence advanced once more
        assert seen == ["A", "0"]
        assert session.get_next_expected_seq_num() == 3
