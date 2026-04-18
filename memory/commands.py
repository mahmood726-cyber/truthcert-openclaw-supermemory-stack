"""
Memory commands - CLI-style functions for memory operations.
"""

import os
from pathlib import Path
from typing import Any, Optional

from .schema import (
    MemoryItem,
    MemoryType,
    MemorySource,
    MemoryProfile,
    PackedContext,
)
from .backend_local_sqlite import LocalSQLiteBackend
from .capture import MemoryCapture
from .recall import MemoryRecall
from .packer import ContextPacker
from .redaction import Redactor
from .compaction import MemoryCompactor
from .codebase_indexer import CodebaseIndexer


def get_default_db_path() -> str:
    """Get default database path."""
    return os.environ.get("TRUTHCERT_MEMORY_DB", "./memory.db")


def get_default_profile() -> MemoryProfile:
    """Get default memory profile."""
    return MemoryProfile(
        name="default",
        auto_recall=True,
        auto_capture=True,
        max_recall_results=10,
        max_inject_chars=4000,
        redact_before_store=True,
    )


class MemoryCommands:
    """
    High-level memory commands for CLI and API use.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        profile: Optional[MemoryProfile] = None,
    ):
        self.db_path = db_path or get_default_db_path()
        self.profile = profile or get_default_profile()

        self.backend = LocalSQLiteBackend(self.db_path)
        self.redactor = Redactor()
        self.capture = MemoryCapture(self.backend, self.profile, self.redactor)
        self.recall = MemoryRecall(self.backend, self.profile)
        self.packer = ContextPacker(self.backend, self.profile)
        self.compactor = MemoryCompactor(self.backend)
        self.indexer = CodebaseIndexer(self.backend)

    def remember(
        self,
        text: str,
        tags: Optional[list[str]] = None,
        memory_type: str = "note",
    ) -> dict[str, Any]:
        """
        Remember a piece of information.

        Args:
            text: Text to remember
            tags: Tags for the memory
            memory_type: Type of memory (note, decision, runbook)

        Returns:
            Result with memory ID
        """
        # Redact if enabled
        if self.profile.redact_before_store:
            text, redaction_result = self.redactor.redact(text)
        else:
            redaction_result = None

        # Map type string to enum
        type_map = {
            "note": MemoryType.NOTE,
            "decision": MemoryType.DECISION,
            "runbook": MemoryType.RUNBOOK,
        }
        mem_type = type_map.get(memory_type, MemoryType.NOTE)

        item = MemoryItem(
            type=mem_type,
            source=MemorySource.CHAT,
            text=text,
            tags=tags or [],
        )

        item_id = self.backend.store(item)

        return {
            "id": item_id,
            "type": mem_type.value,
            "tags": tags or [],
            "redacted": redaction_result is not None and redaction_result.redactions_made > 0,
        }

    def recall_memories(
        self,
        query: str,
        pack: bool = False,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Recall memories matching a query.

        Args:
            query: Search query
            pack: If True, return packed context
            limit: Maximum results

        Returns:
            Recall results or packed context
        """
        result = self.recall.recall(query, limit=limit)

        if pack:
            packed = self.packer.pack_from_recall(result)
            return {
                "packed": True,
                "content": packed.render(),
                "items_included": packed.items_included,
                "total_chars": packed.total_chars,
                "db_hash": packed.db_hash,
            }

        return {
            "packed": False,
            "items": [
                {
                    "id": item.id,
                    "type": item.type.value,
                    "text": item.text[:200] + "..." if len(item.text) > 200 else item.text,
                    "tags": item.tags,
                    "created_at": item.created_at_utc.isoformat(),
                }
                for item in result.items
            ],
            "total_matches": result.total_matches,
            "execution_time_ms": result.execution_time_ms,
        }

    def forget(
        self,
        item_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Forget memory items.

        Args:
            item_id: Specific item ID to forget
            query: Query to match items to forget

        Returns:
            Result with count of items removed
        """
        if item_id:
            success = self.backend.delete(item_id)
            return {
                "removed": 1 if success else 0,
                "method": "by_id",
            }

        if query:
            count = self.backend.delete_by_query(query)
            return {
                "removed": count,
                "method": "by_query",
                "query": query,
            }

        return {
            "removed": 0,
            "error": "Must provide item_id or query",
        }

    def wipe(self, confirm: bool = False) -> dict[str, Any]:
        """
        Wipe all memory.

        Args:
            confirm: Must be True to proceed

        Returns:
            Result with status
        """
        if not confirm:
            return {
                "wiped": False,
                "error": "Must confirm with --yes flag",
            }

        stats_before = self.backend.get_stats()
        success = self.backend.wipe(confirm=True)

        return {
            "wiped": success,
            "items_removed": stats_before.total_items,
        }

    def get_profile(self) -> dict[str, Any]:
        """
        Get current memory profile and stats.

        Returns:
            Profile summary with stats
        """
        stats = self.backend.get_stats()
        profile_summary = self.recall.get_profile_summary()

        return {
            "profile": self.profile.model_dump(),
            "stats": {
                "total_items": stats.total_items,
                "total_bytes": stats.total_bytes,
                "items_by_type": stats.items_by_type,
            },
            "summary": profile_summary,
        }

    def index_codebase(
        self,
        path: str = ".",
        max_files: int = 400,
    ) -> dict[str, Any]:
        """
        Index a codebase.

        Args:
            path: Path to codebase
            max_files: Maximum files to index

        Returns:
            Index result
        """
        item_id = self.indexer.index_codebase(
            repo_path=path,
            max_files=max_files,
        )

        # Get the stored item
        item = self.backend.retrieve(item_id)

        return {
            "id": item_id,
            "repo_path": item.metadata.get("repo_path") if item else path,
            "repo_hash": item.metadata.get("repo_hash") if item else None,
            "file_count": item.metadata.get("file_count") if item else 0,
        }

    def compact(
        self,
        strategy: str = "rolling",
        max_age_days: int = 30,
    ) -> dict[str, Any]:
        """
        Compact memory.

        Args:
            strategy: Compaction strategy (rolling, threshold)
            max_age_days: For rolling strategy

        Returns:
            Compaction result
        """
        if strategy == "rolling":
            result = self.compactor.compact_rolling(max_age_days=max_age_days)
        elif strategy == "threshold":
            result = self.compactor.compact_threshold()
        else:
            result = {"error": f"Unknown strategy: {strategy}"}

        # Also clean up deleted items
        deleted_cleaned = self.compactor.cleanup_deleted()
        result["deleted_cleaned"] = deleted_cleaned

        return result
