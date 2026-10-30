"""
Context packer - deterministic injection of memory into prompts.
"""

from typing import Any
import hashlib
import json

from .schema import (
    MemoryItem,
    MemoryProfile,
    PackedContext,
    RecallResult,
)
from .backend_local_sqlite import LocalSQLiteBackend


class ContextPacker:
    """
    Packs memory items into context for prompt injection.

    Features:
    - Deterministic packing order
    - Character limit enforcement
    - Memory provenance header
    - Clear "not evidence" warning
    """

    # Warning header for packed memory
    MEMORY_HEADER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║ MEMORY CONTEXT (untrusted; planning-only; NOT evidence)                       ║
║ This content is from memory and CANNOT be used as evidence for certification. ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".strip()

    MEMORY_FOOTER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║ END MEMORY CONTEXT - Remember: Memory is NEVER evidence                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".strip()

    def __init__(
        self,
        backend: LocalSQLiteBackend,
        profile: MemoryProfile,
    ):
        self.backend = backend
        self.profile = profile

    def pack(
        self,
        items: list[MemoryItem],
        max_chars: int | None = None,
        include_provenance: bool = True,
    ) -> PackedContext:
        """
        Pack memory items into a context string.

        Args:
            items: Memory items to pack
            max_chars: Maximum characters (defaults to profile setting)
            include_provenance: Include provenance header

        Returns:
            PackedContext with packed content
        """
        max_chars = max_chars or self.profile.max_inject_chars

        # Sort items deterministically by (type, created_at, id)
        sorted_items = sorted(
            items,
            key=lambda x: (x.type.value, x.created_at_utc.isoformat(), x.id),
        )

        # Build content
        content_parts = []
        chars_used = 0
        items_included = 0

        for item in sorted_items:
            item_text = self._format_item(item)
            item_chars = len(item_text)

            # Check if we have room
            if chars_used + item_chars > max_chars:
                # Try to fit a truncated version
                remaining = max_chars - chars_used - 50  # Leave room for ellipsis
                if remaining > 100:
                    truncated = item_text[:remaining] + "... [truncated]"
                    content_parts.append(truncated)
                    chars_used += len(truncated)
                    items_included += 1
                break

            content_parts.append(item_text)
            chars_used += item_chars
            items_included += 1

        content = "\n\n".join(content_parts)

        # Build provenance header if enabled
        header = self.MEMORY_HEADER
        if include_provenance:
            db_hash = self.backend.compute_db_hash()
            selection_rule = f"Sorted by (type, created_at, id), limit={max_chars} chars"
            provenance = f"\nProvenance: db_hash={db_hash}, rule='{selection_rule}'"
            header = self.MEMORY_HEADER + provenance

        return PackedContext(
            header=header,
            content=content,
            footer=self.MEMORY_FOOTER,
            total_chars=len(header) + len(content) + len(self.MEMORY_FOOTER),
            items_included=items_included,
            db_hash=self.backend.compute_db_hash(),
            selection_rule=f"deterministic sort, max_chars={max_chars}",
        )

    def pack_from_recall(
        self,
        recall_result: RecallResult,
        max_chars: int | None = None,
    ) -> PackedContext:
        """Pack items from a recall result."""
        return self.pack(
            items=recall_result.items,
            max_chars=max_chars,
        )

    def pack_for_turn(
        self,
        query: str,
        recall_func,
        max_chars: int | None = None,
    ) -> PackedContext:
        """
        Pack context for a conversation turn.

        Args:
            query: The user's query (for recall)
            recall_func: Function to call for recall
            max_chars: Maximum characters

        Returns:
            PackedContext ready for injection
        """
        result = recall_func(query)
        return self.pack_from_recall(result, max_chars)

    def _format_item(self, item: MemoryItem) -> str:
        """Format a single memory item for inclusion."""
        parts = [
            f"[{item.type.value.upper()}] {item.created_at_utc.strftime('%Y-%m-%d %H:%M')}",
        ]

        if item.tags:
            parts.append(f"Tags: {', '.join(item.tags)}")

        parts.append(item.text)

        return "\n".join(parts)


def verify_packing_determinism(
    packer: ContextPacker,
    items: list[MemoryItem],
    iterations: int = 3,
) -> bool:
    """
    Verify that packing is deterministic.

    Args:
        packer: ContextPacker instance
        items: Items to pack
        iterations: Number of times to pack

    Returns:
        True if all iterations produce identical output
    """
    results = []
    for _ in range(iterations):
        packed = packer.pack(items)
        content_hash = hashlib.sha256(packed.content.encode()).hexdigest()
        results.append(content_hash)

    return len(set(results)) == 1
