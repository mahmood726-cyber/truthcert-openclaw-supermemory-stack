"""
Tests for memory subsystem.
"""

from memory.packer import ContextPacker, verify_packing_determinism
from memory.recall import MemoryRecall
from memory.redaction import Redactor
from memory.schema import MemoryItem, MemorySource, MemoryType


class TestMemoryBackend:
    """Test memory storage backend."""

    def test_store_and_retrieve(self, memory_db, sample_memory_item):
        """Test storing and retrieving a memory item."""
        item_id = memory_db.store(sample_memory_item)
        assert item_id

        retrieved = memory_db.retrieve(item_id)
        assert retrieved is not None
        assert retrieved.text == sample_memory_item.text
        assert retrieved.type == sample_memory_item.type

    def test_search_fts(self, memory_db):
        """Test FTS5 search functionality."""
        # Store items
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                source=MemorySource.CHAT,
                text="Meta-analysis of RCT data shows significant effect",
                tags=["meta-analysis", "rct"],
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                source=MemorySource.CHAT,
                text="Heterogeneity was assessed using I-squared",
                tags=["heterogeneity"],
            )
        )

        # Search
        result = memory_db.search("meta-analysis")
        assert result.total_matches >= 1
        assert any("meta-analysis" in item.text.lower() for item in result.items)

    def test_delete_item(self, memory_db, sample_memory_item):
        """Test deleting a memory item."""
        item_id = memory_db.store(sample_memory_item)
        assert (
            memory_db.exists(item_id)
            if hasattr(memory_db, "exists")
            else memory_db.retrieve(item_id) is not None
        )

        success = memory_db.delete(item_id)
        assert success

        # Should not be retrievable after delete
        retrieved = memory_db.retrieve(item_id)
        assert retrieved is None

    def test_wipe(self, memory_db, sample_memory_item):
        """Test wiping all memory."""
        memory_db.store(sample_memory_item)
        memory_db.store(
            MemoryItem(
                type=MemoryType.DECISION,
                source=MemorySource.SYSTEM,
                text="Another item",
            )
        )

        stats_before = memory_db.get_stats()
        assert stats_before.total_items >= 2

        memory_db.wipe(confirm=True)

        stats_after = memory_db.get_stats()
        assert stats_after.total_items == 0

    def test_stats(self, memory_db):
        """Test getting memory statistics."""
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Note 1",
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.DECISION,
                text="Decision 1",
            )
        )

        stats = memory_db.get_stats()
        assert stats.total_items == 2
        assert "note" in stats.items_by_type or "NOTE" in stats.items_by_type

    def test_compact_after_soft_delete_preserves_live_search(self, memory_db):
        """Compaction must commit FTS changes before VACUUM, without losing live memory."""
        removed = memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                source=MemorySource.CHAT,
                text="Synthetic removed observation",
            )
        )
        retained = memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                source=MemorySource.CHAT,
                text="Synthetic retained observation",
            )
        )

        assert memory_db.delete(removed)
        assert memory_db.compact(remove_deleted=True) == 1
        assert memory_db.retrieve(removed) is None
        assert memory_db.retrieve(retained) is not None
        assert memory_db.search("removed").items == []
        assert any(item.id == retained for item in memory_db.search("retained").items)


class TestRedaction:
    """Test redaction functionality."""

    def test_redact_api_key(self):
        """Test redacting API keys."""
        redactor = Redactor()
        text = "My API key is api_key=sk_live_abcd1234567890abcdef"
        redacted, result = redactor.redact(text)

        assert "sk_live" not in redacted
        assert "REDACTED" in redacted
        assert result.redactions_made > 0

    def test_redact_password(self):
        """Test redacting passwords."""
        redactor = Redactor()
        text = "password=mysecretpassword123"
        redacted, result = redactor.redact(text)

        assert "mysecretpassword" not in redacted
        assert result.redactions_made > 0

    def test_redact_bearer_token(self):
        """Test redacting bearer tokens."""
        redactor = Redactor()
        text = (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        )
        redacted, result = redactor.redact(text)

        assert "eyJ" not in redacted
        assert result.redactions_made > 0

    def test_no_false_positives(self):
        """Test that normal text is not redacted."""
        redactor = Redactor()
        text = "The effect size was 0.45 with 95% CI [0.25, 0.65]"
        redacted, result = redactor.redact(text)

        assert redacted == text
        assert result.redactions_made == 0


class TestPacker:
    """Test context packing."""

    def test_pack_items(self, memory_db, memory_profile):
        """Test packing memory items."""
        # Store items
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="First note",
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.DECISION,
                text="First decision",
            )
        )

        packer = ContextPacker(memory_db, memory_profile)
        items = memory_db.list_items()
        packed = packer.pack(items)

        assert packed.items_included > 0
        assert "MEMORY CONTEXT" in packed.header
        assert "NOT evidence" in packed.header
        assert packed.content

    def test_packing_determinism(self, memory_db, memory_profile):
        """Test that packing is deterministic."""
        # Store items
        for i in range(5):
            memory_db.store(
                MemoryItem(
                    type=MemoryType.NOTE,
                    text=f"Note {i}",
                )
            )

        packer = ContextPacker(memory_db, memory_profile)
        items = memory_db.list_items()

        is_deterministic = verify_packing_determinism(packer, items)
        assert is_deterministic

    def test_character_limit(self, memory_db, memory_profile):
        """Test that character limit is respected."""
        # Store a large item
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="x" * 10000,
            )
        )

        packer = ContextPacker(memory_db, memory_profile)
        items = memory_db.list_items()
        packed = packer.pack(items, max_chars=500)

        # Header includes warning that memory is not evidence (~320 chars)
        # Footer includes reminder (~165 chars)
        # Plus provenance line and content
        # Total overhead is ~635 chars, so max_chars=500 -> ~1135 total
        assert packed.total_chars <= 1200  # Header + content + footer


class TestRecall:
    """Test memory recall functionality."""

    def test_recall_with_query(self, memory_db, memory_profile):
        """Test recall with search query."""
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Publication bias analysis using funnel plots",
                tags=["bias", "funnel"],
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Heterogeneity assessment with I-squared",
                tags=["heterogeneity"],
            )
        )

        recall = MemoryRecall(memory_db, memory_profile)
        result = recall.recall("bias")

        assert result.total_matches >= 1

    def test_recall_by_type(self, memory_db, memory_profile):
        """Test recall filtered by type."""
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="A note",
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.DECISION,
                text="A decision",
            )
        )

        recall = MemoryRecall(memory_db, memory_profile)
        items = recall.recall_by_type(MemoryType.DECISION)

        assert all(item.type == MemoryType.DECISION for item in items)


class TestTagFiltering:
    """Test tag filtering with special characters."""

    def test_tags_with_percent_sign(self, memory_db):
        """Test that tags with % are properly escaped in LIKE queries."""
        # Store item with tag containing %
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Test item with special tag",
                tags=["100%_complete", "status"],
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Another item without percent",
                tags=["other"],
            )
        )

        # Search with tag filter - should find the item with % in tag
        result = memory_db.search("Test", tags_filter=["100%_complete"])
        assert len(result.items) >= 1
        assert any("100%_complete" in item.tags for item in result.items)

    def test_tags_with_underscore(self, memory_db):
        """Test that tags with _ are properly escaped in LIKE queries."""
        # Store item with tag containing _
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Test item with underscore",
                tags=["meta_analysis", "research"],
            )
        )
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Another item",
                tags=["metaXanalysis"],  # Similar but different
            )
        )

        # Search with tag filter - should match exact underscore
        result = memory_db.search("Test", tags_filter=["meta_analysis"])
        # Should find at least the first item
        assert any("meta_analysis" in item.tags for item in result.items)

    def test_tags_sql_injection_prevention(self, memory_db):
        """Test that tag filters don't allow SQL injection."""
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                text="Safe item",
                tags=["safe"],
            )
        )

        # Try SQL injection via tag filter - should not crash or expose data
        result = memory_db.search("Safe", tags_filter=["'; DROP TABLE memory_items; --"])
        # Sanitization must complete; unexpected errors must fail this security test.
        assert result is not None
