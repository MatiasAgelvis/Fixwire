"""Sequence number persistence contract.

Session sequence numbers must survive a restart: FIX requires continuity,
and reusing a number the peer has already seen corrupts the session. This
module defines the seam that makes that possible without the session
knowing anything about files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SessionKey = tuple[str, str]
"""Identifies a session as (our SenderCompID, peer's SenderCompID)."""


class SequenceStoreError(RuntimeError):
    """Stored sequence state could not be read, written, or trusted."""


@dataclass(frozen=True)
class SequenceState:
    """Sequence numbers persisted for one session.

    Frozen: a state is a value handed to the store. Mutating the live
    numbers happens in the session, which then saves a new state.
    """

    sender_comp_id: str
    target_comp_id: str
    outgoing: int = 0
    incoming: int = 0

    @property
    def key(self) -> SessionKey:
        """The identity this state belongs to."""
        return (self.sender_comp_id, self.target_comp_id)


class SequenceStore(Protocol):
    """Persists per-session sequence numbers.

    Implementations must not lose a successfully saved state, and must not
    invent one: a corrupt or foreign record has to surface as
    ``SequenceStoreError`` rather than as a silent reset, because a silent
    reset reuses sequence numbers the peer has already seen.
    """

    async def load(self, key: SessionKey) -> SequenceState | None:
        """Return the stored state, or None when the session is new."""
        ...

    async def save(self, state: SequenceState) -> None:
        """Persist ``state``, replacing whatever was stored before."""
        ...

    async def clear(self, key: SessionKey) -> None:
        """Forget the session, e.g. after the peer resets its sequence."""
        ...


class InMemorySequenceStore:
    """Dict-backed store: no I/O, and a new instance is a new session.

    This is the default. It exercises the same code path as a durable store
    without touching disk, so tests and short-lived sessions need no
    configuration, while a restart legitimately starts from zero.
    """

    def __init__(self) -> None:
        self._states: dict[SessionKey, SequenceState] = {}

    async def load(self, key: SessionKey) -> SequenceState | None:
        return self._states.get(key)

    async def save(self, state: SequenceState) -> None:
        self._states[state.key] = state

    async def clear(self, key: SessionKey) -> None:
        self._states.pop(key, None)
