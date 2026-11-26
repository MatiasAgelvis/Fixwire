"""Tests for the SequenceStore contract and the in-memory implementation."""

from dataclasses import FrozenInstanceError

import pytest

from fixwire.core.sequence import (
    InMemorySequenceStore,
    SequenceState,
    SequenceStore,
)


def _state(
    outgoing: int = 0,
    incoming: int = 0,
    sender: str = "CLIENT",
    target: str = "SERVER",
) -> SequenceState:
    return SequenceState(
        sender_comp_id=sender,
        target_comp_id=target,
        outgoing=outgoing,
        incoming=incoming,
    )


class TestSequenceState:
    """The persisted record itself."""

    def test_defaults_to_zero(self):
        """A fresh session starts at zero on both directions."""
        # Arrange & Act
        state = SequenceState(sender_comp_id="A", target_comp_id="B")

        # Assert
        assert state.outgoing == 0
        assert state.incoming == 0

    def test_key_is_the_identity_pair(self):
        """Sessions are identified by (our sender, peer)."""
        # Arrange & Act
        state = _state(sender="CLIENT", target="SERVER")

        # Assert
        assert state.key == ("CLIENT", "SERVER")

    def test_is_immutable(self):
        """States are values; mutation would bypass persistence."""
        # Arrange
        state = _state()

        # Act & Assert
        with pytest.raises(FrozenInstanceError):
            state.outgoing = 5  # type: ignore[misc]


class TestInMemorySequenceStore:
    """Dict-backed store used as the default."""

    def test_protocol_satisfied(self):
        """The in-memory store satisfies the SequenceStore protocol."""
        # Act
        store: SequenceStore = InMemorySequenceStore()

        # Assert
        assert store is not None

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self):
        """An unknown session has no stored state."""
        # Arrange
        store = InMemorySequenceStore()

        # Act
        state = await store.load(("CLIENT", "SERVER"))

        # Assert
        assert state is None

    @pytest.mark.asyncio
    async def test_round_trip(self):
        """What is saved comes back unchanged."""
        # Arrange
        store = InMemorySequenceStore()
        saved = _state(outgoing=7, incoming=3)

        # Act
        await store.save(saved)

        # Assert
        assert await store.load(("CLIENT", "SERVER")) == saved

    @pytest.mark.asyncio
    async def test_save_replaces_previous_state(self):
        """The latest save wins."""
        # Arrange
        store = InMemorySequenceStore()
        await store.save(_state(outgoing=1))

        # Act
        await store.save(_state(outgoing=9))

        # Assert
        assert (await store.load(("CLIENT", "SERVER"))).outgoing == 9

    @pytest.mark.asyncio
    async def test_keys_are_isolated(self):
        """One session's numbers never leak into another's."""
        # Arrange
        store = InMemorySequenceStore()
        await store.save(_state(outgoing=5, sender="A", target="R"))
        await store.save(_state(outgoing=8, sender="B", target="R"))

        # Act & Assert
        assert (await store.load(("A", "R"))).outgoing == 5
        assert (await store.load(("B", "R"))).outgoing == 8

    @pytest.mark.asyncio
    async def test_clear_removes_the_session(self):
        """After clear the session looks new again."""
        # Arrange
        store = InMemorySequenceStore()
        await store.save(_state(outgoing=5))

        # Act
        await store.clear(("CLIENT", "SERVER"))

        # Assert
        assert await store.load(("CLIENT", "SERVER")) is None

    @pytest.mark.asyncio
    async def test_clear_missing_key_is_a_noop(self):
        """Clearing an unknown session is harmless."""
        # Arrange
        store = InMemorySequenceStore()

        # Act
        await store.clear(("CLIENT", "SERVER"))

        # Assert
        assert await store.load(("CLIENT", "SERVER")) is None
