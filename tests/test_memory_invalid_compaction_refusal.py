"""Synthetic refusal: invalid compaction commands must never mutate retained records.

Soft-deleted rows are deliberately retained until a valid cleanup operation.
Memory remains planning-only, never certificate or scientific source evidence.
"""

import sqlite3

from memory.commands import MemoryCommands
from memory.schema import MemoryItem


def _physical_rows(path: str) -> list[tuple[str, str, int]]:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT id, text, deleted FROM memory_items ORDER BY id").fetchall()


def test_unknown_compaction_strategy_is_storage_noop_across_projects(tmp_path) -> None:
    path = str(tmp_path / "unknown-strategy.db")
    a = MemoryCommands(db_path=path, project_id="project-a")
    b = MemoryCommands(db_path=path, project_id="project-b")

    deleted_a = a.backend.store(MemoryItem(text="Synthetic tombstone A"))
    kept_a = a.backend.store(MemoryItem(text="Synthetic live A"))
    deleted_b = b.backend.store(MemoryItem(text="Synthetic tombstone B"))
    kept_b = b.backend.store(MemoryItem(text="Synthetic live B"))
    assert a.backend.delete(deleted_a)
    assert b.backend.delete(deleted_b)

    before = _physical_rows(path)
    assert {row[0] for row in before} == {deleted_a, kept_a, deleted_b, kept_b}
    assert next(row[2] for row in before if row[0] == deleted_a) == 1
    first_hash = a.backend.compute_db_hash()

    result = a.compact(strategy="not-a-valid-strategy")
    assert result == {"error": "Unknown strategy: not-a-valid-strategy"}
    assert _physical_rows(path) == before
    assert a.backend.compute_db_hash() == first_hash
    assert a.backend.retrieve(kept_a) is not None
    assert b.backend.retrieve(kept_b) is not None


def test_valid_compaction_retains_existing_scoped_cleanup_behavior(tmp_path) -> None:
    path = str(tmp_path / "valid-cleanup.db")
    a = MemoryCommands(db_path=path, project_id="project-a")
    b = MemoryCommands(db_path=path, project_id="project-b")

    deleted_a = a.backend.store(MemoryItem(text="Synthetic cleanup A"))
    deleted_b = b.backend.store(MemoryItem(text="Synthetic cleanup B"))
    assert a.backend.delete(deleted_a)
    assert b.backend.delete(deleted_b)

    result = a.compact(strategy="rolling", max_age_days=30)
    assert result["strategy"] == "rolling"
    assert result["deleted_cleaned"] == 1

    remaining = _physical_rows(path)
    assert {row[0] for row in remaining} == {deleted_b}
    assert remaining[0][2] == 1
