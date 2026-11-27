"""Tests for graceful signal-driven shutdown."""

import asyncio
import signal

import pytest

from fixwire.shutdown import GracefulShutdown


class _Recorder:
    """Builds stop callbacks that record when they ran."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self, name: str, *, delay: float = 0, fail: bool = False):
        async def run() -> None:
            self.calls.append(name)
            if delay:
                await asyncio.sleep(delay)
            if fail:
                raise RuntimeError(f"{name} exploded")

        return run


class _FakeLoop:
    """Captures handler registration and delegates task creation."""

    def __init__(self) -> None:
        self.registered: dict[int, tuple] = {}

    def add_signal_handler(self, sig, callback, *args) -> None:
        self.registered[sig] = (callback, args)

    def create_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)


class TestGracefulShutdown:
    """Stops run in order, and one stuck step cannot block the others."""

    @pytest.mark.asyncio
    async def test_stops_run_in_the_order_given(self):
        """The order matters: stop listening before disconnecting."""
        # Arrange
        recorder = _Recorder()
        shutdown = GracefulShutdown(
            recorder.stop("listener"), recorder.stop("sessions")
        )

        # Act
        await shutdown.shutdown()

        # Assert
        assert recorder.calls == ["listener", "sessions"]

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self):
        """A second call does not repeat the work."""
        # Arrange
        recorder = _Recorder()
        shutdown = GracefulShutdown(recorder.stop("sessions"))

        # Act
        await shutdown.shutdown()
        await shutdown.shutdown()

        # Assert
        assert recorder.calls == ["sessions"]

    @pytest.mark.asyncio
    async def test_a_failing_step_does_not_block_the_rest(self):
        """One broken teardown must not strand the others."""
        # Arrange
        recorder = _Recorder()
        shutdown = GracefulShutdown(
            recorder.stop("broken", fail=True), recorder.stop("sessions")
        )

        # Act
        await shutdown.shutdown()

        # Assert
        assert recorder.calls == ["broken", "sessions"]

    @pytest.mark.asyncio
    async def test_a_slow_step_times_out_and_the_rest_still_run(self):
        """The bound is per step, so shutdown finishes."""
        # Arrange
        recorder = _Recorder()
        shutdown = GracefulShutdown(
            recorder.stop("stuck", delay=5.0),
            recorder.stop("sessions"),
            timeout=0.05,
        )

        # Act
        await asyncio.wait_for(shutdown.shutdown(), timeout=1.0)

        # Assert
        assert recorder.calls == ["stuck", "sessions"]

    @pytest.mark.asyncio
    async def test_install_registers_sigterm_and_sigint(self):
        """Both signals are handled, and the handler runs the stops."""
        # Arrange
        loop = _FakeLoop()
        recorder = _Recorder()
        shutdown = GracefulShutdown(recorder.stop("sessions"))

        # Act
        shutdown.install(loop)
        callback, args = loop.registered[signal.SIGTERM]
        callback(*args)
        await shutdown.task

        # Assert
        assert set(loop.registered) == {signal.SIGTERM, signal.SIGINT}
        assert recorder.calls == ["sessions"]

    @pytest.mark.asyncio
    async def test_a_second_signal_does_not_start_another_shutdown(self):
        """Repeated signals are logged, not acted on."""
        # Arrange
        loop = _FakeLoop()
        recorder = _Recorder()
        gate = asyncio.Event()

        async def blocking() -> None:
            recorder.calls.append("sessions")
            await gate.wait()

        shutdown = GracefulShutdown(blocking)
        shutdown.install(loop)
        callback, args = loop.registered[signal.SIGTERM]

        # Act: two signals while the first shutdown is still running
        callback(*args)
        callback(*args)
        gate.set()
        await shutdown.task

        # Assert
        assert recorder.calls == ["sessions"]
