"""Synthetic regression for the rolling-compaction candidate window.

The SQLite backend returns newest rows first. A fixed first-page cap must not
silently exclude older in-scope memories when newer rows fill that page.
This test does not assert certification or validate external evidence.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.compaction import MemoryCompactor
from memory.schema import MemoryItem, MemoryStats


def test_rolling_compaction_sees_old_records_beyond_newest_ten_thousand() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=60)
    current = MemoryItem(id="new", text="synthetic new", created_at_utc=now)
    # Model the backend's documented newest-first order without 10,002 slow
    # disk writes in every Python/Windows CI matrix member.
    items = [current.model_copy(update={"id": f"new-{index}"}) for index in range(10_000)]
    items.extend(
        [
            MemoryItem(id="old-a", text="old canary a", created_at_utc=old),
            MemoryItem(id="old-b", text="old canary b", created_at_utc=old),
        ]
    )

    backend = MagicMock(spec=LocalSQLiteBackend)
    backend.get_stats.return_value = MemoryStats(total_items=len(items))
    backend.list_items.side_effect = lambda *, limit: items[:limit]

    result = MemoryCompactor(backend).compact_rolling(max_age_days=30, dry_run=True)

    assert result["items_processed"] == 2
    assert result["summaries_created"] == 0
    assert result["items_removed"] == 0
    backend.list_items.assert_called_once_with(limit=10_002)
    backend.store.assert_not_called()
    backend.delete.assert_not_called()
