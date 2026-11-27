"""Credential redaction for log output.

Parser diagnostics log a prefix of the offending bytes so a malformed
message can be diagnosed. A malformed *Logon* can carry a password, so the
prefix is redacted before it reaches a logger.

Deliberately tag-based rather than message-based: the bytes may be
truncated or malformed, which is exactly when this runs, so it cannot rely
on the message parsing successfully.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from fixwire.core.constants import SOH
from fixwire.core.tags import Tags

# Username, password, new password, and opaque raw data. Everything else a
# FIX session carries is spec-public and useful for diagnosis.
_SENSITIVE = frozenset({
    Tags.USERNAME,
    Tags.PASSWORD,
    Tags.NEW_PASSWORD,
    Tags.RAW_DATA,
})

_REDACTED = "***"


def redact(data: bytes) -> bytes:
    """Replace the values of credential-bearing tags with ``***``.

    Works on a truncated message prefix: a field cut mid-value is still
    recognised by its tag and redacted.
    """
    if not data:
        return data

    fields = data.split(SOH.encode())
    redacted = []
    for field in fields:
        tag, separator, _ = field.partition(b"=")
        if separator and tag.isdigit() and int(tag) in _SENSITIVE:
            redacted.append(tag + b"=" + _REDACTED.encode())
        else:
            redacted.append(field)
    return SOH.encode().join(redacted)


def redact_url(url: str) -> str:
    """Strip credentials embedded in a URL.

    Connection URLs are logged so operators can see where a session went. A
    URL of the form ``wss://user:password@host`` would otherwise put the
    password in the log.
    """
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=host))
