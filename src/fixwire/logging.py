"""structlog configuration for FIXwire's audit events.

The library emits events but does not decide where they go. An application
configures rendering once at startup; see ``docs/AUDIT_LOGGING.md`` for the
event taxonomy and level meanings.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, level: int = logging.INFO, json: bool = False) -> None:
    """Configure structlog to render FIXwire's events consistently.

    Safe to call more than once; later calls replace the configuration.

    Args:
        level: Minimum level to emit, as a ``logging`` constant. ``DEBUG``
            carries per-message traces and scales with traffic, so it is
            normally a deliberate, time-boxed setting.
        json: Render one JSON object per line. Use it when shipping to a
            collector; the console renderer is for humans reading a
            terminal.
    """
    renderer = (
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
