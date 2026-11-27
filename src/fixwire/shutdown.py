"""Graceful shutdown on process signals.

A FIX session should say goodbye before the process dies: the peer expects a
Logout, and cutting the socket leaves it guessing whether the session is
alive. This module wires SIGTERM and SIGINT to an ordered list of stop
callbacks so an application can flush and close instead of being killed
mid-session.

The library does not install handlers on import — an application opts in:

    shutdown = GracefulShutdown(ws_server.stop, fix_server.stop)
    shutdown.install()
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger()

StopCallback = Callable[[], Awaitable[None]]


class GracefulShutdown:
    """Runs stop callbacks in order when the process is asked to terminate.

    Callbacks run **sequentially**, in the order given: typically "stop the
    listener" first, then "disconnect the sessions", so the process stops
    accepting new work before tearing down existing work.

    Each step gets its own ``timeout``. A step that fails or times out is
    logged and the remaining steps still run — one stuck session must not
    prevent the others from logging out.
    """

    def __init__(
        self,
        *stops: StopCallback,
        signals: tuple[int, ...] = (signal.SIGTERM, signal.SIGINT),
        timeout: float | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            *stops: Teardown callbacks, run in the order given.
            signals: Signals to handle. Defaults to SIGTERM and SIGINT.
            timeout: Per-step bound in seconds, or None to wait indefinitely.
        """
        self._stops = stops
        self._signals = signals
        self._timeout = timeout
        self._task: asyncio.Task[None] | None = None
        self._finished = False

    def install(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Register the signal handlers on ``loop``.

        Must run on the loop's own thread. Handlers stay installed until the
        loop closes; there is no ``uninstall`` because a process that
        handled a termination signal has nothing left to restore.
        """
        target = loop if loop is not None else asyncio.get_running_loop()
        for sig in self._signals:
            target.add_signal_handler(sig, self._on_signal, target)

    @property
    def task(self) -> asyncio.Task[None] | None:
        """The in-flight shutdown task, once a signal has arrived."""
        return self._task

    async def shutdown(self) -> None:
        """Run every stop callback once, in order.

        Idempotent: a second call, or a re-delivered signal, does nothing.
        """
        if self._finished:
            return
        self._finished = True

        logger.info("shutdown.started", steps=len(self._stops))
        for stop in self._stops:
            name = getattr(stop, "__qualname__", repr(stop))
            try:
                if self._timeout is None:
                    await stop()
                else:
                    await asyncio.wait_for(stop(), timeout=self._timeout)
            except TimeoutError:
                logger.warning("shutdown.step_timeout",
                               step=name,
                               timeout=self._timeout)
            except Exception as exc:
                logger.error("shutdown.step_failed",
                             step=name,
                             error=str(exc))
        logger.info("shutdown.complete")

    def _on_signal(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule the shutdown; repeated signals are ignored.

        Kept synchronous: a signal handler must not await.
        """
        if self._finished or (self._task is not None and not self._task.done()):
            logger.warning("shutdown.already_running")
            return
        self._task = loop.create_task(self.shutdown())
