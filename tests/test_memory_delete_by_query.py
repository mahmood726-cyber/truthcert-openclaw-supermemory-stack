"""Synthetic regression for unbounded, project-scoped memory erasure."""

import sqlite3

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.schema import MemoryItem


def test_delete_by_query_does_not_silently_stop_at_10000(tmp_path) -> None:
    """Soft and hard query deletion must reach every match, not a search page."""
    db = str(tmp_path / "bulk_deletion.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    seed_id = a.store(MemoryItem(text="bulkdelete synthetic item", tags=["not-evidence"]))
    other_id = b.store(MemoryItem(text="bulkdelete synthetic other project"))

    # Bulk-load synthetic rows in one SQLite transaction so the regression
    # is fast without weakening FTS triggers or making real memory fixtures.
    with sqlite3.connect(db) as conn:
        template = conn.execute(
            """SELECT created_at_utc, updated_at_utc, type, source, tags,
                      text, metadata, sensitivity, retention, content_hash, deleted
               FROM memory_items WHERE id = ?""",
            (seed_id,),
        ).fetchone()
        assert template is not None
        conn.executemany(
            """INSERT INTO memory_items
               (id, created_at_utc, updated_at_utc, type, source, tags,
                text, metadata, sensitivity, retention, content_hash, deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ((f"bulk-{i:05d}", *template) for i in range(10005)),
        )

    expected = 10006
    assert a.search("bulkdelete", limit=1).total_matches == expected
    assert a.delete_by_query("bulkdelete") == expected
    assert a.search("bulkdelete").total_matches == 0
    assert a.delete_by_query("bulkdelete") == 0
    assert b.retrieve(other_id) is not None
    assert b.search("bulkdelete").total_matches == 1

    # Restore only the deliberately generated project-A fixture to exercise
    # hard deletion independently; no production undelete API is implied.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_items SET deleted = 0 WHERE id = ? OR id LIKE 'bulk-%'",
            (seed_id,),
        )
    assert a.delete_by_query("bulkdelete", hard=True) == expected
    assert a.search("bulkdelete").total_matches == 0
    assert a.get_stats().total_items == 0
    assert b.retrieve(other_id) is not None
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE id = ? OR id LIKE 'bulk-%'",
                (seed_id,),
            ).fetchone()[0]
            == 0
        )


def test_delete_by_query_refuses_cross_project_and_invalid_scope(tmp_path) -> None:
    """A query deletion must leave other and ambiguous project labels untouched."""
    db = str(tmp_path / "scope_deletion.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    own_id = a.store(MemoryItem(text="scopeerase synthetic own"))
    other_id = b.store(MemoryItem(text="scopeerase synthetic other"))
    corrupted_id = b.store(MemoryItem(text="scopeerase synthetic ambiguous"))
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_items SET metadata = ? WHERE id = ?",
            ('{"project_id":"project-a","project_id":"project-b"}', corrupted_id),
        )

    assert a.delete_by_query("scopeerase", hard=True) == 1
    assert a.retrieve(own_id) is None
    assert b.retrieve(other_id) is not None
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE id = ?", (corrupted_id,)
            ).fetchone()[0]
            == 1
        )
