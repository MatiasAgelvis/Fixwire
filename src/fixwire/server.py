"""FIX Server - Overseer for concurrent client sessions.

Owns the lifecycle of one ``FIXEngine`` per accepted connection: creates
the session, registers it, and guarantees teardown when the connection
ends.

Deliberately transport-agnostic: it adopts any connected ``Transport``
and knows nothing about sockets. Wiring a concrete listener belongs to
the application (or a thin adapter module), for example:

    fix_server = FIXServer(config_factory)

    ws_server = WebSocketServer(host, port)
    ws_server.on_connection(
        lambda conn: fix_server.serve_connection(
            WebSocketTransportAdapter(conn)
        )
    )
    await ws_server.start()
    ...
    await ws_server.stop()
    await fix_server.stop()
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from fixwire.core.session import FIXSession, SessionConfig
from fixwire.engine import FIXEngine
from fixwire.transport import Transport

logger = structlog.get_logger()


class FIXServer:
    """Manages one FIXEngine per accepted connection.

    The engine owns its own I/O tasks, heartbeat monitoring, and error
    teardown. This class owns only the *set* of engines: admission control,
    registration, and guaranteed cleanup.
    """

    def __init__(
        self,
        config_factory: Callable[[], SessionConfig],
        max_sessions: int = 100,
    ) -> None:
        """Initialize the server.

        Args:
            config_factory: Builds a fresh ``SessionConfig`` per session
                (each session needs its own state).
            max_sessions: Maximum concurrent sessions; further connections
                are closed on arrival.
        """
        self._config_factory = config_factory
        self._max_sessions = max_sessions
        self._engines: set[FIXEngine] = set()

    # --- Introspection ---

    @property
    def session_count(self) -> int:
        """Number of active sessions."""
        return len(self._engines)

    def sessions(self) -> list[FIXEngine]:
        """Snapshot of the active engines."""
        return list(self._engines)

    # --- Lifecycle ---

    async def serve_connection(self, transport: Transport) -> None:
        """Adopt a connected transport as a session.

        Returns when the session ends, after tearing the engine down and
        deregistering it. Over the cap, the transport is closed instead.
        """
        if len(self._engines) >= self._max_sessions:
            logger.warning("server.max_sessions_reached",
                           max=self._max_sessions)
            await transport.close()
            return

        engine = FIXEngine(FIXSession(self._config_factory()), transport)
        self._engines.add(engine)
        try:
            await engine.connect()
            await engine.wait_closed()
        except Exception as e:
            logger.warning("server.session_failed",
                           error=str(e),
                           sender=engine.session.config.sender_comp_id,
                           target=engine.session.config.target_comp_id)
        finally:
            await engine.disconnect()
            self._engines.discard(engine)

    async def stop(self) -> None:
        """Disconnect every active session."""
        for engine in list(self._engines):
            await engine.disconnect()
