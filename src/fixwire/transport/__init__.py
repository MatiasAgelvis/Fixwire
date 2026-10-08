"""FIX Transport Layer - Protocol and implementations.

Defines the transport interface and provides WebSocket/TCP implementations.
"""

from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    """Transport protocol for FIX messages.

    Any class implementing these methods can be used as a transport.
    No inheritance required — just implement the methods.

    Usage:
        class MyTransport:
            async def send(self, data: bytes) -> None: ...
            async def receive(self) -> bytes: ...

        session = FIXSession(config, transport=MyTransport())
    """

    async def send(self, data: bytes) -> None:
        """Send raw bytes to the remote endpoint.

        Args:
            data: Raw FIX message bytes.
        """
        ...

    async def receive(self) -> bytes:
        """Receive raw bytes from the remote endpoint.

        Returns:
            Raw FIX message bytes.
        """
        ...

    async def close(self) -> None:
        """Close the transport connection."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        ...
