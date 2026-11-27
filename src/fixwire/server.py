"""FIX Server - Overseer for concurrent client sessions.

Owns the lifecycle of one ``FIXSessionRunner`` per accepted connection: creates
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

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from fixwire.core.message import FIXMessage
from fixwire.core.session import FIXSession, SessionConfig
from fixwire.runner import FIXSessionRunner
from fixwire.transport import Transport

logger = structlog.get_logger()


@dataclass
class ServerConfig:
    """FIX Server Configuration."""
    max_sessions: int = 100
    # Refuse connections that are not TLS. On by default: a server a bank
    # installs should not accept orders over a plaintext socket. Test and
    # in-memory deployments opt out explicitly.
    require_tls: bool = True


class FIXServer:
    """Manages one FIXSessionRunner per accepted connection.

    The engine owns its own I/O tasks, heartbeat monitoring, and error
    teardown. This class owns only the *set* of engines: admission control,
    registration, and guaranteed cleanup.
    """

    def __init__(
        self,
        config_factory: Callable[[], SessionConfig],
        config: ServerConfig | None = None,
    ) -> None:
        """Initialize the server.

        Args:
            config_factory: Builds a fresh ``SessionConfig`` per session
                (each session needs its own state).
            config: Server-wide settings; defaults to ``ServerConfig()``.
        """
        self._config_factory = config_factory
        self.config = config if config is not None else ServerConfig()
        self._engines: set[FIXSessionRunner] = set()
        # Live identities, keyed by (peer SenderCompID, peer TargetCompID).
        self._sessions: dict[tuple[str, str], FIXSessionRunner] = {}
        # Reverse index so releasing a session is O(1) instead of scanning
        # every live identity.
        self._identity: dict[FIXSessionRunner, tuple[str, str]] = {}

    # --- Introspection ---

    @property
    def session_count(self) -> int:
        """Number of active sessions."""
        return len(self._engines)

    def sessions(self) -> list[FIXSessionRunner]:
        """Snapshot of the active engines."""
        return list(self._engines)

    # --- Lifecycle ---

    async def serve_connection(self, transport: Transport) -> None:
        """Adopt a connected transport as a session.

        Returns when the session ends, after tearing the engine down and
deregistering it. Over the cap, or unencrypted where TLS is required,
the transport is closed instead.
        """
        if self.config.require_tls and not transport.security.is_encrypted:
            logger.warning("server.plaintext_rejected",
                           security=transport.security.value)
            await transport.close()
            return

        if len(self._engines) >= self.config.max_sessions:
            logger.warning("server.max_sessions_reached",
                           max=self.config.max_sessions)
            await transport.close()
            return

        engine = FIXSessionRunner(FIXSession(self._config_factory()), transport)
        engine.session.on_logon_request(lambda msg: self._admit(msg, engine))
        self._engines.add(engine)
        try:
            await engine.accept()
            await engine.wait_closed()
        except Exception as e:
            logger.warning("server.session_failed",
                           error=str(e),
                           sender=engine.session.config.sender_comp_id,
                           target=engine.session.config.target_comp_id)
        finally:
            await engine.disconnect()
            self._engines.discard(engine)
            self._release(engine)

    def _admit(self, msg: FIXMessage, engine: FIXSessionRunner) -> bool:
        """Admission policy: one live session per identity.

        Returns False to reject a duplicate Logon; the session then sends
        a Logout and terminates.
        """
        identity = (msg.sender, msg.target)
        owner = self._sessions.get(identity)
        if owner is not None and owner is not engine:
            logger.warning("server.duplicate_logon",
                           sender=msg.sender,
                           target=msg.target)
            return False
        self._sessions[identity] = engine
        self._identity[engine] = identity
        return True

    def _release(self, engine: FIXSessionRunner) -> None:
        """Free the identity ``engine`` holds, if any."""
        identity = self._identity.pop(engine, None)
        if identity is not None and self._sessions.get(identity) is engine:
            del self._sessions[identity]

    async def stop(self, timeout: float | None = None) -> None:
        """Disconnect every active session, concurrently.

        Sessions are torn down in parallel: sequential disconnects would
        cost ``logout_timeout`` per session, so a busy server could take
        minutes to shut down.

        Args:
            timeout: Bound on the whole teardown. Sessions still running
                when it expires are cancelled; shutdown is already
                best-effort at that point.
        """
        engines = list(self._engines)
        if not engines:
            return

        teardown = asyncio.gather(
            *(engine.disconnect() for engine in engines),
            return_exceptions=True,
        )
        if timeout is None:
            await teardown
            return
        try:
            await asyncio.wait_for(teardown, timeout=timeout)
        except TimeoutError:
            logger.warning("server.stop_timeout",
                           timeout=timeout,
                           sessions=len(engines))
