"""
Supermemory - Local-first memory subsystem for TruthCert.

CRITICAL: Memory is NEVER evidence. Memory content cannot be used
to certify numeric claims - it is for planning and context only.
"""

from .backend_local_sqlite import LocalSQLiteBackend
from .backend_remote_stub import RemoteBackendStub
from .capture import MemoryCapture
from .codebase_indexer import CodebaseIndexer
from .compaction import MemoryCompactor
from .fts5_sanitizer import build_safe_fts5_query, escape_fts5_string, sanitize_fts5_query
from .packer import ContextPacker
from .recall import MemoryRecall
from .redaction import RedactionRule, Redactor
from .schema import (
    CodebaseIndex,
    MemoryItem,
    MemoryProfile,
    MemorySensitivity,
    MemorySource,
    MemoryType,
)

# Async backend (requires aiosqlite)
try:
    from .backend_async_sqlite import AsyncLocalSQLiteBackend
except ImportError:
    AsyncLocalSQLiteBackend = None  # aiosqlite not installed

__all__ = [
    "AsyncLocalSQLiteBackend",
    "CodebaseIndex",
    "CodebaseIndexer",
    "ContextPacker",
    # Backends
    "LocalSQLiteBackend",
    # Operations
    "MemoryCapture",
    "MemoryCompactor",
    # Schema
    "MemoryItem",
    "MemoryProfile",
    "MemoryRecall",
    "MemorySensitivity",
    "MemorySource",
    "MemoryType",
    "RedactionRule",
    "Redactor",
    "RemoteBackendStub",
    "build_safe_fts5_query",
    "escape_fts5_string",
    # Security
    "sanitize_fts5_query",
]
