"""FIX Engine - Coordinates a FIXSession with a Transport.

Middle layer between the pure protocol state machine (fixwire.core) and
raw bytes I/O (fixwire.transport). Owns the asyncio tasks that move bytes
in and out. Strict error handling: any uncaught task exception puts the
session in ERROR and closes the transport.
"""

from __future__ import annotations

import structlog

from fixwire.core.session import FIXSession, SessionStatus
from fixwire.transport import Transport

logger = structlog.get_logger()


class FIXEngine:
    """Coordinates a FIXSession with a Transport.

    Owns the asyncio tasks that move bytes in and out. Strict error handling:
    any uncaught task exception puts the session in ERROR and closes the transport.

    Usage:
        engine = FIXEngine(session, transport)
        await engine.connect()
        await engine.disconnect()
    """

    def __init__(self, session: FIXSession, transport: Transport) -> None:
        self._session = session
        self._transport = transport
        self._closed = False

    # --- Lifecycle ---

    async def connect(self) -> None:
        """Open transport, spawn I/O tasks, run session logon."""
        raise NotImplementedError(
            "FIXEngine.connect() is wired in the M1 lifecycle slice."
        )

    async def disconnect(self) -> None:
        """Run session logout, stop tasks, close transport. Idempotent."""
        if self._closed:
            return
        self._closed = True

        await self._session.disconnect()
        # I/O tasks are cancelled here once the reader/writer slices land.
        await self._transport.close()

        logger.info("engine.disconnected",
                    sender=self._session.config.sender_comp_id,
                    target=self._session.config.target_comp_id)

    async def reconnect(self) -> None:
        """Reconnect with backoff. Wired in M3."""
        raise NotImplementedError("FIXEngine.reconnect() is wired in M3.")

    # --- Introspection ---

    @property
    def status(self) -> SessionStatus:
        """Delegates to session.status."""
        return self._session.status

    @property
    def is_connected(self) -> bool:
        """Delegates to session.is_connected."""
        return self._session.is_connected

    @property
    def session(self) -> FIXSession:
        """The coordinated session."""
        return self._session

    @property
    def transport(self) -> Transport:
        """The coordinated transport."""
        return self._transport
