"""In-memory transport for tests, harnesses, and debugging.

Implements the Transport Protocol without touching the network: outbound
bytes are recorded, inbound bytes are injected by the caller. Serves M1
engine tests, M2 chaos scenarios, and M6 conformance runs, where
deterministic, socket-free execution is required.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fixwire.transport import Transport


class InMemoryTransport:
    """In-memory Transport: records sends, receives injected bytes.

    Usage:
        transport = InMemoryTransport()
        await transport.send(b"...")  # recorded in transport.sent
        transport.feed(b"...")        # next receive() returns it
    """

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.close_count = 0
        self._connected = True
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()

    def feed(self, data: bytes) -> None:
        """Deliver inbound bytes as if they arrived from the wire."""
        self._incoming.put_nowait(data)

    async def connect(self) -> None:
        """No-op: the in-memory transport is always connected on creation.

        Exists to satisfy the ``Transport`` protocol. Re-asserts
        ``_connected = True`` so a previously-closed transport can be
        "reconnected" between tests by calling ``connect()`` again.
        """
        self._connected = True

    async def send(self, data: bytes) -> None:
        """Record outbound bytes.

        Args:
            data: Raw FIX message bytes.
        """
        if not self._connected:
            raise ConnectionError("transport is closed")
        self.sent.append(data)

    async def receive(self) -> bytes:
        """Return the next injected bytes, blocking until available.

        Returns:
            Raw FIX message bytes.
        """
        if not self._connected:
            raise ConnectionError("transport is closed")
        return await self._incoming.get()

    async def close(self) -> None:
        """Close the transport. Idempotent; every call is counted."""
        self.close_count += 1
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected


# Type-level proof that InMemoryTransport satisfies the Transport Protocol.
if TYPE_CHECKING:
    _transport_conformance: Transport = InMemoryTransport()
