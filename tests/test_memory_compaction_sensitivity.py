"""Synthetic regression: compaction never downgrades a SECRET memory to PRIVATE.

Memory summaries are planning context, not source-verified evidence or certificates.
"""

from datetime import UTC, datetime, timedelta

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.compaction import MemoryCompactor
from memory.schema import MemoryItem, MemorySensitivity, MemoryType


def _item(item_id: str, stamp: datetime, sensitivity: MemorySensitivity) -> MemoryItem:
    return MemoryItem(
        id=item_id,
        type=MemoryType.NOTE,
        text=f"Synthetic {sensitivity.value} memory canary {item_id}",
        sensitivity=sensitivity,
        created_at_utc=stamp,
        updated_at_utc=stamp,
    )


@pytest.mark.parametrize("strategy", ["rolling", "threshold"])
def test_compaction_preserves_secret_classification_and_project_boundary(
    tmp_path, strategy: str
) -> None:
    db = str(tmp_path / "compaction_sensitive.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    old = datetime.now(UTC) - timedelta(days=60)
    a.store(_item("a-secret", old, MemorySensitivity.SECRET))
    a.store(_item("a-private", old, MemorySensitivity.PRIVATE))
    a.store(_item("a-new-public", datetime.now(UTC), MemorySensitivity.PUBLIC))
    b.store(_item("b-secret", old, MemorySensitivity.SECRET))

    compactor = MemoryCompactor(a)
    result = (
        compactor.compact_rolling(max_age_days=30)
        if strategy == "rolling"
        else compactor.compact_threshold(max_items=2, target_items=1)
    )

    assert result["summaries_created"] == 1
    assert result["items_removed"] == 2
    summaries = a.list_items(type_filter=MemoryType.SUMMARY)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.sensitivity == MemorySensitivity.SECRET
    assert summary.metadata["source_count"] == 2
    assert "a-secret" in summary.text
    assert a.retrieve("a-secret") is None
    assert a.retrieve("a-private") is None
    assert a.retrieve("a-new-public") is not None

    # A project-B SECRET item must neither enter A's summary nor be removed.
    foreign = b.retrieve("b-secret")
    assert foreign is not None and foreign.sensitivity == MemorySensitivity.SECRET
    assert "b-secret" not in summary.text
    assert b.list_items(type_filter=MemoryType.SUMMARY) == []


def test_public_only_compaction_keeps_conservative_private_summary_default(tmp_path) -> None:
    a = LocalSQLiteBackend(str(tmp_path / "public.db"), project_id="project-a")
    old = datetime.now(UTC) - timedelta(days=60)
    a.store(_item("a-public-one", old, MemorySensitivity.PUBLIC))
    a.store(_item("a-public-two", old, MemorySensitivity.PUBLIC))
    result = MemoryCompactor(a).compact_rolling(max_age_days=30)
    assert result["summaries_created"] == 1
    summaries = a.list_items(type_filter=MemoryType.SUMMARY)
    assert len(summaries) == 1
    assert summaries[0].sensitivity == MemorySensitivity.PRIVATE


def test_dry_run_does_not_generate_or_reclassify_secret_memory(tmp_path) -> None:
    a = LocalSQLiteBackend(str(tmp_path / "dry.db"), project_id="project-a")
    old = datetime.now(UTC) - timedelta(days=60)
    a.store(_item("a-secret", old, MemorySensitivity.SECRET))
    a.store(_item("a-private", old, MemorySensitivity.PRIVATE))
    result = MemoryCompactor(a).compact_rolling(max_age_days=30, dry_run=True)
    assert result["summaries_created"] == 0
    assert result["items_removed"] == 0
    assert a.list_items(type_filter=MemoryType.SUMMARY) == []
    secret = a.retrieve("a-secret")
    assert secret is not None and secret.sensitivity == MemorySensitivity.SECRET


def test_empty_derived_sensitivity_refuses_instead_of_fabricating_classification() -> None:
    with pytest.raises(ValueError, match="empty source"):
        MemoryCompactor._summary_sensitivity([])
