"""BM25 must not depend on another project or hidden/retracted memories.

Synthetic records only: neither these records nor their scores are certification
or source-authentication evidence.
"""

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.schema import MemoryItem, MemorySensitivity


def _alpha_heavy() -> MemoryItem:
    return MemoryItem(text="alpha " * 9 + "beta", tags=["synthetic"])


def _beta_heavy() -> MemoryItem:
    return MemoryItem(text="alpha " + "beta " * 9, tags=["synthetic"])


def _ids(result) -> list[str]:
    return [item.id for item in result.items]


def test_bm25_ranking_does_not_depend_on_other_project_corpus(tmp_path) -> None:
    path = str(tmp_path / "ranking.db")
    a = LocalSQLiteBackend(path, project_id="project-a")
    b = LocalSQLiteBackend(path, project_id="project-b")
    first = a.store(_alpha_heavy())
    second = a.store(_beta_heavy())

    # With global BM25 these unrelated, nonmatching documents alter term IDF
    # and reverse the order of the two project-A hits.
    for index in range(100):
        b.store(MemoryItem(text=f"alpha synthetic-other-{index}"))
    before = a.search("alpha beta")
    assert set(_ids(before)) == {first, second}
    assert before.total_matches == 2

    assert b.wipe(confirm=True)
    for index in range(100):
        b.store(MemoryItem(text=f"beta synthetic-other-{index}"))
    after = a.search("alpha beta")
    assert _ids(after) == _ids(before)
    assert after.total_matches == 2
    assert a.compute_db_hash() == before.db_hash == after.db_hash


def test_bm25_hidden_and_soft_deleted_documents_do_not_influence_safe_recall(tmp_path) -> None:
    path = str(tmp_path / "hidden_ranking.db")
    a = LocalSQLiteBackend(path, project_id="project-a")
    first = a.store(_alpha_heavy())
    second = a.store(_beta_heavy())
    before = a.search("alpha beta", exclude_secret=True)

    secret_id = a.store(
        MemoryItem(text="beta " * 25 + "hidden-source", sensitivity=MemorySensitivity.SECRET)
    )
    secret_result = a.search("alpha beta", exclude_secret=True)
    assert _ids(secret_result) == _ids(before) == sorted([first, second])
    assert secret_id not in _ids(secret_result)

    deleted_id = a.store(MemoryItem(text="alpha " * 25 + "retracted-source"))
    assert a.delete(deleted_id)
    after = a.search("alpha beta", exclude_secret=True)
    assert _ids(after) == _ids(before)
    assert after.total_matches == 2
    # Explicit authorized historical search still permits deleted records.
    assert deleted_id in _ids(a.search("alpha", include_deleted=True))


@pytest.mark.asyncio
async def test_async_bm25_project_corpus_and_visibility_match_sync(tmp_path) -> None:
    path = str(tmp_path / "async_ranking.db")
    a = AsyncLocalSQLiteBackend(path, project_id="project-a")
    b = AsyncLocalSQLiteBackend(path, project_id="project-b")
    try:
        first = await a.store(_alpha_heavy())
        second = await a.store(_beta_heavy())
        for index in range(100):
            await b.store(MemoryItem(text=f"alpha async-other-{index}"))
        before = await a.search("alpha beta", exclude_secret=True)
        assert set(_ids(before)) == {first, second}

        assert await b.wipe(confirm=True)
        for index in range(100):
            await b.store(MemoryItem(text=f"beta async-other-{index}"))
        after = await a.search("alpha beta", exclude_secret=True)
        assert _ids(after) == _ids(before)
        assert after.total_matches == before.total_matches == 2
        assert after.db_hash == before.db_hash

        await a.store(
            MemoryItem(text="beta " * 25 + "private-hidden", sensitivity=MemorySensitivity.SECRET)
        )
        assert _ids(await a.search("alpha beta", exclude_secret=True)) == _ids(before)
    finally:
        await a.close()
        await b.close()
