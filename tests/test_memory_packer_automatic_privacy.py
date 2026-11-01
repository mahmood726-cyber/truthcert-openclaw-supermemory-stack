"""Synthetic regression cases: automatic context packing must refuse unsafe recall.

No real memories. These are safety tests for the prompt-injection boundary, not
cryptographic model-call authentication or scientific source verification.
"""

import pytest

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.packer import ContextPacker
from memory.schema import (
    MemoryItem,
    MemoryProfile,
    MemorySensitivity,
    RecallResult,
)


def test_off_profile_never_calls_pack_for_turn_retriever(tmp_path) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "off.db"), project_id="project-a")
    packer = ContextPacker(backend, MemoryProfile(name="off", auto_recall=False))
    invoked = []

    def unsafe_callback(_query):
        invoked.append(True)
        raise AssertionError("OFF profile must not invoke retrieval")

    packed = packer.pack_for_turn("synthetic query", unsafe_callback)
    assert invoked == []
    assert packed.items_included == 0
    assert packed.content == ""
    assert packed.db_hash == ""


def test_off_profile_never_packs_precomputed_recall(tmp_path) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "off.db"), project_id="project-a")
    item = MemoryItem(
        text="synthetic secret withheld",
        sensitivity=MemorySensitivity.SECRET,
        metadata={"project_id": "project-a"},
    )
    recalled = RecallResult(items=[item], query="synthetic", db_hash="sha256:" + "a" * 64)
    packed = ContextPacker(backend, MemoryProfile(name="off", auto_recall=False)).pack_from_recall(
        recalled
    )
    assert packed.items_included == 0
    assert packed.content == ""


@pytest.mark.parametrize("via_callback", [False, True])
def test_secret_direct_backend_results_cannot_enter_automatic_pack(
    tmp_path, via_callback: bool
) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "secret.db"), project_id="project-a")
    backend.store(
        MemoryItem(
            text="synthetic hidden-marker",
            sensitivity=MemorySensitivity.SECRET,
        )
    )
    # Direct backend reads are allowed; automatic prompt injection is not.
    recalled = backend.search("hidden-marker", exclude_secret=False)
    assert len(recalled.items) == 1
    packer = ContextPacker(backend, MemoryProfile(name="on", auto_recall=True))
    with pytest.raises(ValueError, match="SECRET|secret|unsafe"):
        if via_callback:
            packer.pack_for_turn("hidden-marker", lambda _q: recalled)
        else:
            packer.pack_from_recall(recalled)


def test_forged_cross_project_recall_refused_before_packing(tmp_path) -> None:
    db = str(tmp_path / "scopes.db")
    project_a = LocalSQLiteBackend(db, project_id="project-a")
    project_b = LocalSQLiteBackend(db, project_id="project-b")
    project_b.store(MemoryItem(text="synthetic other-project private"))
    recalled = project_b.search("other-project")
    assert len(recalled.items) == 1
    assert recalled.items[0].metadata["project_id"] == "project-b"

    packer = ContextPacker(project_a, MemoryProfile(name="on", auto_recall=True))
    with pytest.raises(ValueError, match="scope|project"):
        packer.pack_from_recall(recalled)


def test_valid_safe_scoped_recall_still_packs(tmp_path) -> None:
    backend = LocalSQLiteBackend(str(tmp_path / "safe.db"), project_id="project-a")
    backend.store(MemoryItem(text="synthetic safe-marker"))
    recalled = backend.search("safe-marker", exclude_secret=True)
    packed = ContextPacker(backend, MemoryProfile(name="on")).pack_from_recall(recalled)
    assert packed.items_included == 1
    assert "safe-marker" in packed.content
    assert packed.db_hash == recalled.db_hash
    assert "NOT evidence" in packed.header
