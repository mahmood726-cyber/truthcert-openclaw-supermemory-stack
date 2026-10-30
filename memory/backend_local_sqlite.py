"""
Local SQLite backend with FTS5 for memory storage.
Append-only with compaction support.
"""

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fts5_sanitizer import sanitize_fts5_query
from .schema import (
    MemoryItem,
    MemorySensitivity,
    MemorySource,
    MemoryStats,
    MemoryType,
    RecallResult,
)


class LocalSQLiteBackend:
    """
    SQLite + FTS5 backend for local-first memory storage.

    Features:
    - Full-text search with FTS5
    - Append-only writes with soft deletes
    - Compaction support
    - Content-addressed deduplication
    """

    def __init__(self, db_path: str = "./memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with context management."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Main memory items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    deleted INTEGER DEFAULT 0
                )
            """)

            # FTS5 virtual table for full-text search
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id,
                    text,
                    tags,
                    content='memory_items',
                    content_rowid='rowid'
                )
            """)

            # Triggers to keep FTS in sync
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_items BEGIN
                    INSERT INTO memory_fts(rowid, id, text, tags)
                    VALUES (new.rowid, new.id, new.text, new.tags);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_items BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, id, text, tags)
                    VALUES ('delete', old.rowid, old.id, old.text, old.tags);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_items BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, id, text, tags)
                    VALUES ('delete', old.rowid, old.id, old.text, old.tags);
                    INSERT INTO memory_fts(rowid, id, text, tags)
                    VALUES (new.rowid, new.id, new.text, new.tags);
                END
            """)

            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_items(source)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_items(created_at_utc)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_items(content_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_deleted ON memory_items(deleted)
            """)

    def store(self, item: MemoryItem) -> str:
        """
        Store a memory item.

        Returns:
            The item ID
        """
        # Generate ID if not provided
        if not item.id:
            item.id = str(uuid.uuid4())

        content_hash = item.compute_hash()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check for duplicate content
            cursor.execute(
                "SELECT id FROM memory_items WHERE content_hash = ? AND deleted = 0",
                (content_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                existing_id = existing["id"]
                if not isinstance(existing_id, str):
                    raise TypeError("Invalid memory identifier in database")
                return existing_id

            # Insert new item
            cursor.execute(
                """
                INSERT INTO memory_items (
                    id, created_at_utc, updated_at_utc, type, source,
                    tags, text, metadata, sensitivity, retention, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item.id,
                    item.created_at_utc.isoformat(),
                    item.updated_at_utc.isoformat(),
                    item.type.value,
                    item.source.value,
                    json.dumps(item.tags),
                    item.text,
                    json.dumps(item.metadata),
                    item.sensitivity.value,
                    json.dumps(item.retention.model_dump()),
                    content_hash,
                ),
            )

        return item.id

    def retrieve(self, item_id: str) -> MemoryItem | None:
        """Retrieve a memory item by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memory_items WHERE id = ? AND deleted = 0", (item_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_item(row)
            return None

    def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: MemoryType | None = None,
        source_filter: MemorySource | None = None,
        tags_filter: list[str] | None = None,
        include_deleted: bool = False,
    ) -> RecallResult:
        """
        Search memory items using FTS5.

        Args:
            query: Search query (will be sanitized for safety)
            limit: Maximum results
            type_filter: Filter by type
            source_filter: Filter by source
            tags_filter: Filter by tags (any match)
            include_deleted: Include soft-deleted items
        """
        import time

        # SQLite interprets negative LIMIT values as unbounded; refuse them
        # before constructing any query against private memory records.
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")

        start_time = time.perf_counter()

        # Sanitize query to prevent FTS5 injection
        safe_query = sanitize_fts5_query(query)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build query
            sql = """
                SELECT m.*, bm25(memory_fts) as rank
                FROM memory_items m
                JOIN memory_fts ON m.id = memory_fts.id
                WHERE memory_fts MATCH ?
            """
            params: list[Any] = [safe_query]

            if not include_deleted:
                sql += " AND m.deleted = 0"

            if type_filter:
                sql += " AND m.type = ?"
                params.append(type_filter.value)

            if source_filter:
                sql += " AND m.source = ?"
                params.append(source_filter.value)

            if tags_filter:
                tag_conditions = " OR ".join(["m.tags LIKE ? ESCAPE '\\'" for _ in tags_filter])
                sql += f" AND ({tag_conditions})"
                # Escape SQL LIKE wildcards properly (don't remove them, escape them)
                # This allows literal % and _ in tag names
                escaped_tags = [
                    tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    for tag in tags_filter
                ]
                params.extend(f"%{tag}%" for tag in escaped_tags)

            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            items = [self._row_to_item(row) for row in rows]

            # Get total count
            count_sql = """
                SELECT COUNT(*) FROM memory_items m
                JOIN memory_fts ON m.id = memory_fts.id
                WHERE memory_fts MATCH ?
            """
            if not include_deleted:
                count_sql += " AND m.deleted = 0"

            cursor.execute(count_sql, [safe_query])
            total = cursor.fetchone()[0]

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return RecallResult(
            items=items,
            query=query,
            total_matches=total,
            execution_time_ms=elapsed_ms,
            db_hash=self.compute_db_hash(),
            selection_rule=f"FTS5 match (sanitized), limit={limit}",
        )

    def list_items(
        self,
        limit: int = 100,
        offset: int = 0,
        type_filter: MemoryType | None = None,
        include_deleted: bool = False,
    ) -> list[MemoryItem]:
        """List memory items with pagination."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            sql = "SELECT * FROM memory_items WHERE 1=1"
            params: list[Any] = []

            if not include_deleted:
                sql += " AND deleted = 0"

            if type_filter:
                sql += " AND type = ?"
                params.append(type_filter.value)

            sql += " ORDER BY created_at_utc DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            return [self._row_to_item(row) for row in rows]

    def delete(self, item_id: str, hard: bool = False) -> bool:
        """
        Delete a memory item.

        Args:
            item_id: ID to delete
            hard: If True, permanently delete. Otherwise soft delete.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if hard:
                cursor.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            else:
                cursor.execute(
                    "UPDATE memory_items SET deleted = 1, updated_at_utc = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), item_id),
                )

            return cursor.rowcount > 0

    def delete_by_query(self, query: str, hard: bool = False) -> int:
        """Delete items matching a search query."""
        results = self.search(query, limit=10000)
        count = 0
        for item in results.items:
            if self.delete(item.id, hard=hard):
                count += 1
        return count

    def wipe(self, confirm: bool = False) -> bool:
        """
        Wipe all memory data.

        Args:
            confirm: Must be True to proceed
        """
        if not confirm:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_items")
            cursor.execute("DELETE FROM memory_fts")

        return True

    def get_stats(self) -> MemoryStats:
        """Get memory statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total items
            cursor.execute("SELECT COUNT(*) FROM memory_items WHERE deleted = 0")
            total_items = cursor.fetchone()[0]

            # Total bytes (approximate)
            cursor.execute("SELECT SUM(LENGTH(text)) FROM memory_items WHERE deleted = 0")
            total_bytes = cursor.fetchone()[0] or 0

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) FROM memory_items
                WHERE deleted = 0 GROUP BY type
            """)
            items_by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # By source
            cursor.execute("""
                SELECT source, COUNT(*) FROM memory_items
                WHERE deleted = 0 GROUP BY source
            """)
            items_by_source = {row[0]: row[1] for row in cursor.fetchall()}

            # Date range
            cursor.execute("""
                SELECT MIN(created_at_utc), MAX(created_at_utc)
                FROM memory_items WHERE deleted = 0
            """)
            dates = cursor.fetchone()
            oldest = datetime.fromisoformat(dates[0]) if dates[0] else None
            newest = datetime.fromisoformat(dates[1]) if dates[1] else None

        return MemoryStats(
            total_items=total_items,
            total_bytes=total_bytes,
            items_by_type=items_by_type,
            items_by_source=items_by_source,
            oldest_item_date=oldest,
            newest_item_date=newest,
            db_hash=self.compute_db_hash(),
        )

    def compute_db_hash(self) -> str:
        """Compute a hash representing current DB state."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, content_hash FROM memory_items
                WHERE deleted = 0 ORDER BY id
            """)
            rows = cursor.fetchall()

            content = json.dumps([(r[0], r[1]) for r in rows], sort_keys=True)
            return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        """Convert a database row to a MemoryItem."""
        from .schema import RetentionPolicy

        return MemoryItem(
            id=row["id"],
            created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
            updated_at_utc=datetime.fromisoformat(row["updated_at_utc"]),
            type=MemoryType(row["type"]),
            source=MemorySource(row["source"]),
            tags=json.loads(row["tags"]),
            text=row["text"],
            metadata=json.loads(row["metadata"]),
            sensitivity=MemorySensitivity(row["sensitivity"]),
            retention=RetentionPolicy(**json.loads(row["retention"])),
        )

    def compact(self, remove_deleted: bool = True) -> int:
        """
        Compact the database.

        Args:
            remove_deleted: Remove soft-deleted items

        Returns:
            Number of items removed
        """
        count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if remove_deleted:
                cursor.execute("SELECT COUNT(*) FROM memory_items WHERE deleted = 1")
                count = cursor.fetchone()[0]
                cursor.execute("DELETE FROM memory_items WHERE deleted = 1")

            # Rebuild FTS
            cursor.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

        # SQLite VACUUM cannot run inside the transaction opened by DELETE
        # or the FTS5 rebuild. The context manager commits that work first;
        # run VACUUM on a separate connection without a pending transaction.
        with self._get_connection() as conn:
            conn.execute("VACUUM")

        return count
