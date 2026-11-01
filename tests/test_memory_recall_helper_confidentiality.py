"""Synthetic refusal tests: every automatic memory-recall helper excludes SECRET.

Explicit authorized backend reads are deliberately unaffected. These helpers
are planning context, never externally verified or signed evidence.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.recall import MemoryRecall
from memory.schema import MemoryItem, MemoryProfile, MemorySensitivity, MemoryType


def _item(
    item_id: str,
    kind: MemoryType,
    sensitivity: MemorySensitivity,
    created: datetime,
    *,
    tags: list[str] | None = None,
) -> MemoryItem:
    return MemoryItem(
        id=item_id,
        type=kind,
        sensitivity=sensitivity,
        text=f"Synthetic {item_id} planning memory",
        tags=tags or [],
        created_at_utc=created,
        updated_at_utc=created,
    )


@pytest.fixture
def scoped_memories(tmp_path):
    path = str(tmp_path / "helper-confidentiality.db")
    project_a = LocalSQLiteBackend(path, project_id="project-a")
    project_b = LocalSQLiteBackend(path, project_id="project-b")
    now = datetime.now(UTC).replace(microsecond=0)

    for kind, name in (
        (MemoryType.NOTE, "note"),
        (MemoryType.DECISION, "decision"),
        (MemoryType.CODEBASE_INDEX, "index"),
    ):
        project_a.store(
            _item(
                f"safe-{name}",
                kind,
                MemorySensitivity.PRIVATE,
                now - timedelta(minutes=5),
                tags=["keep"],
            )
        )
        for n in range(3):
            project_a.store(
                _item(
                    f"secret-{name}-{n}",
                    kind,
                    MemorySensitivity.SECRET,
                    now - timedelta(minutes=n),
                    tags=["keep"],
                )
            )
        project_b.store(
            _item(
                f"foreign-{name}",
                kind,
                MemorySensitivity.PUBLIC,
                now,
                tags=["keep"],
            )
        )
    return path, project_a, project_b


def test_every_automatic_helper_filters_secret_before_limit(scoped_memories):
    _, project_a, project_b = scoped_memories
    recall = MemoryRecall(project_a, MemoryProfile(name="synthetic", max_recall_results=1))
    assert [m.id for m in recall.recall_recent(limit=1, type_filter=MemoryType.NOTE)] == [
        "safe-note"
    ]
    assert [m.id for m in recall.recall_by_type(MemoryType.DECISION, limit=1)] == [
        "safe-decision"
    ]
    assert [m.id for m in recall.recall_decisions(limit=1, tags_filter=["keep"])] == [
        "safe-decision"
    ]
    index = recall.recall_codebase_index()
    assert index is not None and index.id == "safe-index"

    # These remain direct authorized backend capabilities, not prompt injection.
    assert project_a.retrieve("secret-note-0") is not None
    assert project_a.list_items(limit=1, type_filter=MemoryType.NOTE)[0].id.startswith(
        "secret-note"
    )
    assert project_b.retrieve("foreign-note") is not None
    assert "foreign" not in str(recall.recall_decisions(limit=1))


def test_corrupt_sensitivity_is_refused_before_pagination(scoped_memories):
    path, project_a, _ = scoped_memories
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE memory_items SET sensitivity = 'unknown' WHERE id = ?",
            ("secret-decision-0",),
        )
    recall = MemoryRecall(project_a, MemoryProfile(name="synthetic", max_recall_results=1))
    assert [m.id for m in recall.recall_decisions()] == ["safe-decision"]
    assert [m.id for m in recall.recall_by_type(MemoryType.DECISION)] == [
        "safe-decision"
    ]


@pytest.mark.parametrize("bad_limit", [-1, 0, True, 1.5, "1"])
def test_all_paginated_helpers_refuse_invalid_limits(scoped_memories, bad_limit):
    _, project_a, _ = scoped_memories
    recall = MemoryRecall(project_a, MemoryProfile(name="synthetic"))
    with pytest.raises(ValueError, match="positive integer"):
        recall.recall_recent(limit=bad_limit)
    with pytest.raises(ValueError, match="positive integer"):
        recall.recall_by_type(MemoryType.NOTE, limit=bad_limit)
    with pytest.raises(ValueError, match="positive integer"):
        recall.recall_decisions(limit=bad_limit)


@pytest.mark.parametrize("bad_hours", [-1, 0, True, 1.5])
def test_recent_refuses_invalid_hours(scoped_memories, bad_hours):
    _, project_a, _ = scoped_memories
    recall = MemoryRecall(project_a, MemoryProfile(name="synthetic"))
    with pytest.raises(ValueError, match="hours must be a positive integer"):
        recall.recall_recent(hours=bad_hours)


def test_auto_recall_disabled_applies_to_all_helpers(scoped_memories):
    _, project_a, _ = scoped_memories
    recall = MemoryRecall(
        project_a, MemoryProfile(name="synthetic-off", auto_recall=False)
    )
    assert recall.recall_recent() == []
    assert recall.recall_by_type(MemoryType.NOTE) == []
    assert recall.recall_decisions() == []
    assert recall.recall_codebase_index() is None
