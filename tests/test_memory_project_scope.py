"""Synthetic project isolation at all memory read and mutation boundaries."""

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.commands import MemoryCommands
from memory.schema import MemoryItem


def _memory(text: str) -> MemoryItem:
    return MemoryItem(text=text, tags=["synthetic", "not-evidence"])


def test_project_scopes_confine_search_and_id_access(tmp_path) -> None:
    db = str(tmp_path / "scoped.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    legacy = LocalSQLiteBackend(db)
    a_id = a.store(_memory("sharedtoken source A"))
    b_id = b.store(_memory("sharedtoken source B"))
    assert a_id != b_id
    assert a.retrieve(b_id) is None
    assert b.retrieve(a_id) is None
    assert legacy.retrieve(a_id) is None
    assert legacy.search("sharedtoken").items == []
    assert [x.id for x in a.search("sharedtoken").items] == [a_id]
    assert [x.id for x in b.search("sharedtoken").items] == [b_id]
    assert a.search("sharedtoken").total_matches == 1
    assert [x.id for x in a.list_items()] == [a_id]
    assert a.get_stats().total_items == 1
    assert a.delete(b_id) is False
    assert a.compute_db_hash() != b.compute_db_hash()
    assert a.wipe(confirm=True)
    assert a.retrieve(a_id) is None
    assert b.retrieve(b_id) is not None
    assert b.search("sharedtoken").total_matches == 1


def test_project_scope_refuses_missing_mismatch_and_explicit_null(tmp_path) -> None:
    db = str(tmp_path / "mismatched.db")
    with pytest.raises(ValueError):
        LocalSQLiteBackend(db, project_id="")
    a = LocalSQLiteBackend(db, project_id="project-a")
    with pytest.raises(ValueError, match="scope mismatch"):
        a.store(MemoryItem(text="synthetic", metadata={"project_id": "project-b"}))
    with pytest.raises(ValueError, match="scope mismatch"):
        a.store(MemoryItem(text="synthetic", metadata={"project_id": None}))
    a_id = a.store(_memory("noncertifying project A"))
    assert LocalSQLiteBackend(db).retrieve(a_id) is None


def test_high_level_memory_command_scope_does_not_mix_projects(tmp_path) -> None:
    db = str(tmp_path / "commands.db")
    a = MemoryCommands(db_path=db, project_id="project-a")
    b = MemoryCommands(db_path=db, project_id="project-b")
    a.remember("Scopedsynthetic private A")
    b.remember("Scopedsynthetic private B")
    output_a = a.recall_memories("Scopedsynthetic")
    output_b = b.recall_memories("Scopedsynthetic")
    assert len(output_a["items"]) == len(output_b["items"]) == 1
    assert "private A" in output_a["items"][0]["text"]
    assert "private B" in output_b["items"][0]["text"]
    assert MemoryCommands(db_path=db).recall_memories("Scopedsynthetic")["items"] == []


@pytest.mark.asyncio
async def test_async_project_scope_confines_reads_writes_and_wipe(tmp_path) -> None:
    db = str(tmp_path / "scoped_async.db")
    a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    b = AsyncLocalSQLiteBackend(db, project_id="project-b")
    try:
        a_id = await a.store(_memory("asyncscope source A"))
        b_id = await b.store(_memory("asyncscope source B"))
        assert a_id != b_id
        assert await a.retrieve(b_id) is None
        assert await b.retrieve(a_id) is None
        assert (await a.search("asyncscope")).total_matches == 1
        assert [x.id for x in (await a.search("asyncscope")).items] == [a_id]
        assert [x.id for x in await b.list_items()] == [b_id]
        assert (await b.get_stats()).total_items == 1
        assert not await a.delete(b_id)
        assert await a.wipe(confirm=True)
        assert await a.retrieve(a_id) is None
        assert await b.retrieve(b_id) is not None
    finally:
        await a.close()
        await b.close()


def test_old_unlabelled_rows_remain_legacy_only(tmp_path) -> None:
    db = str(tmp_path / "legacy.db")
    legacy = LocalSQLiteBackend(db)
    old_id = legacy.store(_memory("legacy only historical memory"))
    a = LocalSQLiteBackend(db, project_id="project-a")
    assert a.retrieve(old_id) is None
    assert a.search("historical").items == []
    assert legacy.retrieve(old_id) is not None
    assert a.wipe(confirm=True)
    assert legacy.retrieve(old_id) is not None
