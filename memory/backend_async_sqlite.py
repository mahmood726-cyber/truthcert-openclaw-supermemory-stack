"""
Async SQLite backend with FTS5 for memory storage.
Uses aiosqlite for non-blocking database operations in async applications.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

from .schema import (
    MemoryItem,
    MemoryType,
    MemorySensitivity,
    MemorySource,
    MemoryStats,
    RecallResult,
    RetentionPolicy,
)
from .fts5_sanitizer import sanitize_fts5_query


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

    def __init__(self, db_path: str = "./memory.db", pool_size: int = 5):
        if aiosqlite is None:
            raise ImportError(
                "aiosqlite is required for async operations. "
                "Install with: pip install aiosqlite"
            )
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.pool_size = pool_size
        self._pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Initialize the database and connection pool."""
        if self._initialized:
            return

        # Create initial connection to set up schema
        async with aiosqlite.connect(str(self.db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            await self._init_schema(conn)

        self._initialized = True

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get a connection from the pool or create a new one."""
        async with self._pool_lock:
            if self._pool:
                return self._pool.pop()

        conn = await aiosqlite.connect(str(self.db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    async def _return_connection(self, conn: aiosqlite.Connection):
        """Return a connection to the pool."""
        async with self._pool_lock:
            if len(self._pool) < self.pool_size:
                self._pool.append(conn)
            else:
                await conn.close()

    async def close(self):
        """Close all connections in the pool."""
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()

    async def _init_schema(self, conn: aiosqlite.Connection):
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

    async def store(self, item: MemoryItem) -> str:
        """
        Store a memory item asynchronously.

        Returns:
            The item ID
        """
        if not self._initialized:
            await self.initialize()

        # Generate ID if not provided
        if not item.id:
            item.id = str(uuid.uuid4())

        content_hash = item.compute_hash()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            # Check for duplicate content
            await cursor.execute(
                "SELECT id FROM memory_items WHERE content_hash = ? AND deleted = 0",
                (content_hash,)
            )
            existing = await cursor.fetchone()
            if existing:
                return existing["id"]

            # Insert new item
            await cursor.execute("""
                INSERT INTO memory_items (
                    id, created_at_utc, updated_at_utc, type, source,
                    tags, text, metadata, sensitivity, retention, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
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
            ))

            await conn.commit()
            return item.id
        finally:
            await self._return_connection(conn)

    async def retrieve(self, item_id: str) -> Optional[MemoryItem]:
        """Retrieve a memory item by ID asynchronously."""
        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT * FROM memory_items WHERE id = ? AND deleted = 0",
                (item_id,)
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
        type_filter: Optional[MemoryType] = None,
        source_filter: Optional[MemorySource] = None,
        tags_filter: Optional[list[str]] = None,
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
                params.extend([
                    f"%{tag.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
                    for tag in tags_filter
                ])

            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            await cursor.execute(sql, params)
            rows = await cursor.fetchall()

            items = [self._row_to_item(row) for row in rows]

            # Get total count
            count_sql = """
                SELECT COUNT(*) FROM memory_items m
                JOIN memory_fts ON m.id = memory_fts.id
                WHERE memory_fts MATCH ?
            """
            if not include_deleted:
                count_sql += " AND m.deleted = 0"

            await cursor.execute(count_sql, [safe_query])
            total_row = await cursor.fetchone()
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
        type_filter: Optional[MemoryType] = None,
        include_deleted: bool = False,
    ) -> list[MemoryItem]:
        """List memory items with pagination asynchronously."""
        if not self._initialized:
            await self.initialize()

        conn = await self._get_connection()
        try:
            cursor = await conn.cursor()

            sql = "SELECT * FROM memory_items WHERE 1=1"
            params: list[Any] = []

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
                await cursor.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            else:
                await cursor.execute(
                    "UPDATE memory_items SET deleted = 1, updated_at_utc = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), item_id)
                )

            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await self._return_connection(conn)

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
            await cursor.execute("DELETE FROM memory_items")
            await cursor.execute("DELETE FROM memory_fts")
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
            await cursor.execute("SELECT COUNT(*) FROM memory_items WHERE deleted = 0")
            total_items = (await cursor.fetchone())[0]

            # Total bytes (approximate)
            await cursor.execute("SELECT SUM(LENGTH(text)) FROM memory_items WHERE deleted = 0")
            total_bytes = (await cursor.fetchone())[0] or 0

            # By type
            await cursor.execute("""
                SELECT type, COUNT(*) FROM memory_items
                WHERE deleted = 0 GROUP BY type
            """)
            items_by_type = {row[0]: row[1] for row in await cursor.fetchall()}

            # By source
            await cursor.execute("""
                SELECT source, COUNT(*) FROM memory_items
                WHERE deleted = 0 GROUP BY source
            """)
            items_by_source = {row[0]: row[1] for row in await cursor.fetchall()}

            # Date range
            await cursor.execute("""
                SELECT MIN(created_at_utc), MAX(created_at_utc)
                FROM memory_items WHERE deleted = 0
            """)
            dates = await cursor.fetchone()
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
            await cursor.execute("""
                SELECT id, content_hash FROM memory_items
                WHERE deleted = 0 ORDER BY id
            """)
            rows = await cursor.fetchall()

            content = json.dumps([(r[0], r[1]) for r in rows], sort_keys=True)
            return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        finally:
            await self._return_connection(conn)

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
                await cursor.execute("SELECT COUNT(*) FROM memory_items WHERE deleted = 1")
                count = (await cursor.fetchone())[0]
                await cursor.execute("DELETE FROM memory_items WHERE deleted = 1")

            # Rebuild FTS
            await cursor.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

            # Vacuum (must be outside transaction)
            await conn.commit()
            await cursor.execute("VACUUM")

            return count
        finally:
            await self._return_connection(conn)

    def _row_to_item(self, row) -> MemoryItem:
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
