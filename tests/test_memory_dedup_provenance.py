"""Synthetic scope, provenance, retention and privacy deduplication regressions."""

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.schema import (
    MemoryItem,
    MemorySensitivity,
    MemorySource,
    MemoryType,
    RetentionPolicy,
)


def _pair(changed_field: str) -> tuple[MemoryItem, MemoryItem]:
    original = MemoryItem(
        type=MemoryType.NOTE,
        source=MemorySource.SYSTEM,
        text="Synthetic evidence-link reminder; never certification evidence.",
        tags=["synthetic", "source-linked"],
        metadata={"project_id": "project-a", "source_sha": "source-revision-1"},
        sensitivity=MemorySensitivity.PRIVATE,
        retention=RetentionPolicy(keep_days=90),
    )
    different = original.model_copy(deep=True)
    if changed_field == "project":
        different.metadata["project_id"] = "project-b"
    elif changed_field == "source_revision":
        different.metadata["source_sha"] = "source-revision-2"
    elif changed_field == "sensitivity":
        different.sensitivity = MemorySensitivity.SECRET
    elif changed_field == "retention":
        different.retention = RetentionPolicy(keep_days=1)
    else:
        raise AssertionError(f"unrecognized test field: {changed_field}")
    assert original.compute_hash() == different.compute_hash()
    return original, different


@pytest.mark.parametrize(
    "changed_field", ["project", "source_revision", "sensitivity", "retention"]
)
def test_local_memory_dedup_cannot_alias_distinct_provenance(memory_db, changed_field: str) -> None:
    original, different = _pair(changed_field)
    first_backend = LocalSQLiteBackend(str(memory_db.db_path), project_id="project-a")
    second_backend = (
        LocalSQLiteBackend(str(memory_db.db_path), project_id="project-b")
        if changed_field == "project"
        else first_backend
    )
    first_id = first_backend.store(original)
    second_id = second_backend.store(different)

    assert first_id != second_id
    first = first_backend.retrieve(first_id)
    second = second_backend.retrieve(second_id)
    assert first is not None and second is not None
    assert first.metadata == original.metadata
    assert second.metadata == different.metadata
    assert first.sensitivity == original.sensitivity
    assert second.sensitivity == different.sensitivity
    assert first.retention == original.retention
    assert second.retention == different.retention
    if changed_field == "project":
        assert first_backend.retrieve(second_id) is None
        assert second_backend.retrieve(first_id) is None

    exact_duplicate = original.model_copy(deep=True)
    exact_duplicate.id = ""
    assert first_backend.store(exact_duplicate) == first_id
    assert first_backend.get_stats().total_items == (1 if changed_field == "project" else 2)
    assert first_backend.delete(first_id)
    assert second_backend.retrieve(second_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_field", ["project", "source_revision", "sensitivity", "retention"]
)
async def test_async_memory_dedup_cannot_alias_distinct_provenance(
    tmp_path, changed_field: str
) -> None:
    db_path = str(tmp_path / "memory_dedup_async.db")
    first_backend = AsyncLocalSQLiteBackend(db_path, project_id="project-a")
    second_backend = (
        AsyncLocalSQLiteBackend(db_path, project_id="project-b")
        if changed_field == "project"
        else first_backend
    )
    try:
        original, different = _pair(changed_field)
        first_id = await first_backend.store(original)
        second_id = await second_backend.store(different)

        assert first_id != second_id
        first = await first_backend.retrieve(first_id)
        second = await second_backend.retrieve(second_id)
        assert first is not None and second is not None
        assert first.metadata == original.metadata
        assert second.metadata == different.metadata
        assert first.sensitivity == original.sensitivity
        assert second.sensitivity == different.sensitivity
        assert first.retention == original.retention
        assert second.retention == different.retention
        if changed_field == "project":
            assert await first_backend.retrieve(second_id) is None
            assert await second_backend.retrieve(first_id) is None

        exact_duplicate = original.model_copy(deep=True)
        exact_duplicate.id = ""
        assert await first_backend.store(exact_duplicate) == first_id
        assert (await first_backend.get_stats()).total_items == (
            1 if changed_field == "project" else 2
        )
        assert await first_backend.delete(first_id)
        assert await second_backend.retrieve(second_id) is not None
    finally:
        await first_backend.close()
        if second_backend is not first_backend:
            await second_backend.close()
