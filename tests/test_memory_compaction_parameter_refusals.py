"""Synthetic fail-closed regressions for destructive memory-compaction controls.

Invalid command values must be refused before any backend read, summary creation,
or deletion. Tests use synthetic memory only; these are not evidence certificates.
"""

from unittest.mock import MagicMock

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.compaction import MemoryCompactor


@pytest.mark.parametrize(
    ("max_items", "target_items"),
    [
        (-1, 1),
        (0, 1),
        (True, 1),
        (2.5, 1),
        (2, -1),
        (2, 0),
        (2, 2),
        (2, 3),
        (2, False),
        (2, 1.5),
    ],
)
def test_invalid_threshold_controls_refuse_before_storage(
    max_items: object, target_items: object
) -> None:
    backend = MagicMock(spec=LocalSQLiteBackend)
    with pytest.raises(ValueError, match="max_items|target_items"):
        MemoryCompactor(backend).compact_threshold(max_items=max_items, target_items=target_items)
    backend.get_stats.assert_not_called()
    backend.list_items.assert_not_called()
    backend.store.assert_not_called()
    backend.delete.assert_not_called()


@pytest.mark.parametrize(
    ("max_age_days", "summary_window_days", "dry_run"),
    [
        (0, 7, False),
        (-1, 7, False),
        (True, 7, False),
        ("30", 7, False),
        (30, 0, False),
        (30, -7, False),
        (30, True, False),
        (30, "7", False),
        (30, 7, "false"),
        (30, 7, 0),
        (30, 7, None),
    ],
)
def test_invalid_rolling_controls_refuse_before_storage(
    max_age_days: object, summary_window_days: object, dry_run: object
) -> None:
    backend = MagicMock(spec=LocalSQLiteBackend)
    with pytest.raises(ValueError, match="max_age_days|summary_window_days|dry_run"):
        MemoryCompactor(backend).compact_rolling(
            max_age_days=max_age_days,
            summary_window_days=summary_window_days,
            dry_run=dry_run,
        )
    backend.get_stats.assert_not_called()
    backend.list_items.assert_not_called()
    backend.store.assert_not_called()
    backend.delete.assert_not_called()


@pytest.mark.parametrize("dry_run", ["false", 0, None, 1])
def test_invalid_threshold_dry_run_refuses_before_storage(dry_run: object) -> None:
    backend = MagicMock(spec=LocalSQLiteBackend)
    with pytest.raises(ValueError, match="dry_run"):
        MemoryCompactor(backend).compact_threshold(max_items=2, target_items=1, dry_run=dry_run)
    backend.get_stats.assert_not_called()
    backend.list_items.assert_not_called()
    backend.store.assert_not_called()
    backend.delete.assert_not_called()
