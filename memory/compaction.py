"""
Memory compaction - summarizes old items into stable summaries.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from .backend_local_sqlite import LocalSQLiteBackend
from .schema import (
    MemoryItem,
    MemorySource,
    MemoryType,
)


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
    ):
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
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        # Get all items older than cutoff
        old_items = []
        all_items = self.backend.list_items(limit=10000)
        for item in all_items:
            if item.created_at_utc < cutoff and item.type != MemoryType.SUMMARY:
                old_items.append(item)

        if not old_items:
            return {
                "strategy": "rolling",
                "items_processed": 0,
                "summaries_created": 0,
                "items_removed": 0,
            }

        # Group by window
        windows: dict[str, list[MemoryItem]] = {}
        for item in old_items:
            # Calculate window key
            window_start = item.created_at_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            # Align to window
            days_offset = (window_start - datetime(2020, 1, 1, tzinfo=UTC)).days
            window_num = days_offset // summary_window_days
            window_key = f"window_{window_num}"

            if window_key not in windows:
                windows[window_key] = []
            windows[window_key].append(item)

        summaries_created = 0
        items_removed = 0

        for window_key, window_items in windows.items():
            if len(window_items) < 2:
                continue  # Not worth summarizing

            # Create summary
            summary_text = self._create_summary(window_items)

            if not dry_run:
                # Store summary
                summary_item = MemoryItem(
                    type=MemoryType.SUMMARY,
                    source=MemorySource.SYSTEM,
                    text=summary_text,
                    tags=["compaction", window_key],
                    metadata={
                        "source_count": len(window_items),
                        "source_ids": [i.id for i in window_items],
                        "window_key": window_key,
                    },
                )
                self.backend.store(summary_item)
                summaries_created += 1

                # Remove original items
                for item in window_items:
                    self.backend.delete(item.id, hard=True)
                    items_removed += 1

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
            # Create a single summary of removed items
            summary_text = self._create_summary(items_to_remove)

            summary_item = MemoryItem(
                type=MemoryType.SUMMARY,
                source=MemorySource.SYSTEM,
                text=summary_text,
                tags=["compaction", "threshold"],
                metadata={
                    "source_count": len(items_to_remove),
                    "trigger": "threshold",
                },
            )
            self.backend.store(summary_item)
            summaries_created = 1

            for item in items_to_remove:
                self.backend.delete(item.id, hard=True)
                items_removed += 1

        return {
            "strategy": "threshold",
            "triggered": True,
            "items_processed": len(items_to_remove),
            "summaries_created": summaries_created,
            "items_removed": items_removed,
            "dry_run": dry_run,
        }

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
