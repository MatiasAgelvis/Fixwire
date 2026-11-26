"""File-backed Outbox: one append-only journal per session."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fixwire.core.outbox import DEFAULT_MAX_MESSAGES, OutboxError
from fixwire.core.sequence import SessionKey
from fixwire.persistence._paths import session_filename

_HEADER = b"#FIXWIRE OUTBOX\t"
_SEPARATOR = b"\t"
_NEWLINE = b"\n"


class FileOutbox:
    """Keeps outbound messages in an append-only journal per session.

    Each record is ``MsgSeqNum<TAB>raw bytes<NEWLINE>``. FIX payloads are
    ASCII with SOH separators and never contain a newline, so no escaping is
    needed.

    Appends are O(1). The journal is bounded by message count: when it
    exceeds ``max_messages`` it is compacted, atomically, down to half that,
    so compaction is amortised instead of happening on every append.

    The record count is cached per session in this instance, which assumes
    one store per directory. Two processes appending to the same journal
    would drift — sharing a journal is the sequence store's job, not this
    one's.
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        fsync: bool = False,
    ) -> None:
        """Initialize the outbox.

        Args:
            directory: Where journals live. Created on first append.
            max_messages: Upper bound on retained messages per session.
            fsync: Flush each append to disk instead of relying on the page
                cache. Survives power loss at the cost of ~1ms per message.
        """
        self._directory = Path(directory)
        self._max = max(2, max_messages)
        self._fsync = fsync
        self._counts: dict[SessionKey, int] = {}

    async def append(self, key: SessionKey, seq: int, data: bytes) -> None:
        path = self._path(key)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists() or path.stat().st_size == 0
            with path.open("ab") as handle:
                if fresh:
                    handle.write(_header(key))
                handle.write(f"{seq}".encode() + _SEPARATOR + data + _NEWLINE)
                handle.flush()
                if self._fsync:
                    os.fsync(handle.fileno())
        except OSError as exc:
            raise OutboxError(f"Cannot append to {path}: {exc}") from exc

        self._counts[key] = self._known_count(key, path) + 1
        if self._counts[key] > self._max:
            self._write(path, key, self._records(path, key)[-self._max // 2:])
            self._counts[key] = self._max // 2

    async def get_range(
        self, key: SessionKey, begin: int, end: int = 0
    ) -> list[bytes]:
        path = self._path(key)
        if not path.exists():
            return []
        return [
            data
            for seq, data in self._records(path, key)
            if seq >= begin and (end == 0 or seq <= end)
        ]

    async def prune(self, key: SessionKey, through: int) -> None:
        path = self._path(key)
        if not path.exists():
            return
        records = self._records(path, key)
        kept = [(seq, data) for seq, data in records if seq > through]
        if len(kept) == len(records):
            return
        self._write(path, key, kept)
        self._counts[key] = len(kept)

    async def clear(self, key: SessionKey) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise OutboxError(f"Cannot remove {path}: {exc}") from exc
        self._counts.pop(key, None)

    async def truncate(self, key: SessionKey, after: int) -> None:
        path = self._path(key)
        if not path.exists():
            return
        records = self._records(path, key)
        kept = [(seq, data) for seq, data in records if seq <= after]
        if len(kept) == len(records):
            return
        self._write(path, key, kept)
        self._counts[key] = len(kept)

    async def count(self, key: SessionKey) -> int:
        path = self._path(key)
        if not path.exists():
            return 0
        return len(self._records(path, key))

    def _path(self, key: SessionKey) -> Path:
        return self._directory / session_filename(key, ".outbox")

    def _known_count(self, key: SessionKey, path: Path) -> int:
        """Record count for this session, cached after the first read."""
        cached = self._counts.get(key)
        if cached is None:
            cached = len(self._records(path, key)) if path.exists() else 0
            self._counts[key] = cached
        return cached

    def _records(self, path: Path, key: SessionKey) -> list[tuple[int, bytes]]:
        """Read and validate the journal."""
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise OutboxError(f"Cannot read {path}: {exc}") from exc

        lines = raw.split(_NEWLINE)
        header = lines[0] if lines else b""
        if not header.startswith(_HEADER):
            raise OutboxError(f"Corrupt outbox file {path}: missing header")
        sender, separator, target = header[len(_HEADER):].partition(_SEPARATOR)
        if not separator:
            raise OutboxError(f"Corrupt outbox file {path}: bad header")
        stored = (sender.decode(), target.decode())
        if stored != key:
            raise OutboxError(
                f"{path} holds {stored!r}, expected {key!r}"
            )

        records: list[tuple[int, bytes]] = []
        for line in lines[1:]:
            if not line:
                continue
            seq_field, separator, data = line.partition(_SEPARATOR)
            if not separator or not seq_field.isdigit():
                raise OutboxError(f"Corrupt outbox file {path}: bad record")
            records.append((int(seq_field), data))
        return records

    def _write(
        self, path: Path, key: SessionKey, records: list[tuple[int, bytes]]
    ) -> None:
        """Atomically replace the journal with ``records``."""
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                dir=self._directory, prefix=".outbox-", suffix=".tmp"
            )
        except OSError as exc:
            raise OutboxError(f"Cannot rewrite {path}: {exc}") from exc

        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_header(key))
                for seq, data in records:
                    handle.write(
                        f"{seq}".encode() + _SEPARATOR + data + _NEWLINE
                    )
                handle.flush()
                if self._fsync:
                    os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise OutboxError(f"Cannot rewrite {path}: {exc}") from exc

        if self._fsync:
            self._sync_directory()

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


def _header(key: SessionKey) -> bytes:
    return _HEADER + key[0].encode() + _SEPARATOR + key[1].encode() + _NEWLINE
