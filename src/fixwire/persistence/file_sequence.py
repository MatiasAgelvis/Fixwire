"""File-backed SequenceStore: one JSON file per session.

Writes are atomic — payload to a temporary file in the same directory, then
renamed over the target — so a crash mid-write leaves either the old file
or the new one, never a partial one.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fixwire.core.sequence import SequenceState, SequenceStoreError, SessionKey
from fixwire.persistence._paths import session_filename


class FileSequenceStore:
    """Stores each session's sequence numbers as its own JSON file.

    ``fsync`` is off by default: without it a save survives a process crash
    (the bytes are in the page cache and the rename is atomic) but not
    necessarily a power loss. Enable it when machine durability matters more
    than the extra millisecond per save.

    I/O is synchronous. Payloads are tiny, and the caller must not send a
    message before its sequence number is durable — handing the write to
    another thread would give that up. If write latency ever shows up in a
    profile, this is the place to revisit.
    """

    def __init__(self, directory: Path | str, *, fsync: bool = False) -> None:
        """Initialize the store.

        Args:
            directory: Where sequence files live. Created on first save.
            fsync: Flush file and directory to disk on every save.
        """
        self._directory = Path(directory)
        self._fsync = fsync

    async def load(self, key: SessionKey) -> SequenceState | None:
        path = self._path(key)
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SequenceStoreError(f"Cannot read {path}: {exc}") from exc

        try:
            data = json.loads(payload)
            state = SequenceState(
                sender_comp_id=data["sender_comp_id"],
                target_comp_id=data["target_comp_id"],
                outgoing=int(data["outgoing"]),
                incoming=int(data["incoming"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise SequenceStoreError(f"Corrupt sequence file {path}: {exc}") from exc

        if state.key != key:
            raise SequenceStoreError(
                f"{path} holds {state.sender_comp_id!r} -> "
                f"{state.target_comp_id!r}, expected {key!r}"
            )
        return state

    async def save(self, state: SequenceState) -> None:
        path = self._path(state.key)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                dir=self._directory, prefix=".seq-", suffix=".tmp"
            )
        except OSError as exc:
            raise SequenceStoreError(f"Cannot prepare {path}: {exc}") from exc

        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(json.dumps(asdict(state)).encode())
                handle.flush()
                if self._fsync:
                    os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise SequenceStoreError(f"Cannot write {path}: {exc}") from exc

        if self._fsync:
            self._sync_directory()

    async def clear(self, key: SessionKey) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise SequenceStoreError(f"Cannot remove {path}: {exc}") from exc

    def _path(self, key: SessionKey) -> Path:
        return self._directory / session_filename(key, ".json")

    def _sync_directory(self) -> None:
        """Flush the rename itself, which file fsync does not cover."""
        try:
            descriptor = os.open(self._directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
