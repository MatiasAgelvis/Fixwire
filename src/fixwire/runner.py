"""FIX Session Runner - Runs one FIXSession over one Transport.

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

# How often the heartbeat task wakes. It drives session.check_peer_liveness()
# (which decides internally whether anything is due) and also notices a
# session that has entered ERROR. Bounds both heartbeat responsiveness and
# ERROR teardown latency.
_HEARTBEAT_POLL = 1.0


class FIXSessionRunner:
    """Runs one FIXSession over one Transport.

    Owns the asyncio tasks that move bytes in and out. Strict error handling:
    any uncaught task exception puts the session in ERROR and closes the transport.

    Usage:
        runner = FIXSessionRunner(session, transport)
        await runner.connect()
        await runner.disconnect()
    """

    def __init__(self, session: FIXSession, transport: Transport) -> None:
        self._session = session
        self._transport = transport
        self._closed = False
        self._logged_on = False
        self._writer_task: asyncio.Task[None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_poll = _HEARTBEAT_POLL
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
            self._logged_on = True
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
        """Run session logout, wait for the response, stop tasks, close
        transport. Idempotent.

        The engine owns both handshake waits. ``session.disconnect()`` only
        queues the Logout and parks the session in WAITING_LOGOUT; this
        method applies ``session.config.logout_timeout`` and forces the
        session to DISCONNECTED if the peer never replies.
        """
        if self._closed:
            return
        self._closed = True

        await self._session.disconnect()
        await self._await_logout()
        await self.stop()
        await self._transport.close()

        logger.info("runner.disconnected",
                    sender=self._session.config.sender_comp_id,
                    target=self._session.config.target_comp_id)

    async def _await_logout(self) -> None:
        """Wait for the session to leave WAITING_LOGOUT, bounded by
        ``config.logout_timeout``. Forces DISCONNECTED on timeout.
        """
        try:
            await asyncio.wait_for(
                self._wait_for_status(SessionStatus.DISCONNECTED),
                timeout=self._session.config.logout_timeout,
            )
        except TimeoutError:
            logger.warning("runner.logout_timeout",
                           sender=self._session.config.sender_comp_id,
                           target=self._session.config.target_comp_id)
            self._session.status = SessionStatus.DISCONNECTED

    async def _wait_for_status(self, target: SessionStatus) -> None:
        """Poll until ``session.status`` reaches ``target``."""
        while self._session.status != target:
            await asyncio.sleep(0.01)

    # --- Internal task control ---

    async def start(self) -> None:
        """Spawn the I/O tasks. Idempotent."""
        if self._writer_task is not None:
            return
        self._stop_event.clear()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="fixwire-runner-writer"
        )
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="fixwire-runner-reader"
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="fixwire-runner-heartbeat"
        )

    async def stop(self) -> None:
        """Signal I/O tasks to stop and wait for them. Idempotent.

        The writer is woken by setting ``_stop_event`` but drains anything
        already queued before exiting, so a Logout queued just before
        teardown still reaches the peer. The reader is unblocked by its own
        bounded poll (``_IDLE_POLL``), so the transport stays open until
        the drain finishes.
        """
        if (
            self._writer_task is None
            and self._reader_task is None
            and self._heartbeat_task is None
        ):
            return
        self._stop_event.set()
        # Reader and heartbeat exit on their own polls; the writer drains
        # the queue. Only then do we cut the wire.
        await self._await_task(self._reader_task, timeout=1.0)
        await self._await_task(self._heartbeat_task, timeout=1.0)
        await self._await_task(self._writer_task, timeout=1.0)
        try:
            await self._transport.close()
        except Exception:
            pass
        self._writer_task = None
        self._reader_task = None
        self._heartbeat_task = None

    async def _await_task(
        self, task: asyncio.Task[None] | None, timeout: float
    ) -> None:
        """Await a task with a bound; cancel it if it overruns."""
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()

    async def wait_closed(self) -> None:
        """Block until the engine stops.

        Returns when the session ends (ERROR or peer logout) or when
        ``stop()`` / ``disconnect()`` is called. Used by callers that own
        a connection — for example ``FIXServer`` — to know when to clean up.
        """
        await self._stop_event.wait()

    async def _drain_and_close(self) -> None:
        """Drain queued outbound, then close the transport.

        Called from the heartbeat task, so it must never await itself — it
        awaits the writer (a different task) to flush, then closes.
        """
        self._stop_event.set()
        await self._await_task(self._writer_task, timeout=1.0)
        try:
            await self._transport.close()
        except Exception:
            pass

    async def _teardown_on_error(self) -> None:
        """Announce the failure, then drain and close."""
        logger.warning("runner.session_error",
                       sender=self._session.config.sender_comp_id,
                       target=self._session.config.target_comp_id)
        await self._drain_and_close()

    async def _teardown_on_logout(self) -> None:
        """Announce the clean logout, then drain and close."""
        logger.info("runner.logout_complete",
                    sender=self._session.config.sender_comp_id,
                    target=self._session.config.target_comp_id)
        await self._drain_and_close()

    # --- Writer task ---

    async def _writer_loop(self) -> None:
        """Drain session._send_queue, serialize, transport.send.

        Any exception other than cancellation logs, moves the session to
        ERROR, and closes the transport.
        """
        queue = self._session._send_queue
        while True:
            # Exit only when shutdown is signalled *and* nothing is queued,
            # so a Logout queued just before teardown still reaches the peer.
            if self._stop_event.is_set() and queue.empty():
                return
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

    async def _heartbeat_loop(self) -> None:
        """Drive heartbeat checks and react to the session ending.

        The session owns the heartbeat *decision* but no timers; this task
        supplies the tick. It also watches for the session leaving
        LOGGED_ON — ERROR (e.g. too-low sequence) or DISCONNECTED (peer
        initiated Logout) — and tears the engine down, since nothing else
        observes that transition once connected.

        Deliberately does not call ``stop()``: that would await this very
        task and deadlock. Setting ``_stop_event`` and closing the
        transport is enough — the sibling loops exit on their next poll.
        """
        while not self._stop_event.is_set():
            if self._session.status == SessionStatus.LOGGED_ON:
                self._logged_on = True

            await self._session.check_peer_liveness()
            await self._session.send_heartbeat_if_idle()

            if self._session.status == SessionStatus.ERROR:
                await self._teardown_on_error()
                return
            # A peer-initiated Logout parks the session in DISCONNECTED.
            # Only tear down if we had actually logged on, and not when an
            # explicit disconnect() is already handling it.
            if (
                self._session.status == SessionStatus.DISCONNECTED
                and self._logged_on
                and not self._closed
            ):
                await self._teardown_on_logout()
                return

            # Sleep until the next tick, but wake immediately on shutdown so
            # stop() is not delayed by a full poll interval.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._heartbeat_poll
                )
            except TimeoutError:
                pass

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
        logger.error("runner.task_error",
                     task=task_name,
                     error=str(error),
                     sender=self._session.config.sender_comp_id,
                     target=self._session.config.target_comp_id)
        self._session.status = SessionStatus.ERROR
        self._stop_event.set()
        try:
            await self._transport.close()
        except Exception as close_error:
            logger.warning("runner.close_after_error_failed",
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
