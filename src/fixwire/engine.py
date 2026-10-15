"""FIX Engine - Coordinates a FIXSession with a Transport.

Middle layer between the pure protocol state machine (fixwire.core) and
raw bytes I/O (fixwire.transport). Owns the asyncio tasks that move bytes
in and out. Strict error handling: any uncaught task exception puts the
session in ERROR and closes the transport.
"""

from __future__ import annotations

import asyncio

import structlog

from fixwire.core.session import FIXSession, SessionStatus
from fixwire.transport import Transport

logger = structlog.get_logger()


# How long the writer sleeps when the session queue is empty before
# checking the stop event again. Small enough to feel snappy in tests,
# large enough not to burn CPU in idle sessions.
_IDLE_POLL = 0.05


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
        self._writer_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # --- Lifecycle ---

    async def connect(self) -> None:
        """Open transport, spawn I/O tasks, run session logon."""
        raise NotImplementedError

    async def disconnect(self) -> None:
        """Run session logout, stop tasks, close transport. Idempotent."""
        if self._closed:
            return
        self._closed = True

        await self._session.disconnect()
        await self.stop()
        await self._transport.close()

        logger.info("engine.disconnected",
                    sender=self._session.config.sender_comp_id,
                    target=self._session.config.target_comp_id)

    # --- Internal task control ---

    async def start(self) -> None:
        """Spawn the I/O tasks. Idempotent."""
        if self._writer_task is not None:
            return
        self._stop_event.clear()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="fixwire-engine-writer"
        )

    async def stop(self) -> None:
        """Signal I/O tasks to stop and wait for them. Idempotent.

        The writer is woken by setting _stop_event; it finishes any
        message it already pulled, then returns.
        """
        if self._writer_task is None:
            return
        self._stop_event.set()
        try:
            await self._writer_task
        except asyncio.CancelledError:
            pass
        self._writer_task = None

    # --- Writer task ---

    async def _writer_loop(self) -> None:
        """Drain session._send_queue, serialize, transport.send.

        Any exception other than cancellation logs, moves the session to
        ERROR, and closes the transport.
        """
        queue = self._session._send_queue
        while not self._stop_event.is_set():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=_IDLE_POLL)
            except TimeoutError:
                continue
            try:
                data = msg.serialize()
                await self._safe_send(data)
            except Exception as e:
                await self._handle_task_error("writer", e)
                return

    async def _safe_send(self, data: bytes) -> None:
        """Send bytes; raise only on real transport failure."""
        try:
            await self._transport.send(data)
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"transport.send failed: {e}") from e

    async def _handle_task_error(self, task_name: str, error: Exception) -> None:
        """Move the session to ERROR, close the transport,
        and signal the engine to stop.
        """
        logger.error("engine.task_error",
                     task=task_name,
                     error=str(error),
                     sender=self._session.config.sender_comp_id,
                     target=self._session.config.target_comp_id)
        self._session.status = SessionStatus.ERROR
        try:
            await self._transport.close()
        except Exception as close_error:
            logger.warning("engine.close_after_error_failed",
                           error=str(close_error))
        # Signal sibling tasks (and the reader, when slice 4 lands) to stop.
        # stop() is idempotent and a no-op if no tasks are running.
        await self.stop()

    async def reconnect(self) -> None:
        """Reconnect with backoff."""
        raise NotImplementedError

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
