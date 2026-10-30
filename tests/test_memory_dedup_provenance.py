"""Synthetic regression tests for memory deduplication identity boundaries.

Content equality is not sufficient to merge records with different provenance,
scope, sensitivity, or retention. Memory remains noncertifying context.
"""

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
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
    first_id = memory_db.store(original)
    second_id = memory_db.store(different)

    assert first_id != second_id
    first = memory_db.retrieve(first_id)
    second = memory_db.retrieve(second_id)
    assert first is not None and second is not None
    assert first.metadata == original.metadata
    assert second.metadata == different.metadata
    assert first.sensitivity == original.sensitivity
    assert second.sensitivity == different.sensitivity
    assert first.retention == original.retention
    assert second.retention == different.retention

    exact_duplicate = original.model_copy(deep=True)
    exact_duplicate.id = ""
    assert memory_db.store(exact_duplicate) == first_id
    assert memory_db.get_stats().total_items == 2
    assert memory_db.delete(first_id)
    assert memory_db.retrieve(second_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_field", ["project", "source_revision", "sensitivity", "retention"]
)
async def test_async_memory_dedup_cannot_alias_distinct_provenance(
    tmp_path, changed_field: str
) -> None:
    backend = AsyncLocalSQLiteBackend(str(tmp_path / "memory_dedup_async.db"))
    try:
        original, different = _pair(changed_field)
        first_id = await backend.store(original)
        second_id = await backend.store(different)

        assert first_id != second_id
        first = await backend.retrieve(first_id)
        second = await backend.retrieve(second_id)
        assert first is not None and second is not None
        assert first.metadata == original.metadata
        assert second.metadata == different.metadata
        assert first.sensitivity == original.sensitivity
        assert second.sensitivity == different.sensitivity
        assert first.retention == original.retention
        assert second.retention == different.retention

        exact_duplicate = original.model_copy(deep=True)
        exact_duplicate.id = ""
        assert await backend.store(exact_duplicate) == first_id
        assert (await backend.get_stats()).total_items == 2
        assert await backend.delete(first_id)
        assert await backend.retrieve(second_id) is not None
    finally:
        await backend.close()
