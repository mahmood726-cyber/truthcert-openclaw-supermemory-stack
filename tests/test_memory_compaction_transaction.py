"""Synthetic fail-closed tests for atomic memory compaction.

No medical or personal data. Source provenance and SECRET classification remain
noncertifying memory metadata; a concurrent change must not yield a stale summary.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.compaction import MemoryCompactor
from memory.schema import MemoryItem, MemorySensitivity, MemoryType


def _seed(path: str) -> tuple[LocalSQLiteBackend, LocalSQLiteBackend]:
    a = LocalSQLiteBackend(path, project_id="project-a")
    b = LocalSQLiteBackend(path, project_id="project-b")
    old = datetime.now(UTC) - timedelta(days=90)
    a.store(
        MemoryItem(
            id="a-old-one",
            text="Synthetic historical SECRET one",
            sensitivity=MemorySensitivity.SECRET,
            created_at_utc=old,
            updated_at_utc=old,
        )
    )
    a.store(
        MemoryItem(
            id="a-old-two",
            text="Synthetic historical PRIVATE two",
            created_at_utc=old,
            updated_at_utc=old,
        )
    )
    a.store(MemoryItem(id="a-current", text="Synthetic current canary"))
    b.store(MemoryItem(id="b-keep", text="Synthetic other-project canary"))
    return a, b


def _compact(a: LocalSQLiteBackend, strategy: str) -> dict:
    compactor = MemoryCompactor(a)
    if strategy == "rolling":
        return compactor.compact_rolling(max_age_days=30)
    return compactor.compact_threshold(max_items=2, target_items=1)


@pytest.mark.parametrize("strategy", ["rolling", "threshold"])
def test_changed_source_refuses_stale_compaction_before_writing(
    tmp_path, monkeypatch: pytest.MonkeyPatch, strategy: str
) -> None:
    path = str(tmp_path / "stale.db")
    a, b = _seed(path)
    writer = LocalSQLiteBackend(path, project_id="project-a")
    original_list = a.list_items
    injected = False

    def list_with_concurrent_delete(*args, **kwargs):
        nonlocal injected
        selected = original_list(*args, **kwargs)
        if not injected:
            assert writer.delete("a-old-one", hard=True)
            injected = True
        return selected

    monkeypatch.setattr(a, "list_items", list_with_concurrent_delete)
    with pytest.raises(RuntimeError, match="changed|stale|snapshot"):
        _compact(a, strategy)

    assert injected
    assert a.retrieve("a-old-one") is None  # The independent writer acted.
    assert a.retrieve("a-old-two") is not None
    assert a.retrieve("a-current") is not None
    assert a.list_items(type_filter=MemoryType.SUMMARY) == []
    assert b.retrieve("b-keep") is not None


@pytest.mark.parametrize("strategy", ["rolling", "threshold"])
def test_failed_source_deletion_rolls_back_summary_and_every_delete(
    tmp_path, strategy: str
) -> None:
    path = str(tmp_path / "rollback.db")
    a, b = _seed(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TRIGGER synthetic_compaction_abort
            BEFORE DELETE ON memory_items
            WHEN old.id = 'a-old-two'
            BEGIN
                SELECT RAISE(ABORT, 'synthetic delete failure');
            END
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="synthetic delete failure"):
        _compact(a, strategy)

    assert a.retrieve("a-old-one") is not None
    assert a.retrieve("a-old-two") is not None
    assert a.retrieve("a-current") is not None
    assert a.list_items(type_filter=MemoryType.SUMMARY) == []
    assert b.retrieve("b-keep") is not None


@pytest.mark.parametrize("strategy", ["rolling", "threshold"])
def test_other_project_write_does_not_invalidate_scoped_compaction(
    tmp_path, monkeypatch: pytest.MonkeyPatch, strategy: str
) -> None:
    path = str(tmp_path / "isolation.db")
    a, b = _seed(path)
    original_list = a.list_items
    injected = False

    def list_with_other_project_write(*args, **kwargs):
        nonlocal injected
        selected = original_list(*args, **kwargs)
        if not injected:
            b.store(MemoryItem(id="b-new", text="Synthetic independent writer"))
            injected = True
        return selected

    monkeypatch.setattr(a, "list_items", list_with_other_project_write)
    result = _compact(a, strategy)

    assert injected
    assert result["summaries_created"] == 1
    assert result["items_removed"] == 2
    summary = a.list_items(type_filter=MemoryType.SUMMARY)[0]
    assert summary.sensitivity == MemorySensitivity.SECRET
    assert b.retrieve("b-new") is not None
    assert b.retrieve("b-keep") is not None
