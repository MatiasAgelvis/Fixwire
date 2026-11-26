"""Tests for FileOutbox: an append-only journal per session."""

import pytest

from fixwire.core.outbox import Outbox, OutboxError
from fixwire.persistence import FileOutbox

KEY = ("CLIENT", "SERVER")


def _store(directory, **kwargs) -> FileOutbox:
    return FileOutbox(directory, **kwargs)


def _only_file(directory):
    files = [p for p in directory.iterdir() if p.is_file()]
    assert len(files) == 1, files
    return files[0]


class TestFileOutbox:
    """Durable outbox: survives a restart, survives a crash mid-append."""

    def test_protocol_satisfied(self, tmp_path):
        """The file outbox satisfies the Outbox protocol."""
        # Act
        outbox: Outbox = _store(tmp_path)

        # Assert
        assert outbox is not None

    @pytest.mark.asyncio
    async def test_round_trip(self, tmp_path):
        """Stored bytes come back exactly."""
        # Arrange
        outbox = _store(tmp_path)
        payload = b"8=FIX.4.4\x019=5\x0135=0\x0110=000\x01"

        # Act
        await outbox.append(KEY, 7, payload)

        # Assert
        assert await outbox.get_range(KEY, 7, 7) == [payload]

    @pytest.mark.asyncio
    async def test_a_new_instance_reads_what_the_last_one_wrote(self, tmp_path):
        """The point of the store: messages survive the process."""
        # Arrange
        await _store(tmp_path).append(KEY, 3, b"m3")

        # Act
        outbox = _store(tmp_path)

        # Assert
        assert await outbox.get_range(KEY, 1, 10) == [b"m3"]
        assert await outbox.count(KEY) == 1

    @pytest.mark.asyncio
    async def test_range_is_inclusive_and_ordered(self, tmp_path):
        """Bounds are inclusive on both ends, oldest first."""
        # Arrange
        outbox = _store(tmp_path)
        for seq in (1, 2, 3, 4, 5):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        result = await outbox.get_range(KEY, 2, 4)

        # Assert
        assert result == [b"m2", b"m3", b"m4"]

    @pytest.mark.asyncio
    async def test_missing_session_returns_nothing(self, tmp_path):
        """No journal means nothing to replay."""
        # Arrange
        outbox = _store(tmp_path)

        # Act & Assert
        assert await outbox.get_range(KEY, 1, 10) == []
        assert await outbox.count(KEY) == 0

    @pytest.mark.asyncio
    async def test_prune_compacts_the_journal(self, tmp_path):
        """Pruning rewrites the file without the old records."""
        # Arrange
        outbox = _store(tmp_path)
        for seq in (1, 2, 3, 4):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Act
        await outbox.prune(KEY, 2)

        # Assert
        assert await outbox.get_range(KEY, 1, 10) == [b"m3", b"m4"]
        assert await _store(tmp_path).count(KEY) == 2
        assert b"m1" not in _only_file(tmp_path).read_bytes()

    @pytest.mark.asyncio
    async def test_clear_removes_the_journal(self, tmp_path):
        """Clear deletes the session's journal."""
        # Arrange
        outbox = _store(tmp_path)
        await outbox.append(KEY, 1, b"m1")

        # Act
        await outbox.clear(KEY)

        # Assert
        assert list(tmp_path.iterdir()) == []
        assert await outbox.count(KEY) == 0

    @pytest.mark.asyncio
    async def test_directory_is_created_on_first_append(self, tmp_path):
        """The store owns its directory, including parents."""
        # Arrange
        directory = tmp_path / "nested" / "outbox"
        outbox = _store(directory)

        # Act
        await outbox.append(KEY, 1, b"m1")

        # Assert
        assert directory.is_dir()
        assert await outbox.get_range(KEY, 1, 1) == [b"m1"]

    @pytest.mark.asyncio
    async def test_a_foreign_journal_is_rejected(self, tmp_path):
        """A journal holding another session must not be replayed."""
        # Arrange: two identities that sanitise to the same filename
        outbox = _store(tmp_path)
        await outbox.append(("A/B", "R"), 1, b"foreign")

        # Act & Assert
        with pytest.raises(OutboxError, match="expected"):
            await outbox.get_range(("A_B", "R"), 1, 10)

    @pytest.mark.asyncio
    async def test_a_corrupt_record_is_rejected(self, tmp_path):
        """Corruption is an error, not a silent skip.

        Replaying the wrong bytes is worse than failing the resend.
        """
        # Arrange
        outbox = _store(tmp_path)
        await outbox.append(KEY, 1, b"m1")
        path = _only_file(tmp_path)
        path.write_bytes(path.read_bytes() + b"not-a-record\n")

        # Act & Assert
        with pytest.raises(OutboxError, match="Corrupt"):
            await outbox.get_range(KEY, 1, 10)

    @pytest.mark.asyncio
    async def test_oldest_are_dropped_beyond_the_bound(self, tmp_path):
        """The journal is bounded, so it cannot grow forever."""
        # Arrange
        outbox = _store(tmp_path, max_messages=4)

        # Act
        for seq in range(1, 7):
            await outbox.append(KEY, seq, b"m" + str(seq).encode())

        # Assert
        stored = await outbox.get_range(KEY, 1, 0)
        assert b"m6" in stored
        assert b"m1" not in stored
        assert await outbox.count(KEY) <= 4

    @pytest.mark.asyncio
    async def test_identifiers_cannot_escape_the_directory(self, tmp_path):
        """Filenames are sanitised, not interpolated raw."""
        # Arrange
        outbox = _store(tmp_path / "store")
        key = ("../../etc/passwd", "SERVER")

        # Act
        await outbox.append(key, 1, b"m1")

        # Assert
        assert await outbox.get_range(key, 1, 1) == [b"m1"]
        assert not (tmp_path / "etc").exists()
