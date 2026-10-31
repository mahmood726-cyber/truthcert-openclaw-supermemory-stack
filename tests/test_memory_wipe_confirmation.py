"""Fail closed on truthy non-boolean destructive memory confirmations.

The caller's explicit boolean True is required. Tests use synthetic records;
memory remains noncertifying context, never a signed evidence source.
"""

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.commands import MemoryCommands
from memory.schema import MemoryItem


UNTRUSTED_CONFIRMATIONS = ("false", "no", "0", 1, ["yes"], {"confirmed": False})


@pytest.mark.parametrize("confirmation", UNTRUSTED_CONFIRMATIONS)
def test_sync_wipe_refuses_truthy_non_boolean_confirmation(tmp_path, confirmation):
    db = str(tmp_path / "wipe_sync.db")
    project_a = LocalSQLiteBackend(db, project_id="project-a")
    project_b = LocalSQLiteBackend(db, project_id="project-b")
    a_id = project_a.store(MemoryItem(text="synthetic confidential project A"))
    b_id = project_b.store(MemoryItem(text="synthetic confidential project B"))

    assert project_a.wipe(confirm=confirmation) is False
    assert project_a.retrieve(a_id) is not None
    assert project_b.retrieve(b_id) is not None


@pytest.mark.parametrize("confirmation", UNTRUSTED_CONFIRMATIONS)
def test_command_wipe_refuses_truthy_non_boolean_confirmation(tmp_path, confirmation):
    db = str(tmp_path / "wipe_command.db")
    commands = MemoryCommands(db_path=db, project_id="project-a")
    project_b = LocalSQLiteBackend(db, project_id="project-b")
    a_id = commands.backend.store(MemoryItem(text="synthetic secret project A"))
    b_id = project_b.store(MemoryItem(text="synthetic secret project B"))

    result = commands.wipe(confirm=confirmation)
    assert result["wiped"] is False
    assert "error" in result
    assert commands.backend.retrieve(a_id) is not None
    assert project_b.retrieve(b_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", UNTRUSTED_CONFIRMATIONS)
async def test_async_wipe_refuses_truthy_non_boolean_confirmation(tmp_path, confirmation):
    db = str(tmp_path / "wipe_async.db")
    project_a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    project_b = AsyncLocalSQLiteBackend(db, project_id="project-b")
    try:
        a_id = await project_a.store(MemoryItem(text="synthetic confidential project A"))
        b_id = await project_b.store(MemoryItem(text="synthetic confidential project B"))

        assert await project_a.wipe(confirm=confirmation) is False
        assert await project_a.retrieve(a_id) is not None
        assert await project_b.retrieve(b_id) is not None
    finally:
        await project_a.close()
        await project_b.close()


def test_explicit_true_wipes_only_its_project(tmp_path):
    db = str(tmp_path / "wipe_approved.db")
    commands = MemoryCommands(db_path=db, project_id="project-a")
    project_b = LocalSQLiteBackend(db, project_id="project-b")
    a_id = commands.backend.store(MemoryItem(text="synthetic approved project A"))
    b_id = project_b.store(MemoryItem(text="synthetic independent project B"))

    result = commands.wipe(confirm=True)
    assert result["wiped"] is True
    assert result["items_removed"] == 1
    assert commands.backend.retrieve(a_id) is None
    assert project_b.retrieve(b_id) is not None
