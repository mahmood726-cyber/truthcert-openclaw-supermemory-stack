"""
Memory compaction - summarizes old items into stable summaries.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .backend_local_sqlite import LocalSQLiteBackend
from .schema import (
    MemoryItem,
    MemorySensitivity,
    MemorySource,
    MemoryType,
)
from .scope import enforce_store_scope, scoped_sql


class MemoryCompactor:
    """
    Compacts old memory items into summaries.

    Strategies:
    - rolling: Summarize items older than N days into periodic summaries
    - threshold: Summarize when item count exceeds threshold
    - size: Summarize when total size exceeds limit
    """

    def __init__(
        self,
        backend: LocalSQLiteBackend,
    ) -> None:
        self.backend = backend

    def compact_rolling(
        self,
        max_age_days: int = 30,
        summary_window_days: int = 7,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Compact old items using rolling window strategy.

        Args:
            max_age_days: Items older than this are candidates
            summary_window_days: Group items into windows of this size
            dry_run: If True, don't actually modify anything

        Returns:
            Summary of compaction actions
        """
        # Invalid bounds or truthy stand-ins must not trigger destructive writes.
        # In Python bool is an int subclass, so use exact type checks here.
        if type(max_age_days) is not int or max_age_days <= 0:
            raise ValueError("max_age_days must be a positive integer")
        if type(summary_window_days) is not int or summary_window_days <= 0:
            raise ValueError("summary_window_days must be a positive integer")
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")

        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        # These reads may race a writer. The final transaction refuses if
        # the project's state differs from the original scoped fingerprint.
        snapshot = self.backend.get_stats()
        all_items = self.backend.list_items(limit=max(1, snapshot.total_items))
        old_items = [
            item
            for item in all_items
            if item.created_at_utc < cutoff and item.type != MemoryType.SUMMARY
        ]

        if not old_items:
            return {
                "strategy": "rolling",
                "items_processed": 0,
                "summaries_created": 0,
                "items_removed": 0,
            }

        windows: dict[str, list[MemoryItem]] = {}
        for item in old_items:
            window_start = item.created_at_utc.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            days_offset = (window_start - datetime(2020, 1, 1, tzinfo=UTC)).days
            window_key = f"window_{days_offset // summary_window_days}"
            windows.setdefault(window_key, []).append(item)

        groups: list[tuple[MemoryItem, list[MemoryItem]]] = []
        if not dry_run:
            for window_key, window_items in windows.items():
                if len(window_items) < 2:
                    continue
                groups.append(
                    (
                        MemoryItem(
                            type=MemoryType.SUMMARY,
                            source=MemorySource.SYSTEM,
                            sensitivity=self._summary_sensitivity(window_items),
                            text=self._create_summary(window_items),
                            tags=["compaction", window_key],
                            metadata={
                                "source_count": len(window_items),
                                "source_ids": [item.id for item in window_items],
                                "window_key": window_key,
                            },
                        ),
                        window_items,
                    )
                )
        summaries_created, items_removed = self._commit_groups(groups, snapshot.db_hash)

        return {
            "strategy": "rolling",
            "items_processed": len(old_items),
            "summaries_created": summaries_created,
            "items_removed": items_removed,
            "dry_run": dry_run,
        }

    def compact_threshold(
        self,
        max_items: int = 5000,
        target_items: int = 2000,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Compact when item count exceeds threshold.

        Args:
            max_items: Trigger compaction above this count
            target_items: Target count after compaction
            dry_run: If True, don't modify anything

        Returns:
            Summary of compaction actions
        """
        # Prevent inverted/negative targets from deleting nearly all memories.
        # A target must leave room for the replacement summary.
        if type(max_items) is not int or max_items <= 0:
            raise ValueError("max_items must be a positive integer")
        if type(target_items) is not int or not 0 < target_items < max_items:
            raise ValueError("target_items must be a positive integer below max_items")
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")

        stats = self.backend.get_stats()

        if stats.total_items <= max_items:
            return {
                "strategy": "threshold",
                "triggered": False,
                "current_items": stats.total_items,
                "threshold": max_items,
            }

        # Calculate how many to remove
        to_remove = stats.total_items - target_items

        # Get oldest items (excluding summaries)
        all_items = self.backend.list_items(limit=stats.total_items)
        candidates = [item for item in all_items if item.type != MemoryType.SUMMARY]

        # Sort by age (oldest first)
        candidates.sort(key=lambda x: x.created_at_utc)

        # Take oldest items for removal
        items_to_remove = candidates[:to_remove]

        summaries_created = 0
        items_removed = 0

        if items_to_remove and not dry_run:
            summary_item = MemoryItem(
                type=MemoryType.SUMMARY,
                source=MemorySource.SYSTEM,
                sensitivity=self._summary_sensitivity(items_to_remove),
                text=self._create_summary(items_to_remove),
                tags=["compaction", "threshold"],
                metadata={
                    "source_count": len(items_to_remove),
                    "trigger": "threshold",
                },
            )
            summaries_created, items_removed = self._commit_groups(
                [(summary_item, items_to_remove)], stats.db_hash
            )

        return {
            "strategy": "threshold",
            "triggered": True,
            "items_processed": len(items_to_remove),
            "summaries_created": summaries_created,
            "items_removed": items_removed,
            "dry_run": dry_run,
        }

    def _commit_groups(
        self,
        groups: list[tuple[MemoryItem, list[MemoryItem]]],
        expected_db_hash: str,
    ) -> tuple[int, int]:
        """Atomically insert summaries and remove only the sources they describe.

        Fail closed if any active in-project memory changed after the initial
        count/read. An unsigned SQLite fingerprint proves snapshot consistency,
        not authenticity of the underlying sources or model calls. BEGIN IMMEDIATE
        serializes writers and rollback prevents partial loss on any exception.
        """
        if not groups:
            return 0, 0
        if (
            not isinstance(expected_db_hash, str)
            or len(expected_db_hash) != 71
            or not expected_db_hash.startswith("sha256:")
        ):
            raise RuntimeError("Missing memory snapshot fingerprint")

        source_ids: set[str] = set()
        for summary, sources in groups:
            if summary.type != MemoryType.SUMMARY or not sources:
                raise ValueError("Compaction requires a nonempty summary group")
            enforce_store_scope(summary, self.backend.project_id)
            for item in sources:
                if not item.id or item.id in source_ids or item.type == MemoryType.SUMMARY:
                    raise ValueError("Duplicate or invalid compaction source")
                source_ids.add(item.id)

        with self.backend._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self.backend._compute_db_hash_on_connection(conn) != expected_db_hash:
                raise RuntimeError("Memory snapshot changed during compaction")
            cursor = conn.cursor()
            select_sql = scoped_sql(
                "SELECT * FROM memory_items WHERE id = ? AND deleted = 0 "
                "AND /*PROJECT_SCOPE*/"
            )
            for _, sources in groups:
                for item in sources:
                    cursor.execute(select_sql, (item.id, self.backend.project_id))
                    row = cursor.fetchone()
                    if row is None or self.backend._row_to_item(row) != item:
                        raise RuntimeError("Memory source changed during compaction")

            delete_sql = scoped_sql(
                "DELETE FROM memory_items WHERE id = ? AND deleted = 0 "
                "AND /*PROJECT_SCOPE*/"
            )
            for summary, sources in groups:
                summary.id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO memory_items (
                        id, created_at_utc, updated_at_utc, type, source,
                        tags, text, metadata, sensitivity, retention, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary.id,
                        summary.created_at_utc.isoformat(),
                        summary.updated_at_utc.isoformat(),
                        summary.type.value,
                        summary.source.value,
                        json.dumps(summary.tags),
                        summary.text,
                        json.dumps(summary.metadata),
                        summary.sensitivity.value,
                        json.dumps(summary.retention.model_dump()),
                        summary.compute_hash(),
                    ),
                )
                for item in sources:
                    cursor.execute(delete_sql, (item.id, self.backend.project_id))
                    if cursor.rowcount != 1:
                        raise RuntimeError("Memory source disappeared during compaction")

        return len(groups), len(source_ids)

    def cleanup_deleted(self) -> int:
        """Remove soft-deleted items and compact database."""
        return self.backend.compact(remove_deleted=True)

    def get_compaction_stats(self) -> dict[str, Any]:
        """Get statistics relevant to compaction decisions."""
        stats = self.backend.get_stats()

        # Count summaries
        summaries = self.backend.list_items(
            limit=10000,
            type_filter=MemoryType.SUMMARY,
        )

        return {
            "total_items": stats.total_items,
            "total_bytes": stats.total_bytes,
            "summary_count": len(summaries),
            "items_by_type": stats.items_by_type,
            "oldest_item": stats.oldest_item_date.isoformat() if stats.oldest_item_date else None,
            "newest_item": stats.newest_item_date.isoformat() if stats.newest_item_date else None,
        }

    @staticmethod
    def _summary_sensitivity(items: list[MemoryItem]) -> MemorySensitivity:
        """Never downgrade a derived summary below its inputs or the old PRIVATE default.

        Compaction is noncertifying planning context. It may copy excerpts from
        protected inputs, so their SECRET classification must survive derivation.
        """
        if not items:
            raise ValueError("Cannot derive a summary from an empty source list")
        if any(item.sensitivity == MemorySensitivity.SECRET for item in items):
            return MemorySensitivity.SECRET
        return MemorySensitivity.PRIVATE

    def _create_summary(self, items: list[MemoryItem]) -> str:
        """
        Create a text summary of multiple items.

        This is a simple concatenation strategy. Could be enhanced with
        LLM-based summarization.
        """
        # Group by type
        by_type: dict[str, list[str]] = {}
        for item in items:
            type_name = item.type.value
            if type_name not in by_type:
                by_type[type_name] = []
            # Take first 100 chars of each item
            by_type[type_name].append(item.text[:100])

        # Build summary
        parts = [
            (
                f"Compacted {len(items)} items from "
                f"{min(i.created_at_utc for i in items).strftime('%Y-%m-%d')} to "
                f"{max(i.created_at_utc for i in items).strftime('%Y-%m-%d')}"
            ),
        ]

        for type_name, texts in by_type.items():
            parts.append(f"\n{type_name.upper()} ({len(texts)} items):")
            # Include samples
            for text in texts[:3]:
                parts.append(f"  - {text}...")
            if len(texts) > 3:
                parts.append(f"  ... and {len(texts) - 3} more")

        return "\n".join(parts)
