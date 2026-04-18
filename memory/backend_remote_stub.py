"""
Remote backend stub - disabled by default.
Provides interface only for future implementation.
"""

from typing import Any, Optional, Protocol
from .schema import MemoryItem, MemoryStats, RecallResult, MemoryType, MemorySource


class RemoteBackend(Protocol):
    """Protocol for remote memory backends."""

    def store(self, item: MemoryItem) -> str:
        """Store a memory item remotely."""
        ...

    def retrieve(self, item_id: str) -> Optional[MemoryItem]:
        """Retrieve a memory item by ID."""
        ...

    def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: Optional[MemoryType] = None,
    ) -> RecallResult:
        """Search remote memory."""
        ...

    def sync(self, local_items: list[MemoryItem]) -> int:
        """Sync local items to remote."""
        ...


class RemoteBackendStub:
    """
    Stub implementation of remote backend.

    Remote backend is DISABLED by default.
    This stub provides the interface but raises errors if called.
    """

    def __init__(self, enabled: bool = False, endpoint: str = ""):
        self.enabled = enabled
        self.endpoint = endpoint

        if enabled:
            raise NotImplementedError(
                "Remote memory backend is not implemented. "
                "Set allow_remote_backend=false in memory profile."
            )

    def store(self, item: MemoryItem) -> str:
        """Store a memory item remotely."""
        self._check_enabled()
        raise NotImplementedError("Remote store not implemented")

    def retrieve(self, item_id: str) -> Optional[MemoryItem]:
        """Retrieve a memory item by ID."""
        self._check_enabled()
        raise NotImplementedError("Remote retrieve not implemented")

    def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: Optional[MemoryType] = None,
    ) -> RecallResult:
        """Search remote memory."""
        self._check_enabled()
        raise NotImplementedError("Remote search not implemented")

    def sync(self, local_items: list[MemoryItem]) -> int:
        """Sync local items to remote."""
        self._check_enabled()
        raise NotImplementedError("Remote sync not implemented")

    def get_stats(self) -> MemoryStats:
        """Get remote memory statistics."""
        self._check_enabled()
        raise NotImplementedError("Remote stats not implemented")

    def _check_enabled(self):
        """Check if remote backend is enabled."""
        if not self.enabled:
            raise RuntimeError(
                "Remote memory backend is disabled. "
                "Enable it in memory profile if needed."
            )
