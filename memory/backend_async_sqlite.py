"""
Async SQLite backend with FTS5 for memory storage.
Uses aiosqlite for non-blocking database operations in async applications.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar

import aiosqlite

from .fts5_sanitizer import sanitize_fts5_query
from .scope import enforce_store_scope, scope_clause, validate_project_id
from .schema import (
    MemoryItem,
    MemorySensitivity,
    MemorySource,
    MemoryStats,
    MemoryType,
    RecallResult,
    RetentionPolicy,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _serialized_write(
    operation: Callable[Concatenate[AsyncLocalSQLiteBackend, _P], Awaitable[_R]],
) -> Callable[Concatenate[AsyncLocalSQLiteBackend, _P], Awaitable[_R]]:
    """Serialize writes without sacrificing concurrent reads or hiding SQLite errors."""

    @wraps(operation)
    async def guarded(
        self: AsyncLocalSQLiteBackend,
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        async with self._write_lock:
            return await operation(self, *args, **kwargs)

    return guarded


class AsyncLocalSQLiteBackend:
    """
    Async SQLite + FTS5 backend for memory storage.

    Features:
    - Non-blocking async operations via aiosqlite
    - Full-text search with FTS5
    - Append-only writes with soft deletes
    - Connection pooling
    - Content-addressed deduplication
    """

    def __init__(
        self, db_path: str = "./memory.db", pool_size: int = 5, *, project_id: str = "__legacy__"
    ) -> None:
        self.project_id = validate_project_id(project_id)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.pool_size = pool_size
        self._pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the schema exactly once even with concurrent first-use calls."""
        async with self._init_lock:
            if self._initialized:
                return

            # WAL is a persistent database setting; set it once, not every time
            # a parallel reader opens a connection (which can lock on Windows).
            async with aiosqlite.connect(str(self.db_path), timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA journal_mode=WAL")
                await self._init_schema(conn)

            self._initialized = True

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get a connection from the pool or create a new one."""
        async with self._pool_lock:
            if self._pool:
                return self._pool.pop()

        conn = await aiosqlite.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    async def _return_connection(self, conn: aiosqlite.Connection) -> None:
        """Return a connection to the pool."""
        async with self._pool_lock:
            if len(self._pool) < self.pool_size:
                self._pool.append(conn)
            else:
                await conn.close()

    async def close(self) -> None:
        """Close all connections in the pool."""
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        """Initialize database schema."""
        cursor = await conn.cursor()

        # Main memory items table
        await cursor.execute("""
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
        await cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                id,
                text,
                tags,
                content='memory_items',
                content_rowid='rowid'
            )
        """)

        # Triggers to keep FTS in sync
        await cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_items BEGIN
                INSERT INTO memory_fts(rowid, id, text, tags)
                VALUES (new.rowid, new.id, new.text, new.tags);
            END
        """)

        await cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_items BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, id, text, tags)
                VALUES ('delete', old.rowid, old.id, old.text, old.tags);
            END
        """)

        await cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_items BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, id, text, tags)
                VALUES ('delete', old.rowid, old.id, old.text, old.tags);
                INSERT INTO memory_fts(rowid, id, text, tags)
                VALUES (new.rowid, new.id, new.text, new.tags);
            END
        """)

        # Indexes
        await cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(type)
        """)
        await cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_items(source)
        """)
        await cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_items(created_at_utc)
        """)
        await cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_items(content_hash)
        """)
        await cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_deleted ON memory_items(deleted)
        """)

        await conn.commit()

    @_serialized_write
    async def store(self, item: MemoryItem) -> str:
        """
        Store a memory item asynchronously.

        Returns:
            The item ID
        """
        if not self._initialized:
            await self.initialize()

        enforce_store_scope(item, self.project_id)

        # Generate ID if not provided
        if not item.id:
            item.id = str(uuid.uuid4())

        content_hash = item.compute_hash()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            # The hash is content-addressed, not a complete provenance identity.
            # Compare every active candidate before reusing an ID, including
            # privacy and retention fields. Keep historical hashes unchanged.
            await cursor.execute(
                f"""SELECT * FROM memory_items
                   WHERE content_hash = ? AND deleted = 0
                   AND {scope_clause()} ORDER BY id""",
                (content_hash, self.project_id),
            )
            for existing in await cursor.fetchall():
                stored = self._row_to_item(existing)
                if stored.same_dedup_identity(item):
                    return stored.id

            # Insert new item
            await cursor.execute(
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

            await conn.commit()
            return item.id
        finally:
            await self._return_connection(conn)

    async def retrieve(self, item_id: str) -> MemoryItem | None:
        """Retrieve a memory item by ID asynchronously."""
        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()
            await cursor.execute(
                f"SELECT * FROM memory_items WHERE id = ? AND deleted = 0 "
                f"AND {scope_clause()}",
                (item_id, self.project_id),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_item(row)
            return None
        finally:
            await self._return_connection(conn)

    async def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: MemoryType | None = None,
        source_filter: MemorySource | None = None,
        tags_filter: list[str] | None = None,
        include_deleted: bool = False,
    ) -> RecallResult:
        """
        Search memory items using FTS5 asynchronously.

        Args:
            query: Search query (will be sanitized)
            limit: Maximum results
            type_filter: Filter by type
            source_filter: Filter by source
            tags_filter: Filter by tags (any match)
            include_deleted: Include soft-deleted items
        """
        # Keep the asynchronous path as strict as the synchronous backend:
        # SQLite's negative LIMIT otherwise returns an unbounded result set.
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")

        if not self._initialized:
            await self.initialize()

        import time

        start_time = time.perf_counter()

        # Sanitize query to prevent FTS5 injection
        safe_query = sanitize_fts5_query(query)

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            # Build query
            sql = """
                SELECT m.*, bm25(memory_fts) as rank
                FROM memory_items m
                JOIN memory_fts ON m.id = memory_fts.id
                WHERE memory_fts MATCH ?
            """
            sql += f" AND {scope_clause('m.')}"
            params: list[Any] = [safe_query, self.project_id]

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

            # Derive the total from exactly the same scoped and typed filters.
            # Snapshot the bound parameters before LIMIT is appended.
            count_sql = sql.replace(
                "SELECT m.*, bm25(memory_fts) as rank",
                "SELECT COUNT(*)",
                1,
            )
            count_params = params.copy()
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            await cursor.execute(sql, params)
            rows = await cursor.fetchall()

            items = [self._row_to_item(row) for row in rows]

            # Total reflects project, type, source and tag filters, not just FTS.
            await cursor.execute(count_sql, count_params)
            total_row = await cursor.fetchone()
            if total_row is None:
                raise RuntimeError("Missing aggregate database row")
            total = total_row[0]

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return RecallResult(
                items=items,
                query=query,
                total_matches=total,
                execution_time_ms=elapsed_ms,
                db_hash=await self.compute_db_hash(),
                selection_rule=f"FTS5 match (sanitized), limit={limit}",
            )
        finally:
            await self._return_connection(conn)

    async def list_items(
        self,
        limit: int = 100,
        offset: int = 0,
        type_filter: MemoryType | None = None,
        include_deleted: bool = False,
    ) -> list[MemoryItem]:
        """List memory items with pagination asynchronously."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")

        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            sql = f"SELECT * FROM memory_items WHERE {scope_clause()}"
            params: list[Any] = [self.project_id]

            if not include_deleted:
                sql += " AND deleted = 0"

            if type_filter:
                sql += " AND type = ?"
                params.append(type_filter.value)

            sql += " ORDER BY created_at_utc DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            await cursor.execute(sql, params)
            rows = await cursor.fetchall()

            return [self._row_to_item(row) for row in rows]
        finally:
            await self._return_connection(conn)

    @_serialized_write
    async def delete(self, item_id: str, hard: bool = False) -> bool:
        """
        Delete a memory item asynchronously.

        Args:
            item_id: ID to delete
            hard: If True, permanently delete. Otherwise soft delete.
        """
        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            if hard:
                await cursor.execute(
                    f"DELETE FROM memory_items WHERE id = ? AND {scope_clause()}",
                    (item_id, self.project_id),
                )
            else:
                await cursor.execute(
                    f"UPDATE memory_items SET deleted = 1, updated_at_utc = ? "
                    f"WHERE id = ? AND {scope_clause()}",
                    (datetime.now(UTC).isoformat(), item_id, self.project_id),
                )

            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await self._return_connection(conn)

    @_serialized_write
    async def wipe(self, confirm: bool = False) -> bool:
        """
        Wipe all memory data asynchronously.

        Args:
            confirm: Must be True to proceed
        """
        if not confirm:
            return False

        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()
            # SQLite table triggers update FTS without removing other scopes.
            await cursor.execute(
                f"DELETE FROM memory_items WHERE {scope_clause()}",
                (self.project_id,),
            )
            await conn.commit()
            return True
        finally:
            await self._return_connection(conn)

    async def get_stats(self) -> MemoryStats:
        """Get memory statistics asynchronously."""
        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            # Total items
            await cursor.execute(
                f"SELECT COUNT(*) FROM memory_items "
                f"WHERE deleted = 0 AND {scope_clause()}",
                (self.project_id,),
            )
            total_row = await cursor.fetchone()
            if total_row is None:
                raise RuntimeError("Missing aggregate database row")
            total_items = total_row[0]

            # Total bytes (approximate)
            await cursor.execute(
                f"SELECT SUM(LENGTH(text)) FROM memory_items "
                f"WHERE deleted = 0 AND {scope_clause()}",
                (self.project_id,),
            )
            bytes_row = await cursor.fetchone()
            if bytes_row is None:
                raise RuntimeError("Missing aggregate database row")
            total_bytes = bytes_row[0] or 0

            # By type
            await cursor.execute(
                f"""SELECT type, COUNT(*) FROM memory_items
                WHERE deleted = 0 AND {scope_clause()} GROUP BY type""",
                (self.project_id,),
            )
            items_by_type = {row[0]: row[1] for row in await cursor.fetchall()}

            # By source
            await cursor.execute(
                f"""SELECT source, COUNT(*) FROM memory_items
                WHERE deleted = 0 AND {scope_clause()} GROUP BY source""",
                (self.project_id,),
            )
            items_by_source = {row[0]: row[1] for row in await cursor.fetchall()}

            # Date range
            await cursor.execute(
                f"""SELECT MIN(created_at_utc), MAX(created_at_utc)
                FROM memory_items WHERE deleted = 0 AND {scope_clause()}""",
                (self.project_id,),
            )
            dates = await cursor.fetchone()
            if dates is None:
                raise RuntimeError("Missing aggregate database row")
            oldest = datetime.fromisoformat(dates[0]) if dates[0] else None
            newest = datetime.fromisoformat(dates[1]) if dates[1] else None

            return MemoryStats(
                total_items=total_items,
                total_bytes=total_bytes,
                items_by_type=items_by_type,
                items_by_source=items_by_source,
                oldest_item_date=oldest,
                newest_item_date=newest,
                db_hash=await self.compute_db_hash(),
            )
        finally:
            await self._return_connection(conn)

    async def compute_db_hash(self) -> str:
        """Compute a hash representing current DB state asynchronously."""
        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()
            await cursor.execute(
                f"""SELECT id, content_hash FROM memory_items
                WHERE deleted = 0 AND {scope_clause()} ORDER BY id""",
                (self.project_id,),
            )
            rows = await cursor.fetchall()

            content = json.dumps([(r[0], r[1]) for r in rows], sort_keys=True)
            return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        finally:
            await self._return_connection(conn)

    @_serialized_write
    async def compact(self, remove_deleted: bool = True) -> int:
        """
        Compact the database asynchronously.

        Args:
            remove_deleted: Remove soft-deleted items

        Returns:
            Number of items removed
        """
        if not self._initialized:
            await self.initialize()

        count = 0
        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            if remove_deleted:
                await cursor.execute(
                    f"SELECT COUNT(*) FROM memory_items "
                    f"WHERE deleted = 1 AND {scope_clause()}",
                    (self.project_id,),
                )
                count_row = await cursor.fetchone()
                if count_row is None:
                    raise RuntimeError("Missing aggregate database row")
                count = count_row[0]
                await cursor.execute(
                    f"DELETE FROM memory_items WHERE deleted = 1 AND {scope_clause()}",
                    (self.project_id,),
                )

            # Rebuild FTS
            await cursor.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

            # Vacuum (must be outside transaction)
            await conn.commit()
            await cursor.execute("VACUUM")

            return count
        finally:
            await self._return_connection(conn)

    def _row_to_item(self, row: aiosqlite.Row) -> MemoryItem:
        """Convert a database row to a MemoryItem."""
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
