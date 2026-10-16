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
        self._reader_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # --- Lifecycle ---

    async def connect(self) -> None:
        """Open transport, spawn I/O tasks, run session logon.

        Order of operations:
        1. ``await transport.connect()`` — open the wire.
        2. ``start()`` — spawn the writer and reader tasks.
        3. ``session.connect()`` — put a Logon on the queue.
        4. Wait for ``session.status == LOGGED_ON``, bounded by
           ``session.config.logon_timeout``.

        Idempotent: a second call is a no-op once the engine is running.

        Raises:
            ConnectionError: Transport could not be opened, or the logon
                handshake failed (e.g. malformed peer response, peer
                moved the session to ERROR).
            TimeoutError: The peer did not complete the logon handshake
                within ``session.config.logon_timeout``.
        """
        if self._writer_task is not None:
            return

        try:
            await self._transport.connect()
            await self.start()
            await self._session.connect()
            await asyncio.wait_for(
                self._wait_for_logon(),
                timeout=self._session.config.logon_timeout,
            )
        except TimeoutError as e:
            await self._teardown_after_failed_connect()
            raise TimeoutError(
                f"Logon handshake did not complete within "
                f"{self._session.config.logon_timeout}s"
            ) from e
        except Exception:
            await self._teardown_after_failed_connect()
            raise

    async def _wait_for_logon(self) -> None:
        """Poll until the session reaches LOGGED_ON or fails.

        Treats any non-LOGGED_ON terminal state (ERROR) as a failure so
        the caller surfaces a ConnectionError rather than waiting for the
        logon timeout to fire.
        """
        while self._session.status == SessionStatus.WAITING_LOGON:
            await asyncio.sleep(0.01)
        if self._session.status != SessionStatus.LOGGED_ON:
            raise ConnectionError(
                f"Logon handshake failed; session.status="
                f"{self._session.status.value}"
            )

    async def _teardown_after_failed_connect(self) -> None:
        """Tear down engine state after ``connect()`` fails. Idempotent."""
        await self.stop()

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
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="fixwire-engine-reader"
        )

    async def stop(self) -> None:
        """Signal I/O tasks to stop and wait for them. Idempotent.

        The writer is woken by setting ``_stop_event``; it finishes any
        message it already pulled, then returns. The reader is unblocked
        by closing the transport, which makes ``transport.receive()``
        raise — the reader's task guard sees ``_stop_event`` is set and
        exits cleanly without setting ERROR.
        """
        if self._writer_task is None and self._reader_task is None:
            return
        self._stop_event.set()
        # Close the transport so a reader blocked in receive() wakes up.
        try:
            await self._transport.close()
        except Exception:
            pass
        for task in (self._writer_task, self._reader_task):
            if task is None or task.done():
                continue
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._writer_task = None
        self._reader_task = None

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

    async def _reader_loop(self) -> None:
        """Drain transport.receive(), feed session.receive().

        Symmetric with the writer: the receive is bounded by ``_IDLE_POLL``
        so the reader can wake up and observe ``_stop_event`` without
        depending on the transport closing. Any exception other than the
        idle-poll timeout is routed through ``_handle_task_error``, which
        decides whether to escalate to ERROR or treat as clean shutdown.
        """
        while not self._stop_event.is_set():
            try:
                data = await asyncio.wait_for(
                    self._transport.receive(),
                    timeout=_IDLE_POLL,
                )
                await self._session.receive(data)
            except TimeoutError:
                continue
            except Exception as e:
                await self._handle_task_error("reader", e)
                return

    async def _handle_task_error(self, task_name: str, error: Exception) -> None:
        """Mark the session as ERROR, signal shutdown, and close the
        transport. Does NOT await the failing task — that would
        self-deadlock when called from inside the failing task. The outer
        caller (``connect()`` / ``stop()`` / ``disconnect()``) is
        responsible for awaiting the tasks.

        If the engine is already shutting down (``_stop_event`` is set),
        the error is expected — typically the transport closing under us
        — and we exit without escalating to ERROR.
        """
        if self._stop_event.is_set():
            # Clean shutdown: the error is the transport closing under us.
            return
        logger.error("engine.task_error",
                     task=task_name,
                     error=str(error),
                     sender=self._session.config.sender_comp_id,
                     target=self._session.config.target_comp_id)
        self._session.status = SessionStatus.ERROR
        self._stop_event.set()
        try:
            await self._transport.close()
        except Exception as close_error:
            logger.warning("engine.close_after_error_failed",
                           error=str(close_error))

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
