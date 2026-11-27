"""TLS configuration for FIX over WSS.

Verification is on by default: a FIX session carries orders, so an
unverified peer is an unauthenticated peer. Opting out exists for test
environments and has to be written explicitly.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path


class TLSError(ValueError):
    """TLS configuration is incomplete or contradictory."""


@dataclass(frozen=True)
class TLSConfig:
    """TLS settings for one endpoint.

    Attributes:
        ca_file: Trust anchors. ``None`` uses the system store.
        cert_file: Certificate to present. Required for a server, and for a
            client only when the peer demands mutual TLS.
        key_file: Private key matching ``cert_file``.
        verify: Verify the peer's certificate. Never disable this outside a
            test environment.
        server_side: Build a server context instead of a client context.
        require_client_cert: Server only. Demand and verify a client
            certificate, which requires ``ca_file``.
    """

    ca_file: Path | None = None
    cert_file: Path | None = None
    key_file: Path | None = None
    verify: bool = True
    server_side: bool = False
    require_client_cert: bool = False


def build_ssl_context(config: TLSConfig) -> ssl.SSLContext:
    """Build an ``SSLContext`` from ``config``.

    Raises:
        TLSError: The configuration is incomplete, contradictory, or points
            at files that do not exist. Everything is checked here rather
            than at handshake time, so a misconfigured endpoint fails at
            startup.
    """
    _validate(config)

    if config.server_side:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(str(config.cert_file), str(config.key_file))
        if config.require_client_cert:
            context.load_verify_locations(cafile=str(config.ca_file))
            context.verify_mode = ssl.CERT_REQUIRED
    else:
        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=str(config.ca_file) if config.ca_file else None,
        )
        if config.cert_file and config.key_file:
            context.load_cert_chain(str(config.cert_file), str(config.key_file))

    if not config.verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    return context


def _validate(config: TLSConfig) -> None:
    """Check the configuration before touching the filesystem."""
    if config.cert_file and not config.key_file:
        raise TLSError("cert_file was given without key_file")
    if config.key_file and not config.cert_file:
        raise TLSError("key_file was given without cert_file")

    if config.server_side:
        if not (config.cert_file and config.key_file):
            raise TLSError(
                "server TLS requires cert_file and key_file: clients must "
                "be given a certificate"
            )
        if config.require_client_cert and not config.ca_file:
            raise TLSError(
                "require_client_cert needs ca_file: without trust anchors "
                "client certificates cannot be verified"
            )
        if config.require_client_cert and not config.verify:
            raise TLSError(
                "require_client_cert contradicts verify=False"
            )

    for name in ("ca_file", "cert_file", "key_file"):
        path = getattr(config, name)
        if path is not None and not Path(path).is_file():
            raise TLSError(f"{name} not found: {path}")
