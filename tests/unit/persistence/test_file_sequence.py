"""Tests for FileSequenceStore: one JSON file per session, atomic replacement."""

import json

import pytest

from fixwire.core.sequence import SequenceState, SequenceStore, SequenceStoreError
from fixwire.persistence import FileSequenceStore


def _state(
    outgoing: int = 0,
    incoming: int = 0,
    sender: str = "CLIENT",
    target: str = "SERVER",
) -> SequenceState:
    return SequenceState(
        sender_comp_id=sender,
        target_comp_id=target,
        outgoing=outgoing,
        incoming=incoming,
    )


def _only_file(directory) -> "object":
    files = [p for p in directory.iterdir() if p.is_file()]
    assert len(files) == 1, files
    return files[0]


class TestFileSequenceStore:
    """Durable store: survives a restart, never leaves a partial file."""

    def test_protocol_satisfied(self, tmp_path):
        """The file store satisfies the SequenceStore protocol."""
        # Act
        store: SequenceStore = FileSequenceStore(tmp_path)

        # Assert
        assert store is not None

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, tmp_path):
        """No file means a new session."""
        # Arrange
        store = FileSequenceStore(tmp_path)

        # Act
        state = await store.load(("CLIENT", "SERVER"))

        # Assert
        assert state is None

    @pytest.mark.asyncio
    async def test_round_trip(self, tmp_path):
        """What is saved comes back unchanged."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        saved = _state(outgoing=7, incoming=3)

        # Act
        await store.save(saved)

        # Assert
        assert await store.load(("CLIENT", "SERVER")) == saved

    @pytest.mark.asyncio
    async def test_directory_is_created_on_first_save(self, tmp_path):
        """The store owns its directory, including parents."""
        # Arrange
        directory = tmp_path / "nested" / "sequences"
        store = FileSequenceStore(directory)

        # Act
        await store.save(_state())

        # Assert
        assert directory.is_dir()
        assert await store.load(("CLIENT", "SERVER")) == _state()

    @pytest.mark.asyncio
    async def test_a_new_instance_reads_what_the_last_one_wrote(self, tmp_path):
        """The point of the store: state survives the process."""
        # Arrange
        await FileSequenceStore(tmp_path).save(_state(outgoing=42))

        # Act
        reloaded = await FileSequenceStore(tmp_path).load(("CLIENT", "SERVER"))

        # Assert
        assert reloaded is not None
        assert reloaded.outgoing == 42

    @pytest.mark.asyncio
    async def test_sessions_get_separate_files(self, tmp_path):
        """Different identities do not share storage."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        await store.save(_state(outgoing=5, sender="A", target="R"))
        await store.save(_state(outgoing=8, sender="B", target="R"))

        # Act & Assert
        assert (await store.load(("A", "R"))).outgoing == 5
        assert (await store.load(("B", "R"))).outgoing == 8
        assert len(list(tmp_path.iterdir())) == 2

    @pytest.mark.asyncio
    async def test_clear_removes_only_its_own_session(self, tmp_path):
        """Clearing one session leaves the others intact."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        await store.save(_state(sender="A", target="R"))
        await store.save(_state(sender="B", target="R"))

        # Act
        await store.clear(("A", "R"))

        # Assert
        assert await store.load(("A", "R")) is None
        assert await store.load(("B", "R")) is not None

    @pytest.mark.asyncio
    async def test_fsync_mode_round_trips(self, tmp_path):
        """Durability mode uses the same format."""
        # Arrange
        store = FileSequenceStore(tmp_path, fsync=True)
        saved = _state(outgoing=11, incoming=2)

        # Act
        await store.save(saved)

        # Assert
        assert await store.load(("CLIENT", "SERVER")) == saved

    @pytest.mark.asyncio
    async def test_identity_mismatch_is_rejected(self, tmp_path):
        """A file holding another session must not be used."""
        # Arrange: two keys that sanitise to the same filename
        store = FileSequenceStore(tmp_path)
        await store.save(_state(sender="A/B", target="R"))
        await store.save(_state(sender="A_B", target="R"))

        # Act & Assert
        with pytest.raises(SequenceStoreError, match="expected"):
            await store.load(("A/B", "R"))

    @pytest.mark.asyncio
    async def test_corrupt_file_is_rejected(self, tmp_path):
        """Corruption is an error: silently starting at zero would reuse numbers."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        await store.save(_state())
        _only_file(tmp_path).write_bytes(b"not json")

        # Act & Assert
        with pytest.raises(SequenceStoreError, match="Corrupt"):
            await store.load(("CLIENT", "SERVER"))

    @pytest.mark.asyncio
    async def test_failed_rename_keeps_the_previous_state(self, tmp_path, monkeypatch):
        """A failed save must not destroy what was already durable."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        await store.save(_state(outgoing=1))

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(
            "fixwire.persistence.file_sequence.os.replace", boom
        )

        # Act & Assert
        with pytest.raises(SequenceStoreError, match="Cannot write"):
            await store.save(_state(outgoing=99))

        assert (await store.load(("CLIENT", "SERVER"))).outgoing == 1
        # No temporary files left behind
        assert [p.name for p in tmp_path.iterdir()] == ["CLIENT--SERVER.json"]

    @pytest.mark.asyncio
    async def test_identifiers_cannot_escape_the_directory(self, tmp_path):
        """Filenames are sanitised, not interpolated raw."""
        # Arrange
        store = FileSequenceStore(tmp_path / "store")
        saved = _state(sender="../../etc/passwd", target="SERVER")

        # Act
        await store.save(saved)
        loaded = await store.load(("../../etc/passwd", "SERVER"))

        # Assert
        assert loaded == saved
        assert not (tmp_path / "etc").exists()
        assert [p.name for p in (tmp_path / "store").iterdir()] == [
            ".._.._etc_passwd--SERVER.json"
        ]

    @pytest.mark.asyncio
    async def test_saved_payload_is_readable_json(self, tmp_path):
        """Operators and tooling can inspect the file."""
        # Arrange
        store = FileSequenceStore(tmp_path)
        await store.save(_state(outgoing=3, incoming=4))

        # Act
        data = json.loads(_only_file(tmp_path).read_bytes())

        # Assert
        assert data == {
            "sender_comp_id": "CLIENT",
            "target_comp_id": "SERVER",
            "outgoing": 3,
            "incoming": 4,
        }
