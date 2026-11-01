"""
Memory recall module - search, ranking, and recency bias.
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from .backend_local_sqlite import LocalSQLiteBackend
from .schema import MemoryItem, MemoryProfile, MemorySource, MemoryType, RecallResult


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
    ) -> None:
        self.backend = backend
        self.profile = profile

    def recall(
        self,
        query: str,
        limit: int | None = None,
        type_filter: MemoryType | None = None,
        source_filter: MemorySource | None = None,
        tags_filter: list[str] | None = None,
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

        effective_limit = self.profile.max_recall_results if limit is None else limit
        if (
            isinstance(effective_limit, bool)
            or not isinstance(effective_limit, int)
            or effective_limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        if not math.isfinite(recency_weight) or not 0.0 <= recency_weight <= 1.0:
            raise ValueError("recency_weight must be finite and between 0 and 1")
        if not math.isfinite(min_relevance) or not 0.0 <= min_relevance <= 1.0:
            raise ValueError("min_relevance must be finite and between 0 and 1")

        # Perform search
        result = self.backend.search(
            query=query,
            limit=effective_limit * 2,  # Get more for re-ranking
            type_filter=type_filter,
            source_filter=source_filter,
            tags_filter=tags_filter,
            # This is automatic, potentially prompt-injected context. Explicit
            # authorized SECRET reads remain available on the direct backend.
            exclude_secret=True,
        )

        # Always enforce the requested limit and relevance threshold. A
        # zero recency weight must not expose the over-fetched candidate set.
        if result.items:
            scored_items = []
            now = datetime.now(UTC)

            for position, item in enumerate(result.items):
                # Future-dated records cannot receive an above-one recency score.
                age_hours = max(0.0, (now - item.created_at_utc).total_seconds() / 3600)
                recency_score = math.exp(-age_hours / (24 * 7))

                # FTS has already ordered candidates by relevance.
                relevance_score = 1.0 / (1 + position * 0.1)
                combined_score = (
                    1 - recency_weight
                ) * relevance_score + recency_weight * recency_score

                if combined_score >= min_relevance:
                    scored_items.append((item, combined_score))

            scored_items.sort(key=lambda pair: pair[1], reverse=True)
            result.items = [item for item, _ in scored_items[:effective_limit]]

        result.selection_rule = (
            f"FTS5 + recency_weight={recency_weight}, limit={effective_limit}, SECRET excluded"
        )

        return result

    def _validated_list_limit(self, limit: int | None) -> int:
        """Refuse SQLite-unbounded and noninteger limits on every recall path."""
        effective_limit = self.profile.max_recall_results if limit is None else limit
        if (
            isinstance(effective_limit, bool)
            or not isinstance(effective_limit, int)
            or effective_limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        return effective_limit

    def recall_recent(
        self,
        hours: int = 24,
        limit: int | None = None,
        type_filter: MemoryType | None = None,
    ) -> list[MemoryItem]:
        """Recall recent non-SECRET items for automatic planning context."""
        effective_limit = self._validated_list_limit(limit)
        if isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
            raise ValueError("hours must be a positive integer")
        if not self.profile.auto_recall:
            return []

        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        items = self.backend.list_items(
            limit=effective_limit,
            type_filter=type_filter,
            # Apply privacy filtering before LIMIT, never to an already
            # truncated page; callers needing SECRET use the direct backend.
            exclude_secret=True,
        )
        return [item for item in items if item.created_at_utc >= cutoff]

    def recall_by_type(
        self,
        memory_type: MemoryType,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        """Recall non-SECRET items of a type for automatic planning context."""
        effective_limit = self._validated_list_limit(limit)
        if not self.profile.auto_recall:
            return []
        return self.backend.list_items(
            limit=effective_limit,
            type_filter=memory_type,
            exclude_secret=True,
        )

    def recall_decisions(
        self,
        limit: int | None = None,
        tags_filter: list[str] | None = None,
    ) -> list[MemoryItem]:
        """Recall non-SECRET decisions with filtering before pagination."""
        effective_limit = self._validated_list_limit(limit)
        if not self.profile.auto_recall:
            return []
        return self.backend.list_items(
            limit=effective_limit,
            type_filter=MemoryType.DECISION,
            tags_filter=tags_filter,
            exclude_secret=True,
        )

    def recall_codebase_index(self) -> MemoryItem | None:
        """Recall the most recent non-SECRET codebase index."""
        if not self.profile.auto_recall:
            return None
        items = self.backend.list_items(
            limit=1,
            type_filter=MemoryType.CODEBASE_INDEX,
            exclude_secret=True,
        )
        return items[0] if items else None

    def get_profile_summary(self) -> dict[str, Any]:
        """
        Get a summary for /profile injection.

        Returns key decisions and context for the current session.
        """
        # /profile is automatic injection, not an explicitly authorized
        # SECRET read. Enforce the class before pagination so newer SECRET
        # records cannot hide older usable context.
        decisions = self.backend.list_items(
            limit=5, type_filter=MemoryType.DECISION, exclude_secret=True
        )
        codebase_candidates = self.backend.list_items(
            limit=1, type_filter=MemoryType.CODEBASE_INDEX, exclude_secret=True
        )
        codebase = codebase_candidates[0] if codebase_candidates else None
        summaries = self.backend.list_items(
            limit=3, type_filter=MemoryType.SUMMARY, exclude_secret=True
        )

        return {
            "recent_decisions": [{"text": d.text[:200], "tags": d.tags} for d in decisions],
            "codebase_indexed": codebase is not None,
            "codebase_path": codebase.metadata.get("repo_path") if codebase else None,
            "summaries": [s.text[:150] for s in summaries],
            "total_memories": self.backend.get_stats().total_items,
        }
