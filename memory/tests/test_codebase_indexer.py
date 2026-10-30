"""
Tests for codebase indexer.
"""

from pathlib import Path

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.codebase_indexer import CodebaseIndexer
from memory.schema import MemoryType


@pytest.fixture
def sample_codebase(tmp_path: Path) -> Path:
    """Create a sample codebase structure."""
    # Create directory structure
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    # Create files
    (tmp_path / "README.md").write_text("# Test Project\n\nA sample project.")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    (tmp_path / "src" / "main.py").write_text("def main():\n    print('Hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")

    return tmp_path


class TestCodebaseIndexer:
    """Test codebase indexing."""

    def test_index_creates_memory_item(self, sample_codebase: Path, temp_dir: Path) -> None:
        """Test that indexing creates a CodebaseIndex memory item."""
        db_path = temp_dir / "test.db"
        backend = LocalSQLiteBackend(str(db_path))
        indexer = CodebaseIndexer(backend)

        item_id = indexer.index_codebase(str(sample_codebase), max_files=100)

        # Retrieve and verify
        item = backend.retrieve(item_id)
        assert item is not None
        assert item.type == MemoryType.CODEBASE_INDEX
        assert "codebase" in item.tags

    def test_index_captures_key_files(self, sample_codebase: Path, temp_dir: Path) -> None:
        """Test that key files are identified."""
        db_path = temp_dir / "test.db"
        backend = LocalSQLiteBackend(str(db_path))
        indexer = CodebaseIndexer(backend)

        item_id = indexer.index_codebase(str(sample_codebase))

        item = backend.retrieve(item_id)
        assert item is not None
        key_files = item.metadata.get("key_files", [])

        assert "README.md" in key_files or any("README" in f for f in key_files)
        assert "pyproject.toml" in key_files or any("pyproject" in f for f in key_files)

    def test_index_computes_repo_hash(self, sample_codebase: Path, temp_dir: Path) -> None:
        """Test that repo hash is computed."""
        db_path = temp_dir / "test.db"
        backend = LocalSQLiteBackend(str(db_path))
        indexer = CodebaseIndexer(backend)

        item_id = indexer.index_codebase(str(sample_codebase))

        item = backend.retrieve(item_id)
        assert item is not None
        repo_hash = item.metadata.get("repo_hash")

        assert repo_hash is not None
        assert repo_hash.startswith("sha256:")

    def test_index_detects_changes(self, sample_codebase: Path, temp_dir: Path) -> None:
        """Test change detection."""
        db_path = temp_dir / "test.db"
        backend = LocalSQLiteBackend(str(db_path))
        indexer = CodebaseIndexer(backend)

        # Initial index
        indexer.index_codebase(str(sample_codebase))

        # Check - should show no changes
        result = indexer.check_for_changes(str(sample_codebase))
        assert not result["changed"]

        # Modify a file
        (sample_codebase / "src" / "main.py").write_text("def main():\n    print('Modified')\n")

        # Check again - should show changes
        result = indexer.check_for_changes(str(sample_codebase))
        assert result["changed"]

    def test_index_respects_max_files(self, sample_codebase: Path, temp_dir: Path) -> None:
        """Test that max_files limit is respected."""
        db_path = temp_dir / "test.db"
        backend = LocalSQLiteBackend(str(db_path))
        indexer = CodebaseIndexer(backend)

        item_id = indexer.index_codebase(str(sample_codebase), max_files=2)

        item = backend.retrieve(item_id)
        assert item is not None
        file_count = item.metadata.get("file_count", 0)

        assert file_count <= 2
