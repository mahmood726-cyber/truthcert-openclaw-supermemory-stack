"""
Codebase indexer - indexes repository structure into memory.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar

from .backend_local_sqlite import LocalSQLiteBackend
from .schema import (
    CodebaseIndex,
    MemoryItem,
    MemorySource,
    MemoryType,
)


class CodebaseIndexer:
    """
    Indexes codebase structure and key files into memory.

    Features:
    - Directory structure analysis
    - Key file identification
    - Content hashing for change detection
    - Configurable file limits
    """

    # Default patterns for key files
    KEY_FILE_PATTERNS: ClassVar[list[str]] = [
        "README.md",
        "README.rst",
        "setup.py",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        ".env.example",
        "requirements.txt",
        "CHANGELOG.md",
    ]

    # Directories to skip
    SKIP_DIRS: ClassVar[list[str]] = [
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
    ]

    # Extensions to index
    INDEX_EXTENSIONS: ClassVar[list[str]] = [
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".sql",
    ]

    def __init__(
        self,
        backend: LocalSQLiteBackend,
    ):
        self.backend = backend

    def index_codebase(
        self,
        repo_path: str,
        max_files: int = 400,
        max_file_size: int = 100 * 1024,  # 100KB
        include_content: bool = False,
    ) -> str:
        """
        Index a codebase and store as memory item.

        Args:
            repo_path: Path to repository root
            max_files: Maximum files to index
            max_file_size: Maximum file size to hash
            include_content: Include file content summaries

        Returns:
            Memory item ID
        """
        path = Path(repo_path).resolve()
        if not path.exists():
            raise ValueError(f"Path does not exist: {repo_path}")

        # Collect files
        files = self._collect_files(path, max_files)

        # Hash files
        file_hashes = {}
        total_bytes = 0
        for file_path in files:
            try:
                stat = file_path.stat()
                if stat.st_size <= max_file_size:
                    content = file_path.read_bytes()
                    file_hash = hashlib.sha256(content).hexdigest()
                    rel_path = str(file_path.relative_to(path))
                    file_hashes[rel_path] = f"sha256:{file_hash}"
                    total_bytes += stat.st_size
            except OSError:
                continue

        # Identify key files
        key_files = self._identify_key_files(path, files)

        # Build structure summary
        structure = self._build_structure_summary(path, files)

        # Compute repo hash
        repo_hash = self._compute_repo_hash(file_hashes)

        # Create index
        index = CodebaseIndex(
            repo_path=str(path),
            repo_hash=repo_hash,
            file_count=len(files),
            total_bytes=total_bytes,
            key_files=key_files,
            file_hashes=file_hashes,
            structure_summary=structure,
        )

        # Create memory item
        item = MemoryItem(
            type=MemoryType.CODEBASE_INDEX,
            source=MemorySource.SYSTEM,
            text=self._format_index_text(index),
            tags=["codebase", "index", path.name],
            metadata={
                "repo_path": str(path),
                "repo_hash": repo_hash,
                "file_count": len(files),
                "total_bytes": total_bytes,
                "key_files": key_files,
            },
        )

        return self.backend.store(item)

    def _collect_files(
        self,
        root: Path,
        max_files: int,
    ) -> list[Path]:
        """Collect files to index."""
        files = []

        for item in root.rglob("*"):
            if len(files) >= max_files:
                break

            # Skip directories in skip list
            if any(skip in item.parts for skip in self.SKIP_DIRS):
                continue

            # Check extension
            if (item.is_file()) and (
                item.suffix.lower() in self.INDEX_EXTENSIONS or item.name in self.KEY_FILE_PATTERNS
            ):
                files.append(item)

        return files

    def _identify_key_files(
        self,
        root: Path,
        files: list[Path],
    ) -> list[str]:
        """Identify key files in the repository."""
        key_files = []

        for file_path in files:
            if file_path.name in self.KEY_FILE_PATTERNS:
                key_files.append(str(file_path.relative_to(root)))

        # Also check root directly
        for pattern in self.KEY_FILE_PATTERNS:
            root_file = root / pattern
            if root_file.exists():
                rel_path = str(root_file.relative_to(root))
                if rel_path not in key_files:
                    key_files.append(rel_path)

        return sorted(key_files)

    def _build_structure_summary(
        self,
        root: Path,
        files: list[Path],
    ) -> str:
        """Build a summary of the directory structure."""
        # Get unique directories
        dirs = set()
        for file_path in files:
            rel = file_path.relative_to(root)
            for parent in rel.parents:
                if str(parent) != ".":
                    dirs.add(str(parent))

        # Sort and format
        sorted_dirs = sorted(dirs)

        # Build tree representation
        lines = [f"Repository: {root.name}"]
        lines.append(f"Total files indexed: {len(files)}")
        lines.append("")
        lines.append("Directory structure:")

        for dir_path in sorted_dirs[:20]:  # Limit depth
            depth = dir_path.count("/") + dir_path.count("\\")
            indent = "  " * depth
            name = Path(dir_path).name
            lines.append(f"{indent}├── {name}/")

        if len(sorted_dirs) > 20:
            lines.append(f"  ... and {len(sorted_dirs) - 20} more directories")

        return "\n".join(lines)

    def _compute_repo_hash(self, file_hashes: dict[str, str]) -> str:
        """Compute overall repository hash."""
        canonical = json.dumps(
            sorted(file_hashes.items()),
            sort_keys=True,
        )
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"

    def _format_index_text(self, index: CodebaseIndex) -> str:
        """Format index as text for memory storage."""
        lines = [
            f"Codebase Index: {Path(index.repo_path).name}",
            f"Path: {index.repo_path}",
            f"Hash: {index.repo_hash}",
            f"Files: {index.file_count}",
            f"Size: {index.total_bytes / 1024:.1f} KB",
            "",
            "Key Files:",
        ]

        for key_file in index.key_files[:10]:
            lines.append(f"  - {key_file}")

        if len(index.key_files) > 10:
            lines.append(f"  ... and {len(index.key_files) - 10} more")

        lines.append("")
        lines.append(index.structure_summary)

        return "\n".join(lines)

    def check_for_changes(
        self,
        repo_path: str,
    ) -> dict[str, Any]:
        """
        Check if codebase has changed since last index.

        Returns:
            Dict with changed status and details
        """
        # Get existing index
        items = self.backend.list_items(
            limit=10,
            type_filter=MemoryType.CODEBASE_INDEX,
        )

        existing = None
        for item in items:
            if item.metadata.get("repo_path") == str(Path(repo_path).resolve()):
                existing = item
                break

        if not existing:
            return {
                "changed": True,
                "reason": "no_existing_index",
                "existing_hash": None,
            }

        # Recompute hash
        path = Path(repo_path).resolve()
        files = self._collect_files(path, max_files=400)

        file_hashes = {}
        for file_path in files:
            try:
                content = file_path.read_bytes()
                file_hash = hashlib.sha256(content).hexdigest()
                rel_path = str(file_path.relative_to(path))
                file_hashes[rel_path] = f"sha256:{file_hash}"
            except OSError:
                continue

        new_hash = self._compute_repo_hash(file_hashes)
        existing_hash = existing.metadata.get("repo_hash")

        return {
            "changed": new_hash != existing_hash,
            "reason": "hash_mismatch" if new_hash != existing_hash else "unchanged",
            "existing_hash": existing_hash,
            "new_hash": new_hash,
        }
