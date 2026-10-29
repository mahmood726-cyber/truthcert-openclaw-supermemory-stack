"""
Tests for async SQLite backend.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from pathlib import Path

from memory.schema import (
    MemoryItem,
    MemoryType,
    MemorySource,
    MemorySensitivity,
    RetentionPolicy,
)
from memory.backend_async_sqlite import AsyncLocalSQLiteBackend


@pytest.fixture
async def async_db(temp_dir):
    """Create a temporary async memory database."""
    db_path = temp_dir / "test_async_memory.db"
    backend = AsyncLocalSQLiteBackend(str(db_path))
    await backend.initialize()
    yield backend
    await backend.close()


@pytest.fixture
def sample_async_memory_item():
    """Create a sample memory item for async tests."""
    return MemoryItem(
        type=MemoryType.NOTE,
        source=MemorySource.CHAT,
        text="This is a test memory note for async testing.",
        tags=["test", "async"],
    )


class TestAsyncStoreRetrieve:
    """Test async store and retrieve operations."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, async_db, sample_async_memory_item):
        """Test storing and retrieving a memory item asynchronously."""
        item_id = await async_db.store(sample_async_memory_item)
        assert item_id

        retrieved = await async_db.retrieve(item_id)
        assert retrieved is not None
        assert retrieved.text == sample_async_memory_item.text
        assert retrieved.type == sample_async_memory_item.type

    @pytest.mark.asyncio
    async def test_store_generates_id(self, async_db):
        """Test that store generates an ID if not provided."""
        item = MemoryItem(
            type=MemoryType.NOTE,
            text="No ID provided",
        )
        assert not item.id or item.id == ""

        item_id = await async_db.store(item)
        assert item_id
        assert len(item_id) > 0

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent(self, async_db):
        """Test retrieving a nonexistent item returns None."""
        result = await async_db.retrieve("nonexistent-id-12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_content_deduplication(self, async_db):
        """Test that duplicate content is deduplicated."""
        item1 = MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Duplicate content test",
            tags=["test"],
        )
        item2 = MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Duplicate content test",
            tags=["test"],
        )

        id1 = await async_db.store(item1)
        id2 = await async_db.store(item2)

        # Should return same ID for duplicate content
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_store_with_all_fields(self, async_db):
        """Test storing an item with all fields populated."""
        item = MemoryItem(
            type=MemoryType.DECISION,
            source=MemorySource.SYSTEM,
            text="Complete item with all fields",
            tags=["complete", "test"],
            metadata={"key": "value"},
            sensitivity=MemorySensitivity.PRIVATE,
            retention=RetentionPolicy(keep_days=30, max_items=100),
        )

        item_id = await async_db.store(item)
        retrieved = await async_db.retrieve(item_id)

        assert retrieved.type == MemoryType.DECISION
        assert retrieved.source == MemorySource.SYSTEM
        assert retrieved.tags == ["complete", "test"]
        assert retrieved.metadata == {"key": "value"}
        assert retrieved.sensitivity == MemorySensitivity.PRIVATE


class TestAsyncSearch:
    """Test async search functionality."""

    @pytest.mark.asyncio
    async def test_search_fts(self, async_db):
        """Test FTS5 search functionality."""
        # Store items
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Meta-analysis of RCT data shows significant effect",
            tags=["meta-analysis", "rct"],
        ))
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Heterogeneity was assessed using I-squared",
            tags=["heterogeneity"],
        ))

        # Search
        result = await async_db.search("meta-analysis")
        assert result.total_matches >= 1
        assert any("meta-analysis" in item.text.lower() for item in result.items)

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, async_db):
        """Test search with type filter."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            text="A searchable note",
        ))
        await async_db.store(MemoryItem(
            type=MemoryType.DECISION,
            text="A searchable decision",
        ))

        result = await async_db.search("searchable", type_filter=MemoryType.DECISION)
        assert all(item.type == MemoryType.DECISION for item in result.items)

    @pytest.mark.asyncio
    async def test_search_with_source_filter(self, async_db):
        """Test search with source filter."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Chat source item",
        ))
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.SYSTEM,
            text="System source item",
        ))

        result = await async_db.search("source", source_filter=MemorySource.SYSTEM)
        assert all(item.source == MemorySource.SYSTEM for item in result.items)

    @pytest.mark.asyncio
    async def test_search_with_tags_filter(self, async_db):
        """Test search with tags filter."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            text="Item with special tag",
            tags=["special", "unique"],
        ))
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            text="Item without special tag",
            tags=["normal"],
        ))

        result = await async_db.search("Item", tags_filter=["special"])
        assert any("special" in item.tags for item in result.items)

    @pytest.mark.asyncio
    async def test_search_tag_filter_treats_like_wildcards_literally(self, async_db):
        """Literal percent and underscore in tags must not match other tag names."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Synthetic distinctive alpha memory",
            tags=["phase%_checkpoint"],
        ))
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text="Synthetic distinctive beta memory",
            tags=["phaseX_checkpoint"],
        ))

        result = await async_db.search(
            "Synthetic", tags_filter=["phase%_checkpoint"],
        )
        assert [item.text for item in result.items] == [
            "Synthetic distinctive alpha memory",
        ]

    @pytest.mark.asyncio
    async def test_search_limit(self, async_db):
        """Test search respects limit parameter."""
        # Store many items
        for i in range(10):
            await async_db.store(MemoryItem(
                type=MemoryType.NOTE,
                text=f"Searchable item number {i}",
            ))

        result = await async_db.search("Searchable", limit=3)
        assert len(result.items) <= 3

    @pytest.mark.asyncio
    async def test_search_returns_execution_time(self, async_db):
        """Test search returns execution time."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            text="Timing test item",
        ))

        result = await async_db.search("Timing")
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_search_include_deleted(self, async_db):
        """Test search can include deleted items."""
        item = MemoryItem(
            type=MemoryType.NOTE,
            text="Soon to be deleted item",
        )
        item_id = await async_db.store(item)
        await async_db.delete(item_id, hard=False)

        # Should not find by default
        result = await async_db.search("deleted", include_deleted=False)
        assert not any(item.id == item_id for item in result.items)

        # Should find when include_deleted is True
        result = await async_db.search("deleted", include_deleted=True)
        assert any("deleted" in item.text.lower() for item in result.items)


class TestAsyncDelete:
    """Test async delete operations."""

    @pytest.mark.asyncio
    async def test_soft_delete(self, async_db, sample_async_memory_item):
        """Test soft delete (default)."""
        item_id = await async_db.store(sample_async_memory_item)
        assert await async_db.retrieve(item_id) is not None

        success = await async_db.delete(item_id, hard=False)
        assert success

        # Should not be retrievable after soft delete
        retrieved = await async_db.retrieve(item_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_hard_delete(self, async_db, sample_async_memory_item):
        """Test hard delete."""
        item_id = await async_db.store(sample_async_memory_item)

        success = await async_db.delete(item_id, hard=True)
        assert success

        retrieved = await async_db.retrieve(item_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, async_db):
        """Test deleting nonexistent item."""
        success = await async_db.delete("nonexistent-id")
        assert not success


class TestAsyncListItems:
    """Test async list items functionality."""

    @pytest.mark.asyncio
    async def test_list_items_basic(self, async_db):
        """Test basic list items."""
        # Store items
        await async_db.store(MemoryItem(type=MemoryType.NOTE, text="Item 1"))
        await async_db.store(MemoryItem(type=MemoryType.NOTE, text="Item 2"))

        items = await async_db.list_items()
        assert len(items) >= 2

    @pytest.mark.asyncio
    async def test_list_items_with_pagination(self, async_db):
        """Test list items with pagination."""
        # Store items
        for i in range(5):
            await async_db.store(MemoryItem(
                type=MemoryType.NOTE,
                text=f"Paginated item {i}",
            ))

        # Get first page
        items1 = await async_db.list_items(limit=2, offset=0)
        assert len(items1) == 2

        # Get second page
        items2 = await async_db.list_items(limit=2, offset=2)
        assert len(items2) == 2

        # Check they are different
        ids1 = {item.id for item in items1}
        ids2 = {item.id for item in items2}
        assert not ids1.intersection(ids2)

    @pytest.mark.asyncio
    async def test_list_items_with_type_filter(self, async_db):
        """Test list items with type filter."""
        await async_db.store(MemoryItem(type=MemoryType.NOTE, text="Note"))
        await async_db.store(MemoryItem(type=MemoryType.DECISION, text="Decision"))

        items = await async_db.list_items(type_filter=MemoryType.DECISION)
        assert all(item.type == MemoryType.DECISION for item in items)


class TestAsyncStats:
    """Test async statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, async_db):
        """Test getting memory statistics."""
        await async_db.store(MemoryItem(type=MemoryType.NOTE, text="Note 1"))
        await async_db.store(MemoryItem(type=MemoryType.DECISION, text="Decision 1"))

        stats = await async_db.get_stats()
        assert stats.total_items == 2
        assert "note" in stats.items_by_type or "NOTE" in stats.items_by_type

    @pytest.mark.asyncio
    async def test_stats_total_bytes(self, async_db):
        """Test total bytes in stats."""
        await async_db.store(MemoryItem(
            type=MemoryType.NOTE,
            text="A" * 1000,  # 1000 character text
        ))

        stats = await async_db.get_stats()
        assert stats.total_bytes >= 1000


class TestAsyncWipe:
    """Test async wipe functionality."""

    @pytest.mark.asyncio
    async def test_wipe_requires_confirmation(self, async_db, sample_async_memory_item):
        """Test wipe requires confirmation."""
        await async_db.store(sample_async_memory_item)

        # Should fail without confirmation
        result = await async_db.wipe(confirm=False)
        assert not result

        # Should still have items
        stats = await async_db.get_stats()
        assert stats.total_items >= 1

    @pytest.mark.asyncio
    async def test_wipe_with_confirmation(self, async_db, sample_async_memory_item):
        """Test wipe with confirmation."""
        await async_db.store(sample_async_memory_item)

        result = await async_db.wipe(confirm=True)
        assert result

        stats = await async_db.get_stats()
        assert stats.total_items == 0


class TestAsyncCompact:
    """Test async compaction."""

    @pytest.mark.asyncio
    async def test_compact_removes_deleted(self, async_db, sample_async_memory_item):
        """Test compaction removes soft-deleted items."""
        item_id = await async_db.store(sample_async_memory_item)
        await async_db.delete(item_id, hard=False)

        removed = await async_db.compact(remove_deleted=True)
        assert removed >= 1


class TestAsyncConcurrentOperations:
    """Test concurrent async operations."""

    @pytest.mark.asyncio
    async def test_concurrent_stores(self, async_db):
        """Test concurrent store operations."""
        items = [
            MemoryItem(
                type=MemoryType.NOTE,
                text=f"Concurrent item {i}",
                tags=[f"concurrent-{i}"],
            )
            for i in range(10)
        ]

        # Store concurrently
        tasks = [async_db.store(item) for item in items]
        ids = await asyncio.gather(*tasks)

        assert len(ids) == 10
        assert all(item_id is not None for item_id in ids)

        # Verify all were stored
        stats = await async_db.get_stats()
        assert stats.total_items >= 10

    @pytest.mark.asyncio
    async def test_concurrent_reads(self, async_db):
        """Test concurrent read operations."""
        # Store some items first
        ids = []
        for i in range(5):
            item_id = await async_db.store(MemoryItem(
                type=MemoryType.NOTE,
                text=f"Readable item {i}",
            ))
            ids.append(item_id)

        # Read concurrently
        tasks = [async_db.retrieve(item_id) for item_id in ids]
        items = await asyncio.gather(*tasks)

        assert len(items) == 5
        assert all(item is not None for item in items)

    @pytest.mark.asyncio
    async def test_concurrent_searches(self, async_db):
        """Test concurrent search operations."""
        # Store items
        for i in range(5):
            await async_db.store(MemoryItem(
                type=MemoryType.NOTE,
                text=f"Searchable concurrent item {i}",
            ))

        # Search concurrently
        queries = ["Searchable", "concurrent", "item"]
        tasks = [async_db.search(q) for q in queries]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        assert all(r.total_matches >= 1 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self, async_db):
        """Test concurrent mixed operations."""
        # Store initial items
        stored_ids = []
        for i in range(3):
            item_id = await async_db.store(MemoryItem(
                type=MemoryType.NOTE,
                text=f"Mixed operation item {i}",
            ))
            stored_ids.append(item_id)

        # Mix of operations
        tasks = [
            async_db.store(MemoryItem(type=MemoryType.NOTE, text="New item")),
            async_db.retrieve(stored_ids[0]),
            async_db.search("Mixed"),
            async_db.get_stats(),
            async_db.list_items(limit=5),
        ]

        results = await asyncio.gather(*tasks)

        # Check all operations completed
        assert len(results) == 5
        assert results[0] is not None  # store returned ID
        assert results[1] is not None  # retrieve returned item
        assert results[2].total_matches >= 1  # search found items
        assert results[3].total_items >= 3  # stats shows items
        assert len(results[4]) >= 3  # list returned items


    @pytest.mark.asyncio
    async def test_parallel_first_use_deduplicates_without_lock_errors(self, temp_dir):
        """First-use concurrent writers must not race schema, WAL or deduplication."""
        import sqlite3
        from contextlib import closing

        db_path = temp_dir / "parallel_first_use.db"
        backend = AsyncLocalSQLiteBackend(str(db_path), pool_size=2)
        items = [
            MemoryItem(type=MemoryType.NOTE, text="Synthetic concurrent duplicate")
            for _ in range(10)
        ] + [
            MemoryItem(type=MemoryType.NOTE, text=f"Synthetic unique item {i}")
            for i in range(10)
        ]
        try:
            ids = await asyncio.gather(*(backend.store(item) for item in items))
            assert len(set(ids[:10])) == 1
            assert len(set(ids[10:])) == 10
            assert (await backend.get_stats()).total_items == 11

            # A concurrent mutation/read must leave the database valid.
            deleted, retrieved = await asyncio.gather(
                backend.delete(ids[0]), backend.retrieve(ids[10]),
            )
            assert deleted is True
            assert retrieved is not None
            assert (await backend.get_stats()).total_items == 10
        finally:
            await backend.close()

        # In particular on Windows, all pooled handles must be released.
        # sqlite3.Connection's context manager commits but does not close:
        # Windows cannot clean the temporary directory until the handle closes.
        with closing(sqlite3.connect(str(db_path))) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


class TestAsyncDbHash:
    """Test database hash computation."""

    @pytest.mark.asyncio
    async def test_compute_db_hash(self, async_db, sample_async_memory_item):
        """Test database hash computation."""
        await async_db.store(sample_async_memory_item)

        hash1 = await async_db.compute_db_hash()
        assert hash1.startswith("sha256:")
        assert len(hash1) > 10

    @pytest.mark.asyncio
    async def test_db_hash_changes_on_modification(self, async_db, sample_async_memory_item):
        """Test that database hash changes when data changes."""
        await async_db.store(sample_async_memory_item)
        hash1 = await async_db.compute_db_hash()

        await async_db.store(MemoryItem(type=MemoryType.NOTE, text="New item"))
        hash2 = await async_db.compute_db_hash()

        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_db_hash_deterministic(self, async_db, sample_async_memory_item):
        """Test that database hash is deterministic."""
        await async_db.store(sample_async_memory_item)

        hash1 = await async_db.compute_db_hash()
        hash2 = await async_db.compute_db_hash()

        assert hash1 == hash2


class TestAsyncConnectionPooling:
    """Test connection pool behavior."""

    @pytest.mark.asyncio
    async def test_pool_reuse(self, temp_dir):
        """Test that connections are reused from pool."""
        db_path = temp_dir / "pool_test.db"
        backend = AsyncLocalSQLiteBackend(str(db_path), pool_size=2)
        await backend.initialize()

        try:
            # Perform operations that would use connections
            for i in range(5):
                await backend.store(MemoryItem(
                    type=MemoryType.NOTE,
                    text=f"Pool test item {i}",
                ))

            # Should not have created more than pool_size connections
            # (pool management should work)
            stats = await backend.get_stats()
            assert stats.total_items >= 5
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_multiple_backends_same_db(self, temp_dir):
        """Test multiple backends accessing same database."""
        db_path = temp_dir / "shared_test.db"

        backend1 = AsyncLocalSQLiteBackend(str(db_path))
        await backend1.initialize()

        backend2 = AsyncLocalSQLiteBackend(str(db_path))
        await backend2.initialize()

        try:
            # Write from backend1
            item_id = await backend1.store(MemoryItem(
                type=MemoryType.NOTE,
                text="Shared database item",
            ))

            # Read from backend2
            item = await backend2.retrieve(item_id)
            assert item is not None
            assert item.text == "Shared database item"
        finally:
            await backend1.close()
            await backend2.close()
