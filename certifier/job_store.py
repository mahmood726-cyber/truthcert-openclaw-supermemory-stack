"""
SQLite-backed job store for TruthCert certifier.
Provides persistent job storage that survives server restarts.
"""

import json
import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .constants import DEFAULT_DB_PATH, ENV_DB_PATH
from .models import CertificationProfile, Job, JobStatus

# Thread-safe lock for singleton initialization
_singleton_lock = threading.Lock()


class ConnectionPool:
    """
    Thread-safe SQLite connection pool.

    Features:
    - Configurable pool size
    - Connection reuse to reduce overhead
    - Automatic connection cleanup
    - Health checks on checkout
    """

    def __init__(
        self,
        db_path: str,
        pool_size: int = 5,
        timeout: float = 30.0,
    ):
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self._pool: queue.Queue = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created = 0

        # Pre-create connections
        self._initialize_pool()

    def _initialize_pool(self):
        """Pre-create pool connections."""
        for _ in range(min(2, self.pool_size)):  # Start with 2 connections
            self._pool.put(self._create_connection())
            self._created += 1

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimal settings."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,  # Safe with proper locking
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _health_check(self, conn: sqlite3.Connection) -> bool:
        """Check if connection is healthy."""
        try:
            conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool."""
        try:
            conn = self._pool.get_nowait()
            # Health check
            if not self._health_check(conn):
                # If the bad handle cannot be closed, refuse rather than
                # silently continuing with a possibly leaked SQLite lock.
                conn.close()
                conn = self._create_connection()
            return conn
        except queue.Empty:
            # Pool exhausted, create new if under limit
            with self._lock:
                if self._created < self.pool_size:
                    self._created += 1
                    return self._create_connection()
            # Wait for available connection
            return self._pool.get(timeout=self.timeout)

    def return_connection(self, conn: sqlite3.Connection):
        """Return a connection to the pool."""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            # Do not hide failures to release an excess SQLite handle.
            conn.close()

    def close_all(self):
        """Close all connections in the pool."""
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break


class JobStore:
    """
    SQLite-backed persistent job storage.

    Features:
    - Jobs survive server restarts
    - Atomic operations with transactions
    - Automatic schema migrations
    - Connection pooling for high throughput
    - Thread-safe operations
    """

    def __init__(self, db_path: str | None = None, pool_size: int = 5):
        self.db_path = Path(db_path or os.environ.get(ENV_DB_PATH, DEFAULT_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = ConnectionPool(str(self.db_path), pool_size=pool_size)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Get a database connection from pool with context management."""
        conn = self._pool.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.return_connection(conn)

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    input_path TEXT,
                    output_bundle_id TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)

            # Indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_policy ON jobs(policy_id)
            """)

            # Schema version table for migrations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)

            # Apply migrations
            self._apply_migrations(cursor)

    def _apply_migrations(self, cursor):
        """Apply any pending schema migrations."""
        cursor.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        current_version = row[0] if row[0] else 0

        migrations = [
            # Version 1: Initial schema (already created above)
            (1, "-- Initial schema created"),
        ]

        for version, sql in migrations:
            if version > current_version:
                if sql and not sql.startswith("--"):
                    cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(UTC).isoformat()),
                )

    def create(self, job: Job) -> Job:
        """
        Create a new job.

        Args:
            job: Job to create

        Returns:
            Created job
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    job_id, status, policy_id, profile, input_path,
                    output_bundle_id, error_message, created_at,
                    started_at, completed_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    job.job_id,
                    job.status.value,
                    job.policy_id,
                    job.profile.value,
                    job.input_path,
                    job.output_bundle_id,
                    job.error_message,
                    job.created_at.isoformat(),
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                    json.dumps(job.metadata),
                ),
            )

        return job

    def get(self, job_id: str) -> Job | None:
        """
        Get a job by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            Job if found, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_job(row)
            return None

    def update(self, job: Job) -> Job:
        """
        Update an existing job.

        Args:
            job: Job with updated fields

        Returns:
            Updated job
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs SET
                    status = ?,
                    policy_id = ?,
                    profile = ?,
                    input_path = ?,
                    output_bundle_id = ?,
                    error_message = ?,
                    started_at = ?,
                    completed_at = ?,
                    metadata = ?
                WHERE job_id = ?
            """,
                (
                    job.status.value,
                    job.policy_id,
                    job.profile.value,
                    job.input_path,
                    job.output_bundle_id,
                    job.error_message,
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                    json.dumps(job.metadata),
                    job.job_id,
                ),
            )

        return job

    def delete(self, job_id: str) -> bool:
        """
        Delete a job.

        Args:
            job_id: Job ID to delete

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            return cursor.rowcount > 0

    def list_jobs(
        self,
        status: JobStatus | None = None,
        policy_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        """
        List jobs with optional filters.

        Args:
            status: Filter by status
            policy_id: Filter by policy
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of jobs
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            sql = "SELECT * FROM jobs WHERE 1=1"
            params = []

            if status:
                sql += " AND status = ?"
                params.append(status.value)

            if policy_id:
                sql += " AND policy_id = ?"
                params.append(policy_id)

            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            return [self._row_to_job(row) for row in rows]

    def count(self, status: JobStatus | None = None) -> int:
        """
        Count jobs.

        Args:
            status: Optional status filter

        Returns:
            Job count
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if status:
                cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (status.value,))
            else:
                cursor.execute("SELECT COUNT(*) FROM jobs")

            return cursor.fetchone()[0]

    def cleanup_old_jobs(self, days: int = 30) -> int:
        """
        Clean up old completed jobs.

        Args:
            days: Delete jobs older than this many days

        Returns:
            Number of jobs deleted
        """
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM jobs
                WHERE status IN ('completed', 'failed')
                AND created_at < ?
            """,
                (cutoff,),
            )
            return cursor.rowcount

    def close(self) -> None:
        """Close all pooled connections.

        Releases the underlying SQLite file handles. Required for clean
        teardown on platforms (e.g. Windows) where an open handle prevents
        the database file from being deleted.
        """
        self._pool.close_all()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert a database row to a Job."""
        return Job(
            job_id=row["job_id"],
            status=JobStatus(row["status"]),
            policy_id=row["policy_id"],
            profile=CertificationProfile(row["profile"]),
            input_path=row["input_path"],
            output_bundle_id=row["output_bundle_id"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"]
            else None,
            metadata=json.loads(row["metadata"]),
        )


# Global job store instance
_job_store: JobStore | None = None


def get_job_store() -> JobStore:
    """
    Get the global job store instance (thread-safe).

    Uses double-checked locking pattern for thread safety
    without unnecessary lock overhead on hot path.
    """
    global _job_store
    if _job_store is None:
        with _singleton_lock:
            # Double-check after acquiring lock
            if _job_store is None:
                _job_store = JobStore()
    return _job_store


def init_job_store(db_path: str | None = None) -> JobStore:
    """
    Initialize and return the global job store (thread-safe).

    Args:
        db_path: Optional database path override

    Returns:
        Initialized JobStore instance
    """
    global _job_store
    with _singleton_lock:
        # On Windows, overwriting the singleton without closing the old
        # pool leaves open SQLite handles and can lock or leak the old DB.
        # A close failure must prevent replacement, not be ignored.
        if _job_store is not None:
            _job_store.close()
        _job_store = None
        _job_store = JobStore(db_path)
        return _job_store


def reset_job_store() -> None:
    """
    Reset the global job store (for testing only).

    WARNING: This should only be used in test teardown.
    """
    global _job_store
    with _singleton_lock:
        if _job_store is not None:
            # Preserve the reference and surface failures to release DB
            # handles, rather than claiming reset succeeded.
            _job_store.close()
        _job_store = None
