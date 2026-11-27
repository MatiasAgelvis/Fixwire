"""Security posture reported by a transport.

Configuration is a connection concern (each transport's constructor takes a
``TLSConfig``). Posture is a *contract* concern: a server that must refuse
plaintext, or an audit that records how a counterparty connected, needs to
ask the transport what actually happened rather than be told.
"""

from __future__ import annotations

from enum import StrEnum


class TransportSecurity(StrEnum):
    """How bytes on this transport are protected."""

    PLAINTEXT = "plaintext"
    """Unencrypted, whether over TCP or WebSocket."""

    TLS = "tls"
    """Encrypted; the handshake completed with a peer certificate."""

    IN_MEMORY = "in_memory"
    """No wire at all. Never a substitute for TLS: it makes no claim."""

    @property
    def is_encrypted(self) -> bool:
        """True only when traffic is actually protected by TLS."""
        return self is TransportSecurity.TLS
