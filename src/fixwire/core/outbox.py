"""Outbound message store contract.

A sent message can be lost between taking a sequence number and reaching the
peer. When the peer asks for it, the only answer without a copy is a GapFill
— "that message never existed". The outbox keeps the bytes so a resend can be
a real replay instead.

Storage keeps the serialized message, not the ``FIXMessage`` object: a resend
must be re-emitted with ``PossDupFlag=Y`` and ``OrigSendingTime``, so it has
to be rebuilt rather than replayed byte-for-byte. Re-parsing the stored bytes
at resend time is cheaper than maintaining a second representation.
"""

from __future__ import annotations

from typing import Protocol

from fixwire.core.sequence import SessionKey

DEFAULT_MAX_MESSAGES = 10_000
"""How many outbound messages a store keeps before dropping the oldest."""


class OutboxError(RuntimeError):
    """Stored outbound messages could not be read, written, or trusted."""


class Outbox(Protocol):
    """Keeps outbound messages per session, indexed by MsgSeqNum.

    Implementations must not replay the wrong bytes: a corrupt record or a
    journal belonging to another session has to surface as ``OutboxError``.
    """

    async def append(self, key: SessionKey, seq: int, data: bytes) -> None:
        """Store ``data`` under ``seq`` for this session."""
        ...

    async def get_range(
        self, key: SessionKey, begin: int, end: int = 0
    ) -> list[bytes]:
        """Return stored messages with ``begin <= seq <= end``, oldest first.

        ``end=0`` means no upper bound, matching FIX's EndSeqNo convention.
        """
        ...

    async def prune(self, key: SessionKey, through: int) -> None:
        """Drop messages up to and including ``through``."""
        ...

    async def clear(self, key: SessionKey) -> None:
        """Forget every message for this session."""
        ...

    async def count(self, key: SessionKey) -> int:
        """Number of messages currently stored."""
        ...


class InMemoryOutbox:
    """Dict-backed outbox: no I/O, bounded by message count.

    The default. It exercises the same interface as a durable journal without
    touching disk, which is the right trade-off unless the process must
    survive a restart mid-resend.
    """

    def __init__(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        """Initialize the outbox.

        Args:
            max_messages: Keep at most this many messages, newest first.
        """
        self._max = max(1, max_messages)
        self._messages: dict[SessionKey, dict[int, bytes]] = {}

    async def append(self, key: SessionKey, seq: int, data: bytes) -> None:
        records = self._messages.setdefault(key, {})
        records[seq] = data
        while len(records) > self._max:
            del records[min(records)]

    async def get_range(
        self, key: SessionKey, begin: int, end: int = 0
    ) -> list[bytes]:
        records = self._messages.get(key, {})
        return [
            records[seq]
            for seq in sorted(records)
            if seq >= begin and (end == 0 or seq <= end)
        ]

    async def prune(self, key: SessionKey, through: int) -> None:
        records = self._messages.get(key)
        if not records:
            return
        for seq in [seq for seq in records if seq <= through]:
            del records[seq]

    async def clear(self, key: SessionKey) -> None:
        self._messages.pop(key, None)

    async def count(self, key: SessionKey) -> int:
        return len(self._messages.get(key, {}))
