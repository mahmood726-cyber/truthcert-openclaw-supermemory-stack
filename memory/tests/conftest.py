"""Pytest fixtures for memory tests.

The root ``tests/conftest.py`` is not visible to tests under ``memory/tests``
because pytest only loads conftest files along the collected test's path.
This provides the ``temp_dir`` fixture those tests depend on.
"""

import pytest


@pytest.fixture
def temp_dir(tmp_path_factory):
    """Create an isolated temporary directory for a single test."""
    return tmp_path_factory.mktemp("memory-test")
