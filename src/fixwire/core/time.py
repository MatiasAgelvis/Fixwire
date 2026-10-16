"""Time helpers - single source of truth for current time."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Replaces ``datetime.utcnow()`` (deprecated since Python 3.12) with the
    modern ``datetime.now(UTC)`` API. Use this anywhere the codebase needs
    "now" so there is one place to swap in a clock for tests if needed.
    """
    return datetime.now(UTC)