"""Synthetic fail-closed tests for memory retrieval bounds.

Memories are planning context, never evidence for certification.
"""

import json
from pathlib import Path

import pytest

from memory.recall import MemoryRecall
from memory.schema import MemoryItem, MemorySource, MemoryType


@pytest.fixture
def synthetic_memories(memory_db):
    for number in range(4):
        memory_db.store(
            MemoryItem(
                type=MemoryType.NOTE,
                source=MemorySource.CHAT,
                text=f"Synthetic corpus note {number} distinct",
            )
        )
    return memory_db


@pytest.mark.parametrize("invalid_limit", [-2, 0, True])
def test_sqlite_search_refuses_nonpositive_or_boolean_limits(synthetic_memories, invalid_limit):
    with pytest.raises(ValueError, match="positive integer"):
        synthetic_memories.search("Synthetic", limit=invalid_limit)


@pytest.mark.parametrize("invalid_limit", [-2, 0, True])
def test_recall_refuses_nonpositive_or_boolean_limits(
    synthetic_memories, memory_profile, invalid_limit
):
    recall = MemoryRecall(synthetic_memories, memory_profile)
    with pytest.raises(ValueError, match="positive integer"):
        recall.recall("Synthetic", limit=invalid_limit)


def test_zero_recency_weight_cannot_double_requested_recall_limit(
    synthetic_memories, memory_profile
):
    recall = MemoryRecall(synthetic_memories, memory_profile)
    result = recall.recall("Synthetic", limit=1, recency_weight=0)
    assert result.total_matches == 4
    assert len(result.items) == 1


def test_zero_recency_weight_still_applies_relevance_threshold(
    synthetic_memories, memory_profile
):
    recall = MemoryRecall(synthetic_memories, memory_profile)
    result = recall.recall("Synthetic", limit=4, recency_weight=0, min_relevance=0.99)
    assert len(result.items) == 1


@pytest.mark.parametrize("invalid_weight", [-0.1, 1.1, float("nan"), float("inf")])
def test_recall_rejects_invalid_recency_weights(
    synthetic_memories, memory_profile, invalid_weight
):
    recall = MemoryRecall(synthetic_memories, memory_profile)
    with pytest.raises(ValueError, match="recency_weight"):
        recall.recall("Synthetic", recency_weight=invalid_weight)


@pytest.mark.parametrize("invalid_threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_recall_rejects_invalid_relevance_threshold(
    synthetic_memories, memory_profile, invalid_threshold
):
    recall = MemoryRecall(synthetic_memories, memory_profile)
    with pytest.raises(ValueError, match="min_relevance"):
        recall.recall("Synthetic", min_relevance=invalid_threshold)


def test_openclaw_recall_schema_rejects_negative_and_zero_limits():
    path = (
        Path(__file__).resolve().parents[1]
        / "gateway"
        / "openclaw"
        / "tools"
        / "truthcert_memory_recall.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    limit = schema["parameters"]["properties"]["limit"]
    assert limit["type"] == "integer"
    assert limit["minimum"] == 1
    assert limit["maximum"] == 50


@pytest.mark.parametrize("invalid_limit", [-1, 0, True, 1.5])
def test_sqlite_list_items_refuses_unbounded_limit(synthetic_memories, invalid_limit):
    """Listing private memories must not accept SQLite's unlimited LIMIT -1."""
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        synthetic_memories.list_items(limit=invalid_limit)


@pytest.mark.parametrize("invalid_offset", [-1, True, 1.5])
def test_sqlite_list_items_refuses_invalid_offset(synthetic_memories, invalid_offset):
    with pytest.raises(ValueError, match="offset must be a nonnegative integer"):
        synthetic_memories.list_items(limit=1, offset=invalid_offset)


def test_sqlite_list_items_valid_page_remains_bounded(synthetic_memories):
    first = synthetic_memories.list_items(limit=1, offset=0)
    second = synthetic_memories.list_items(limit=1, offset=1)
    assert len(first) == len(second) == 1
    assert first[0].id != second[0].id
