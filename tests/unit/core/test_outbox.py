"""Tests for the Outbox contract and the in-memory implementation.

The outbox keeps the messages we have sent so a peer's ResendRequest can be
answered with real replays instead of a GapFill that pretends the message
never existed.
"""

import pytest

from fixwire.core.outbox import InMemoryOutbox, Outbox

KEY = ("CLIENT", "SERVER")


class TestInMemoryOutbox:
    """Dict-backed outbox, used as the default."""

    def test_protocol_satisfied(self):
        """The in-memory outbox satisfies the Outbox protocol."""
        # Act
        outbox: Outbox = InMemoryOutbox()

        # Assert
        assert outbox is not None

    @pytest.mark.asyncio
    async def test_append_then_read_back(self):
        """Stored bytes come back exactly as they went in."""
        # Arrange
        outbox = InMemoryOutbox()
        payload = b"8=FIX.4.4\x019=5\x0135=0\x0110=000\x01"

        # Act
        await outbox.append(KEY, 1, payload)

        # Assert
        assert await outbox.get_range(KEY, 1, 1) == [payload]

    @pytest.mark.asyncio
    async def test_range_is_inclusive_and_ordered(self):
        """Bounds are inclusive on both ends, oldest first."""
        # Arrange
        outbox = InMemoryOutbox()
        for seq in (1, 2, 3, 4, 5):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        result = await outbox.get_range(KEY, 2, 4)

        # Assert
        assert result == [b"m2", b"m3", b"m4"]

    @pytest.mark.asyncio
    async def test_end_zero_means_no_upper_bound(self):
        """FIX uses EndSeqNo=0 for 'everything from here on'."""
        # Arrange
        outbox = InMemoryOutbox()
        for seq in (1, 2, 3):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        result = await outbox.get_range(KEY, 2, 0)

        # Assert
        assert result == [b"m2", b"m3"]

    @pytest.mark.asyncio
    async def test_unknown_session_returns_nothing(self):
        """An unknown session has no stored messages."""
        # Arrange
        outbox = InMemoryOutbox()

        # Act & Assert
        assert await outbox.get_range(KEY, 1, 10) == []
        assert await outbox.count(KEY) == 0

    @pytest.mark.asyncio
    async def test_empty_range_returns_nothing(self):
        """A range with no matching messages is empty, not an error."""
        # Arrange
        outbox = InMemoryOutbox()
        await outbox.append(KEY, 1, b"m1")

        # Act & Assert
        assert await outbox.get_range(KEY, 5, 9) == []

    @pytest.mark.asyncio
    async def test_prune_drops_through_seq(self):
        """Pruning removes everything up to and including the watermark."""
        # Arrange
        outbox = InMemoryOutbox()
        for seq in (1, 2, 3, 4):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        await outbox.prune(KEY, 2)

        # Assert
        assert await outbox.get_range(KEY, 1, 10) == [b"m3", b"m4"]
        assert await outbox.count(KEY) == 2

    @pytest.mark.asyncio
    async def test_clear_forgets_the_session(self):
        """Clear removes every message for the session."""
        # Arrange
        outbox = InMemoryOutbox()
        await outbox.append(KEY, 1, b"m1")

        # Act
        await outbox.clear(KEY)

        # Assert
        assert await outbox.count(KEY) == 0

    @pytest.mark.asyncio
    async def test_sessions_are_isolated(self):
        """One session's messages never leak into another's."""
        # Arrange
        outbox = InMemoryOutbox()
        await outbox.append(("A", "R"), 1, b"a1")
        await outbox.append(("B", "R"), 1, b"b1")

        # Act & Assert
        assert await outbox.get_range(("A", "R"), 1, 1) == [b"a1"]
        assert await outbox.get_range(("B", "R"), 1, 1) == [b"b1"]

    @pytest.mark.asyncio
    async def test_oldest_are_dropped_beyond_the_bound(self):
        """The outbox is bounded: resend beyond the window degrades to GapFill."""
        # Arrange: room for four messages
        outbox = InMemoryOutbox(max_messages=4)

        # Act: append six
        for seq in range(1, 7):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Assert: the newest survive, the oldest are gone
        stored = await outbox.get_range(KEY, 1, 0)
        assert b"m6" in stored
        assert b"m1" not in stored
        assert await outbox.count(KEY) <= 4

    @pytest.mark.asyncio
    async def test_truncate_drops_newer_records(self):
        """Discarding unsent messages removes them from the outbox."""
        # Arrange
        outbox = InMemoryOutbox()
        for seq in (1, 2, 3, 4):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        await outbox.truncate(KEY, 2)

        # Assert
        assert await outbox.get_range(KEY, 1, 10) == [b"m1", b"m2"]
        assert await outbox.count(KEY) == 2
