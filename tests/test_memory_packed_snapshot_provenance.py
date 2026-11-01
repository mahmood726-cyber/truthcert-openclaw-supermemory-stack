"""Synthetic negative tests for snapshot-bound, noncertifying memory packing.

Memory fingerprints are unsigned database-state identifiers, never scientific
source verification or model-call authentication.
"""

import sqlite3

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.commands import MemoryCommands
from memory.packer import ContextPacker
from memory.schema import MemoryItem, MemoryProfile, RecallResult


def test_packing_keeps_search_snapshot_after_concurrent_source_change(
    tmp_path, monkeypatch
) -> None:
    db = str(tmp_path / "snapshot_pack.db")
    backend = LocalSQLiteBackend(db, project_id="project-a")
    item_id = backend.store(
        MemoryItem(
            text="packedsnapshotmarker synthetic observation",
            metadata={"source_revision": "v1"},
        )
    )
    recalled = backend.search("packedsnapshotmarker")
    assert recalled.items[0].metadata["source_revision"] == "v1"
    assert recalled.db_hash.startswith("sha256:")

    # The source revision advances AFTER search commits its read snapshot.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_items SET metadata = "
            "json_set(metadata, '$.source_revision', 'v2') WHERE id = ?",
            (item_id,),
        )
    assert backend.compute_db_hash() != recalled.db_hash

    # Any attempt to recompute a live hash during packing must fail this test.
    def refuse_rehash() -> str:
        raise AssertionError("packing must use the original recall snapshot")

    monkeypatch.setattr(backend, "compute_db_hash", refuse_rehash)
    packed = ContextPacker(backend, MemoryProfile(name="synthetic")).pack_from_recall(recalled)
    assert packed.db_hash == recalled.db_hash
    assert f"db_hash={recalled.db_hash}" in packed.header
    assert "packedsnapshotmarker" in packed.content
    assert "NOT evidence" in packed.header


def test_high_level_packed_recall_keeps_original_fingerprint(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "command_pack.db")
    commands = MemoryCommands(db_path=db, project_id="project-a")
    remembered = commands.remember("commandpackmarker synthetic revision")
    initial_hash = commands.backend.compute_db_hash()
    original_recall = commands.recall.recall

    def recalled_then_changed(*args, **kwargs):
        result = original_recall(*args, **kwargs)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE memory_items SET metadata = "
                "json_set(metadata, '$.source_revision', 'later') WHERE id = ?",
                (remembered["id"],),
            )
        return result

    monkeypatch.setattr(commands.recall, "recall", recalled_then_changed)
    response = commands.recall_memories("commandpackmarker", pack=True)
    assert response["db_hash"] == initial_hash
    assert f"db_hash={initial_hash}" in response["content"]
    assert commands.backend.compute_db_hash() != response["db_hash"]


@pytest.mark.parametrize(
    "invalid_hash",
    ["", "sha256:abc", "sha256:" + "g" * 64, "signed-by-human", "sha256:" + "A" * 64],
)
def test_nonempty_recall_refuses_missing_or_malformed_fingerprint(tmp_path, invalid_hash) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "bad_hash.db"), project_id="project-a")
    backend.store(MemoryItem(text="invalidpackhashmarker synthetic"))
    result = backend.search("invalidpackhashmarker")
    corrupted = result.model_copy(update={"db_hash": invalid_hash})
    with pytest.raises(ValueError, match="snapshot fingerprint"):
        ContextPacker(backend, MemoryProfile(name="synthetic")).pack_from_recall(corrupted)


def test_direct_item_packing_never_claims_a_recall_snapshot(tmp_path, monkeypatch) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "arbitrary.db"), project_id="project-a")
    backend.store(MemoryItem(text="arbitrarypackmarker synthetic"))
    items = backend.list_items()

    def refuse_rehash() -> str:
        raise AssertionError("arbitrary items cannot be bound to a later live hash")

    monkeypatch.setattr(backend, "compute_db_hash", refuse_rehash)
    packed = ContextPacker(backend, MemoryProfile(name="synthetic")).pack(items)
    assert packed.db_hash == ""
    assert "NOT_SNAPSHOT_BOUND" in packed.header
    assert "NOT evidence" in packed.header


def test_empty_unverified_recall_stays_noncertifying(tmp_path) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "empty.db"), project_id="project-a")
    packed = ContextPacker(backend, MemoryProfile(name="synthetic")).pack_from_recall(
        RecallResult(query="nothing", items=[], db_hash="")
    )
    assert packed.db_hash == ""
    assert packed.items_included == 0
    assert "NOT_SNAPSHOT_BOUND" in packed.header
