"""Filename derivation shared by the file-backed stores."""

from __future__ import annotations

from fixwire.core.sequence import SessionKey


def session_filename(key: SessionKey, suffix: str) -> str:
    """Turn a session identity into a safe filename component.

    Only alphanumerics, ``-``, ``_`` and ``.`` survive; everything else
    becomes ``_``. That is lossy on purpose: file stores stamp the identity
    next to the data and reject a mismatch instead of trusting the name, so
    two identities colliding here fails loudly rather than sharing storage.
    """
    raw = f"{key[0]}--{key[1]}"
    safe = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in raw
    )
    return f"{safe}{suffix}"
