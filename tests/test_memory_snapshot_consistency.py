"""Fail-closed synthetic interleaving tests for recall provenance snapshots.

These tests make a concurrent writer commit after search results are fetched
but before the API returns its memory-state fingerprint. They do not certify
external source validity or cryptographically authenticate model calls.
"""

import sqlite3

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.schema import MemoryItem


def _enable_wal(db_path: str) -> None:
    # SQLite WAL permits a writer to commit while a prior reader is active.
    conn = sqlite3.connect(db_path)
    try:
        actual = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        assert actual.lower() == "wal"
    finally:
        conn.close()


def _concurrent_source_revision_change(db_path: str, item_id: str) -> None:
    """A different connection advances the persisted memory source revision."""
    writer = sqlite3.connect(db_path, timeout=5.0)
    try:
        with writer:
            writer.execute(
                "UPDATE memory_items SET metadata = "
                "json_set(metadata, '$.source_revision', 'v2') WHERE id = ?",
                (item_id,),
            )
    finally:
        writer.close()


def test_sync_recall_hash_matches_selected_snapshot_under_concurrent_revision(
    tmp_path, monkeypatch
) -> None:
    db_path = str(tmp_path / "sync_snapshot.db")
    memory = LocalSQLiteBackend(db_path, project_id="project-a")
    _enable_wal(db_path)
    memory.store(
        MemoryItem(
            text="snapshotmarker synthetic source revision",
            metadata={"source_revision": "v1"},
        )
    )
    prewrite_hash = memory.compute_db_hash()
    original = memory._row_to_item
    changed = False

    def interleave_writer(row):
        nonlocal changed
        item = original(row)
        if not changed:
            changed = True
            _concurrent_source_revision_change(db_path, item.id)
        return item

    monkeypatch.setattr(memory, "_row_to_item", interleave_writer)
    result = memory.search("snapshotmarker")
    assert changed
    assert len(result.items) == result.total_matches == 1
    assert result.items[0].metadata["source_revision"] == "v1"
    assert result.db_hash == prewrite_hash
    # The next search/fingerprint must see the new version, not remain cached.
    assert memory.compute_db_hash() != prewrite_hash
    assert memory.search("snapshotmarker").items[0].metadata["source_revision"] == "v2"


@pytest.mark.asyncio
async def test_async_recall_hash_matches_selected_snapshot_under_concurrent_revision(
    tmp_path, monkeypatch
) -> None:
    db_path = str(tmp_path / "async_snapshot.db")
    memory = AsyncLocalSQLiteBackend(db_path, project_id="project-a")
    try:
        await memory.store(
            MemoryItem(
                text="asyncsnapshotmarker synthetic source revision",
                metadata={"source_revision": "v1"},
            )
        )
        _enable_wal(db_path)
        prewrite_hash = await memory.compute_db_hash()
        original = memory._row_to_item
        changed = False

        def interleave_writer(row):
            nonlocal changed
            item = original(row)
            if not changed:
                changed = True
                _concurrent_source_revision_change(db_path, item.id)
            return item

        monkeypatch.setattr(memory, "_row_to_item", interleave_writer)
        result = await memory.search("asyncsnapshotmarker")
        assert changed
        assert len(result.items) == result.total_matches == 1
        assert result.items[0].metadata["source_revision"] == "v1"
        assert result.db_hash == prewrite_hash
        assert await memory.compute_db_hash() != prewrite_hash
        assert (await memory.search("asyncsnapshotmarker")).items[0].metadata[
            "source_revision"
        ] == "v2"
    finally:
        await memory.close()
