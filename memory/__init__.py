"""
Supermemory - Local-first memory subsystem for TruthCert.

CRITICAL: Memory is NEVER evidence. Memory content cannot be used
to certify numeric claims - it is for planning and context only.
"""

from .schema import (
    MemoryItem,
    MemoryType,
    MemorySensitivity,
    MemorySource,
    CodebaseIndex,
    MemoryProfile,
)
from .backend_local_sqlite import LocalSQLiteBackend
from .backend_remote_stub import RemoteBackendStub
from .capture import MemoryCapture
from .recall import MemoryRecall
from .packer import ContextPacker
from .redaction import Redactor, RedactionRule
from .compaction import MemoryCompactor
from .codebase_indexer import CodebaseIndexer
from .fts5_sanitizer import sanitize_fts5_query, escape_fts5_string, build_safe_fts5_query

# Async backend (requires aiosqlite)
try:
    from .backend_async_sqlite import AsyncLocalSQLiteBackend
except ImportError:
    AsyncLocalSQLiteBackend = None  # aiosqlite not installed

__all__ = [
    # Schema
    "MemoryItem",
    "MemoryType",
    "MemorySensitivity",
    "MemorySource",
    "CodebaseIndex",
    "MemoryProfile",
    # Backends
    "LocalSQLiteBackend",
    "AsyncLocalSQLiteBackend",
    "RemoteBackendStub",
    # Operations
    "MemoryCapture",
    "MemoryRecall",
    "ContextPacker",
    "Redactor",
    "RedactionRule",
    "MemoryCompactor",
    "CodebaseIndexer",
    # Security
    "sanitize_fts5_query",
    "escape_fts5_string",
    "build_safe_fts5_query",
]
