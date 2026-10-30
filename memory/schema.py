"""
Memory schema definitions using Pydantic v2.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import hashlib
import json


class MemoryType(str, Enum):
    """Types of memory items."""
    NOTE = "note"
    DECISION = "decision"
    RUNBOOK = "runbook"
    CODEBASE_INDEX = "codebase_index"
    TRACE = "trace"
    SUMMARY = "summary"


class MemorySensitivity(str, Enum):
    """Sensitivity levels for memory items."""
    PUBLIC = "public"
    PRIVATE = "private"
    SECRET = "secret"


class MemorySource(str, Enum):
    """Source of memory items."""
    CHAT = "chat"
    TOOL = "tool"
    SYSTEM = "system"


class RetentionPolicy(BaseModel):
    """Retention policy for memory items."""
    keep_days: int = Field(default=365, ge=0)
    max_items: int = Field(default=10000, ge=0)
    max_bytes: int = Field(default=100 * 1024 * 1024, ge=0)  # 100MB default


class MemoryItem(BaseModel):
    """A single memory item."""
    id: str = Field(default="", description="Unique identifier")
    created_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    type: MemoryType = MemoryType.NOTE
    source: MemorySource = MemorySource.CHAT
    tags: list[str] = Field(default_factory=list)
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: MemorySensitivity = MemorySensitivity.PRIVATE
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)

    def compute_hash(self) -> str:
        """Compute content hash for this memory item."""
        canonical = json.dumps(
            {
                "type": self.type.value,
                "source": self.source.value,
                "text": self.text,
                "tags": sorted(self.tags),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return f"sha256:{digest}"


class CodebaseIndex(BaseModel):
    """Index of a codebase for memory."""
    repo_path: str
    repo_hash: str = ""
    indexed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    file_count: int = 0
    total_bytes: int = 0
    key_files: list[str] = Field(default_factory=list)
    file_hashes: dict[str, str] = Field(default_factory=dict)
    structure_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryProfile(BaseModel):
    """Configuration profile for memory behavior."""
    name: str
    auto_recall: bool = True
    auto_capture: bool = True
    max_recall_results: int = 10
    max_inject_chars: int = 4000
    profile_frequency: int = 5  # Every N turns inject /profile
    capture_mode: str = "all"  # "all" | "selected"
    capture_tools: list[str] = Field(default_factory=list)
    skip_tools: list[str] = Field(default_factory=list)
    redact_before_store: bool = True
    store_tool_results: bool = True
    store_tool_inputs: bool = True
    allow_remote_backend: bool = False


class MemoryStats(BaseModel):
    """Statistics about memory storage."""
    total_items: int = 0
    total_bytes: int = 0
    items_by_type: dict[str, int] = Field(default_factory=dict)
    items_by_source: dict[str, int] = Field(default_factory=dict)
    oldest_item_date: datetime | None = None
    newest_item_date: datetime | None = None
    db_hash: str = ""


class RecallResult(BaseModel):
    """Result from a memory recall query."""
    items: list[MemoryItem] = Field(default_factory=list)
    query: str = ""
    total_matches: int = 0
    execution_time_ms: float = 0.0
    db_hash: str = ""
    selection_rule: str = ""


class PackedContext(BaseModel):
    """Packed memory context for injection."""
    header: str = ""
    content: str = ""
    footer: str = ""
    total_chars: int = 0
    items_included: int = 0
    db_hash: str = ""
    selection_rule: str = ""

    def render(self) -> str:
        """Render the full packed context."""
        return f"{self.header}\n{self.content}\n{self.footer}"
