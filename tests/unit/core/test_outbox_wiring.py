"""Outbox wiring: a sent message is durable before it can leave.

If the connection drops after a message took a sequence number, the peer
will ask for it. Without a stored copy the only answer is a GapFill, which
tells the peer the message never existed.
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


def _heartbeat() -> FIXMessage:
    return FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)


class _Recorder:
    """Records the order in which the session persisted things."""

    def __init__(self) -> None:
        self.events: list[str] = []


class _RecordingSequenceStore(InMemorySequenceStore):
    def __init__(self, recorder: _Recorder) -> None:
        super().__init__()
        self._recorder = recorder

    async def save(self, state) -> None:
        self._recorder.events.append("sequence")
        await super().save(state)


class _RecordingOutbox(InMemoryOutbox):
    def __init__(self, recorder: _Recorder) -> None:
        super().__init__()
        self._recorder = recorder

    async def append(self, key, seq, data: bytes) -> None:
        self._recorder.events.append("outbox")
        await super().append(key, seq, data)


class _FailingOutbox:
    """An outbox whose writes always fail."""

    async def append(self, key, seq, data: bytes) -> None:
        raise OutboxError("disk full")

    async def get_range(self, key, begin: int, end: int = 0) -> list[bytes]:
        return []

    async def prune(self, key, through: int) -> None:
        pass

    async def truncate(self, key, after: int) -> None:
        pass

    async def clear(self, key) -> None:
        pass

    async def count(self, key) -> int:
        return 0


class TestOutboxWiring:
    """The session keeps a copy of everything it hands to the writer."""

    @pytest.mark.asyncio
    async def test_send_stores_the_serialized_message(self):
        """The stored bytes are the wire form, ready to be rebuilt on resend."""
        # Arrange
        outbox = InMemoryOutbox()
        session = FIXSession(_config(outbox=outbox))
        session.status = SessionStatus.LOGGED_ON
        msg = _heartbeat()

        # Act
        await session.send(msg)

        # Assert
        assert await outbox.get_range(KEY, 1, 1) == [msg.serialize()]

    @pytest.mark.asyncio
    async def test_sequence_is_saved_before_the_outbox_append(self):
        """A crash between the two must leave a gap, never a reused number."""
        # Arrange
        recorder = _Recorder()
        session = FIXSession(
            _config(
                sequence_store=_RecordingSequenceStore(recorder),
                outbox=_RecordingOutbox(recorder),
            )
        )
        session.status = SessionStatus.LOGGED_ON

        # Act
        await session.send(_heartbeat())

        # Assert
        assert recorder.events == ["sequence", "outbox"]

    @pytest.mark.asyncio
    async def test_outbox_failure_prevents_queueing(self):
        """No stored copy means no message on the wire."""
        # Arrange
        session = FIXSession(_config(outbox=_FailingOutbox()))
        session.status = SessionStatus.LOGGED_ON

        # Act & Assert
        with pytest.raises(OutboxError):
            await session.send(_heartbeat())

        assert session.pending_send_count() == 0

    @pytest.mark.asyncio
    async def test_discarding_pending_messages_truncates_the_outbox(self):
        """Messages that will never be sent must not be replayable."""
        # Arrange
        outbox = InMemoryOutbox()
        session = FIXSession(_config(outbox=outbox))
        session.status = SessionStatus.LOGGED_ON
        await session.send(_heartbeat())
        await session.send(_heartbeat())
        assert await outbox.count(KEY) == 2

        # Act
        await session.discard_pending_send()

        # Assert
        assert await outbox.count(KEY) == 0
