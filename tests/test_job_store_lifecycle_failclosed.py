"""Synthetic regression tests for fail-closed SQLite lifecycle handling.

No patient or private memory data is involved.
"""

import sqlite3

import pytest

from certifier.job_store import (
    ConnectionPool,
    get_job_store,
    init_job_store,
    reset_job_store,
)


def test_reinitialization_releases_old_sqlite_handles(tmp_path):
    """Switching the singleton DB must close the old pool, including on Windows."""
    reset_job_store()
    old_path = tmp_path / "previous.db"
    next_path = tmp_path / "replacement.db"

    try:
        old_store = init_job_store(str(old_path))
        replacement = init_job_store(str(next_path))
        assert replacement is get_job_store()
        assert replacement is not old_store
        assert old_store._pool._pool.empty()
        # Open SQLite handles prevent this deletion on Windows.
        old_path.unlink()
        assert not old_path.exists()
    finally:
        reset_job_store()


def test_failed_reset_preserves_singleton_and_reports_sqlite_error(tmp_path, monkeypatch):
    """A failed close is not a successful reset and must not lose the handle."""
    reset_job_store()
    store = init_job_store(str(tmp_path / "jobs.db"))
    original_close = store.close

    def deny_close():
        raise sqlite3.OperationalError("synthetic close failure")

    monkeypatch.setattr(store, "close", deny_close)
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic close failure"):
            reset_job_store()
        assert get_job_store() is store
    finally:
        monkeypatch.setattr(store, "close", original_close)
        reset_job_store()


def test_unclosable_corrupt_pool_handle_refuses_replacement(tmp_path):
    """A failed health check plus failed close must not silently issue a new handle."""
    pool = ConnectionPool(str(tmp_path / "jobs.db"), pool_size=1)
    healthy = pool._pool.get_nowait()
    healthy.close()

    class CorruptHandle:
        def execute(self, _query):
            raise sqlite3.DatabaseError("synthetic corruption")

        def close(self):
            raise sqlite3.OperationalError("synthetic close failure")

    pool._pool.put_nowait(CorruptHandle())
    with pytest.raises(sqlite3.OperationalError, match="synthetic close failure"):
        pool.get_connection()
    pool.close_all()


def test_full_pool_does_not_swallow_close_failure(tmp_path):
    """Extra SQLite handles must not be silently discarded after close failure."""
    pool = ConnectionPool(str(tmp_path / "jobs.db"), pool_size=1)

    class UnclosableHandle:
        def close(self):
            raise sqlite3.OperationalError("synthetic extra-handle failure")

    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic extra-handle failure"):
            pool.return_connection(UnclosableHandle())
    finally:
        pool.close_all()
