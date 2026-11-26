"""Session wiring for sequence persistence.

A FIX session must resume its sequence numbers after a restart: reusing a
number the peer has already seen corrupts the session. These tests cover
the seam between the state machine and the store.
"""

import pytest

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.message import FIXMessage
from fixwire.core.sequence import (
    InMemorySequenceStore,
    SequenceState,
    SequenceStoreError,
)
from fixwire.core.session import FIXSession, SessionConfig, SessionStatus
from fixwire.core.tags import MsgType

KEY = ("CLIENT", "SERVER")


def _config(**overrides) -> SessionConfig:
    return SessionConfig(
        sender_comp_id="CLIENT", target_comp_id="SERVER", **overrides
    )


def _heartbeat(seq: int = 1) -> FIXMessage:
    return FIXMessageFactory.create_heartbeat("SERVER", "CLIENT", seq=seq)


class _FailingStore:
    """A store whose writes always fail."""

    async def load(self, key):
        return None

    async def save(self, state):
        raise SequenceStoreError("disk full")

    async def clear(self, key):
        raise SequenceStoreError("disk full")


class TestSequencePersistence:
    """Sequence numbers are read from and written to the configured store."""

    @pytest.mark.asyncio
    async def test_send_persists_outgoing_before_queueing(self):
        """The number is durable before the message can leave."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(_config(sequence_store=store))
        session.status = SessionStatus.LOGGED_ON

        # Act
        await session.send(_heartbeat())

        # Assert
        state = await store.load(KEY)
        assert state is not None
        assert state.outgoing == 1

    @pytest.mark.asyncio
    async def test_incoming_advance_is_persisted(self):
        """Accepted inbound traffic moves the stored baseline."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(_config(sequence_store=store))
        session.status = SessionStatus.LOGGED_ON

        # Act
        await session.receive(_heartbeat(seq=1).serialize())

        # Assert
        state = await store.load(KEY)
        assert state is not None
        assert state.incoming == 1

    @pytest.mark.asyncio
    async def test_connect_resumes_outgoing_from_the_store(self):
        """A restart continues the sequence instead of restarting at 1."""
        # Arrange: a previous session already sent one message
        store = InMemorySequenceStore()
        previous = FIXSession(_config(sequence_store=store))
        previous.status = SessionStatus.LOGGED_ON
        await previous.send(_heartbeat())

        # Act: a new session over the same store
        session = FIXSession(_config(sequence_store=store))
        await session.connect()

        # Assert: the Logon continues at 2
        logon = session._send_queue.get_nowait()
        assert logon.msg_type == MsgType.LOGON
        assert logon.sequence == 2

    @pytest.mark.asyncio
    async def test_connect_resumes_incoming_from_the_store(self):
        """The peer's next message is expected where we left off."""
        # Arrange
        store = InMemorySequenceStore()
        await store.save(
            SequenceState(
                sender_comp_id="CLIENT", target_comp_id="SERVER", incoming=5
            )
        )
        session = FIXSession(_config(sequence_store=store))

        # Act
        await session.connect()

        # Assert
        assert session.get_next_expected_seq_num() == 6

    @pytest.mark.asyncio
    async def test_reset_seq_num_ignores_persisted_numbers(self):
        """An explicit reset starts over even when the store says otherwise."""
        # Arrange
        store = InMemorySequenceStore()
        await store.save(
            SequenceState(
                sender_comp_id="CLIENT", target_comp_id="SERVER", outgoing=7
            )
        )
        session = FIXSession(_config(sequence_store=store, reset_seq_num=True))

        # Act
        await session.connect()

        # Assert: the Logon is 1, not 8, and that is what got persisted
        logon = session._send_queue.get_nowait()
        assert logon.sequence == 1
        assert (await store.load(KEY)).outgoing == 1

    @pytest.mark.asyncio
    async def test_initiator_logon_baseline_is_persisted(self):
        """The initiator records the baseline from the peer's Logon reply."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(_config(sequence_store=store))
        await session.connect()  # status WAITING_LOGON
        reply = FIXMessageFactory.create_logon("SERVER", "CLIENT", seq=5)

        # Act
        await session.receive(reply.serialize())

        # Assert
        state = await store.load(KEY)
        assert state is not None
        assert state.incoming == 5

    @pytest.mark.asyncio
    async def test_acceptor_restores_outgoing_before_replying(self):
        """Without this the server would reuse numbers the peer has seen."""
        # Arrange: state stored under the identity learned from the Logon
        store = InMemorySequenceStore()
        await store.save(
            SequenceState(
                sender_comp_id="SERVER", target_comp_id="CLIENT", outgoing=10
            )
        )
        session = FIXSession(
            SessionConfig(
                sender_comp_id="SERVER",
                target_comp_id="PLACEHOLDER",
                sequence_store=store,
            )
        )
        peer_logon = FIXMessageFactory.create_logon("CLIENT", "SERVER", seq=1)

        # Act
        await session.receive(peer_logon.serialize())

        # Assert: our Logon response continues at 11
        response = session._send_queue.get_nowait()
        assert response.msg_type == MsgType.LOGON
        assert response.sequence == 11

    @pytest.mark.asyncio
    async def test_discarding_pending_messages_persists_the_rewind(self):
        """A rewound number must not be handed out again after a restart."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(_config(sequence_store=store))
        session.status = SessionStatus.LOGGED_ON
        await session.send(_heartbeat())
        await session.send(_heartbeat())

        # Act
        await session.discard_pending_send()

        # Assert
        state = await store.load(KEY)
        assert state is not None
        assert state.outgoing == 0

    @pytest.mark.asyncio
    async def test_store_failure_prevents_queueing(self):
        """Write-ahead: if the number is not durable, the message is not sent."""
        # Arrange
        session = FIXSession(_config(sequence_store=_FailingStore()))
        session.status = SessionStatus.LOGGED_ON

        # Act & Assert
        with pytest.raises(SequenceStoreError):
            await session.send(_heartbeat())

        assert session.pending_send_count() == 0

    @pytest.mark.parametrize("gap_fill", [True, False])
    @pytest.mark.asyncio
    async def test_sequence_reset_is_persisted(self, gap_fill):
        """Both forms move the stored baseline, on their own paths."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(_config(sequence_store=store))
        session.status = SessionStatus.LOGGED_ON
        reset = FIXMessageFactory.create_sequence_reset(
            "SERVER", "CLIENT", seq=1, new_seq_no=10, gap_fill=gap_fill
        )

        # Act
        await session.receive(reset.serialize())

        # Assert
        state = await store.load(KEY)
        assert state is not None
        assert state.incoming == 9

    @pytest.mark.asyncio
    async def test_logon_baseline_is_persisted(self):
        """The accept path records the baseline it learns from the Logon."""
        # Arrange
        store = InMemorySequenceStore()
        session = FIXSession(
            SessionConfig(
                sender_comp_id="SERVER",
                target_comp_id="PLACEHOLDER",
                sequence_store=store,
            )
        )
        peer_logon = FIXMessageFactory.create_logon("CLIENT", "SERVER", seq=7)

        # Act
        await session.receive(peer_logon.serialize())

        # Assert
        state = await store.load(("SERVER", "CLIENT"))
        assert state is not None
        assert state.incoming == 7
