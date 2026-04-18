"""
Memory recall module - search, ranking, and recency bias.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import math

from .schema import (
    MemoryItem,
    MemoryType,
    MemorySource,
    MemoryProfile,
    RecallResult,
)
from .backend_local_sqlite import LocalSQLiteBackend


class MemoryRecall:
    """
    Handles memory recall with search, ranking, and recency bias.

    Features:
    - FTS5-based full-text search
    - Recency weighting
    - Type and source filtering
    - Relevance ranking
    """

    def __init__(
        self,
        backend: LocalSQLiteBackend,
        profile: MemoryProfile,
    ):
        self.backend = backend
        self.profile = profile

    def recall(
        self,
        query: str,
        limit: Optional[int] = None,
        type_filter: Optional[MemoryType] = None,
        source_filter: Optional[MemorySource] = None,
        tags_filter: Optional[list[str]] = None,
        recency_weight: float = 0.3,
        min_relevance: float = 0.0,
    ) -> RecallResult:
        """
        Recall memory items matching a query.

        Args:
            query: Search query
            limit: Maximum results (defaults to profile setting)
            type_filter: Filter by memory type
            source_filter: Filter by memory source
            tags_filter: Filter by tags
            recency_weight: Weight for recency (0-1)
            min_relevance: Minimum relevance score

        Returns:
            RecallResult with matching items
        """
        if not self.profile.auto_recall:
            return RecallResult(
                items=[],
                query=query,
                total_matches=0,
                selection_rule="auto_recall disabled",
            )

        effective_limit = limit or self.profile.max_recall_results

        # Perform search
        result = self.backend.search(
            query=query,
            limit=effective_limit * 2,  # Get more for re-ranking
            type_filter=type_filter,
            source_filter=source_filter,
            tags_filter=tags_filter,
        )

        # Apply recency weighting and re-rank
        if result.items and recency_weight > 0:
            scored_items = []
            now = datetime.now(timezone.utc)

            for item in result.items:
                # Calculate recency score (decay over time)
                age_hours = (now - item.created_at_utc).total_seconds() / 3600
                recency_score = math.exp(-age_hours / (24 * 7))  # Week half-life

                # Combined score (assuming FTS already ranked by relevance)
                # Position-based relevance (earlier = more relevant)
                position = result.items.index(item)
                relevance_score = 1.0 / (1 + position * 0.1)

                combined_score = (
                    (1 - recency_weight) * relevance_score +
                    recency_weight * recency_score
                )

                if combined_score >= min_relevance:
                    scored_items.append((item, combined_score))

            # Sort by combined score
            scored_items.sort(key=lambda x: x[1], reverse=True)

            # Take top results
            result.items = [item for item, _ in scored_items[:effective_limit]]

        result.selection_rule = f"FTS5 + recency_weight={recency_weight}, limit={effective_limit}"

        return result

    def recall_recent(
        self,
        hours: int = 24,
        limit: Optional[int] = None,
        type_filter: Optional[MemoryType] = None,
    ) -> list[MemoryItem]:
        """
        Recall recent memory items.

        Args:
            hours: How many hours back to look
            limit: Maximum results
            type_filter: Filter by type

        Returns:
            List of recent memory items
        """
        effective_limit = limit or self.profile.max_recall_results
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        items = self.backend.list_items(
            limit=effective_limit,
            type_filter=type_filter,
        )

        # Filter by time
        return [
            item for item in items
            if item.created_at_utc >= cutoff
        ]

    def recall_by_type(
        self,
        memory_type: MemoryType,
        limit: Optional[int] = None,
    ) -> list[MemoryItem]:
        """Recall items of a specific type."""
        effective_limit = limit or self.profile.max_recall_results
        return self.backend.list_items(
            limit=effective_limit,
            type_filter=memory_type,
        )

    def recall_decisions(
        self,
        limit: Optional[int] = None,
        tags_filter: Optional[list[str]] = None,
    ) -> list[MemoryItem]:
        """Recall decision items."""
        effective_limit = limit or self.profile.max_recall_results
        items = self.backend.list_items(
            limit=effective_limit,
            type_filter=MemoryType.DECISION,
        )

        if tags_filter:
            items = [
                item for item in items
                if any(tag in item.tags for tag in tags_filter)
            ]

        return items

    def recall_codebase_index(self) -> Optional[MemoryItem]:
        """Recall the most recent codebase index."""
        items = self.backend.list_items(
            limit=1,
            type_filter=MemoryType.CODEBASE_INDEX,
        )
        return items[0] if items else None

    def get_profile_summary(self) -> dict[str, Any]:
        """
        Get a summary for /profile injection.

        Returns key decisions and context for the current session.
        """
        # Get recent decisions
        decisions = self.recall_by_type(MemoryType.DECISION, limit=5)

        # Get codebase index
        codebase = self.recall_codebase_index()

        # Get recent summaries
        summaries = self.recall_by_type(MemoryType.SUMMARY, limit=3)

        return {
            "recent_decisions": [
                {"text": d.text[:200], "tags": d.tags}
                for d in decisions
            ],
            "codebase_indexed": codebase is not None,
            "codebase_path": codebase.metadata.get("repo_path") if codebase else None,
            "summaries": [s.text[:150] for s in summaries],
            "total_memories": self.backend.get_stats().total_items,
        }
