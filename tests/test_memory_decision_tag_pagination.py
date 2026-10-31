"""Synthetic scoped-memory pagination and decision-tag refusal regressions.

Memory is planning context, not a certificate or authenticated source.
"""

from datetime import UTC, datetime, timedelta

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.recall import MemoryRecall
from memory.schema import MemoryItem, MemoryProfile, MemoryType


def _decision(item_id: str, tag: str, stamp: datetime) -> MemoryItem:
    return MemoryItem(
        id=item_id,
        type=MemoryType.DECISION,
        text=f"Synthetic private decision {item_id}",
        tags=[tag],
        created_at_utc=stamp,
        updated_at_utc=stamp,
    )


def test_decision_tags_are_filtered_before_limit_with_project_isolation(tmp_path):
    db = str(tmp_path / "tag_page.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    oldest = datetime(2026, 10, 31, tzinfo=UTC)

    a.store(_decision("a-keep", "keep", oldest))
    for i in range(5):
        a.store(_decision(f"a-omit-{i}", "bookkeep", oldest + timedelta(minutes=i + 1)))
    b.store(_decision("b-keep", "keep", oldest + timedelta(minutes=10)))

    # Former post-LIMIT filter returned [] because the first page was all
    # nonmatching tags. Exact JSON membership also refuses substring aliases.
    recall = MemoryRecall(a, MemoryProfile(name="synthetic"))
    assert [m.id for m in recall.recall_decisions(limit=1, tags_filter=["keep"])] == ["a-keep"]
    assert [m.id for m in a.list_items(limit=1, tags_filter=["keep"])] == ["a-keep"]
    assert [m.id for m in b.list_items(limit=1, tags_filter=["keep"])] == ["b-keep"]
    assert a.list_items(limit=2, tags_filter=["missing"]) == []


def test_equal_timestamp_pages_use_stable_id_tiebreaker(tmp_path):
    backend = LocalSQLiteBackend(str(tmp_path / "ties.db"), project_id="project-a")
    stamp = datetime(2026, 10, 31, tzinfo=UTC)
    for item_id in ("z", "a", "m"):
        backend.store(_decision(item_id, "keep", stamp))
    assert [m.id for m in backend.list_items(limit=2, offset=0)] == ["a", "m"]
    assert [m.id for m in backend.list_items(limit=2, offset=2)] == ["z"]


@pytest.mark.asyncio
async def test_async_tag_filter_before_limit_and_stable_pages(tmp_path):
    db = str(tmp_path / "async_tags.db")
    a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    b = AsyncLocalSQLiteBackend(db, project_id="project-b")
    stamp = datetime(2026, 10, 31, tzinfo=UTC)
    try:
        await a.store(_decision("z", "keep", stamp))
        await a.store(_decision("a", "keep", stamp))
        await a.store(_decision("m", "bookkeep", stamp + timedelta(minutes=1)))
        await b.store(_decision("b-private", "keep", stamp + timedelta(minutes=2)))

        page = await a.list_items(limit=1, type_filter=MemoryType.DECISION, tags_filter=["keep"])
        assert [m.id for m in page] == ["a"]
        next_page = await a.list_items(
            limit=1, offset=1, type_filter=MemoryType.DECISION, tags_filter=["keep"]
        )
        assert [m.id for m in next_page] == ["z"]
        assert await a.list_items(limit=2, tags_filter=["missing"]) == []
        assert [m.id for m in await b.list_items(tags_filter=["keep"])] == ["b-private"]
    finally:
        await a.close()
        await b.close()
