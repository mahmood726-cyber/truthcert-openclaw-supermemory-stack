"""Synthetic project isolation at all memory read and mutation boundaries."""

import sqlite3

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.commands import MemoryCommands
from memory.schema import MemoryItem, MemoryType
from memory.scope import scoped_sql


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


def test_duplicate_project_scope_keys_fail_closed_for_retrieval_and_recall(tmp_path) -> None:
    """SQLite and Python disagree on duplicate keys: reject an ambiguous stored label."""
    db = str(tmp_path / "duplicate_labels.db")
    project_a = LocalSQLiteBackend(db, project_id="project-a")
    project_b = LocalSQLiteBackend(db, project_id="project-b")
    memory_id = project_b.store(_memory("ambiguousscope synthetic private B"))
    # Deliberate corruption through SQL, not a normal write through MemoryItem.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_items SET metadata = ? WHERE id = ?",
            ('{"project_id":"project-a","project_id":"project-b"}', memory_id),
        )
    assert project_a.retrieve(memory_id) is None
    assert project_b.retrieve(memory_id) is None
    assert project_a.search("ambiguousscope").items == []
    assert project_a.search("ambiguousscope").total_matches == 0
    assert project_a.get_stats().total_items == 0


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


def test_scoped_search_filtered_totals_match_returned_items(tmp_path) -> None:
    """Project, type and tag predicates must match both result and total queries."""
    db = str(tmp_path / "scoped_counts.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    wanted_id = a.store(MemoryItem(text="sharedcount wanted", tags=["keep"]))
    a.store(MemoryItem(type=MemoryType.DECISION, text="sharedcount other", tags=["omit"]))
    b.store(MemoryItem(text="sharedcount different project", tags=["keep"]))
    for kwargs in ({"type_filter": MemoryType.NOTE}, {"tags_filter": ["keep"]}):
        result = a.search("sharedcount", **kwargs)
        assert [item.id for item in result.items] == [wanted_id]
        assert result.total_matches == len(result.items) == 1


@pytest.mark.asyncio
async def test_async_scoped_search_filtered_totals_match_returned_items(
    tmp_path,
) -> None:
    """The async backend must use the same filters for counts and results."""
    db = str(tmp_path / "scoped_counts_async.db")
    a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    b = AsyncLocalSQLiteBackend(db, project_id="project-b")
    try:
        wanted_id = await a.store(MemoryItem(text="asyncsharedcount wanted", tags=["keep"]))
        await a.store(
            MemoryItem(
                type=MemoryType.DECISION,
                text="asyncsharedcount other",
                tags=["omit"],
            )
        )
        await b.store(MemoryItem(text="asyncsharedcount different project", tags=["keep"]))
        for kwargs in ({"type_filter": MemoryType.NOTE}, {"tags_filter": ["keep"]}):
            result = await a.search("asyncsharedcount", **kwargs)
            assert [item.id for item in result.items] == [wanted_id]
            assert result.total_matches == len(result.items) == 1
    finally:
        await a.close()
        await b.close()


def test_scoped_tag_membership_is_exact(tmp_path) -> None:
    """Partial tag names must not appear in scoped recall or totals."""
    db = str(tmp_path / "exact_tags.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    wanted_id = a.store(MemoryItem(text="scopedtagmatch wanted", tags=["alpha", "100%_done"]))
    a.store(MemoryItem(text="scopedtagmatch false positive", tags=["alphabet"]))
    b.store(MemoryItem(text="scopedtagmatch other project", tags=["alpha"]))
    for tag in ("alpha", "100%_done"):
        result = a.search("scopedtagmatch", tags_filter=[tag])
        assert [item.id for item in result.items] == [wanted_id]
        assert result.total_matches == 1
    result = a.search("scopedtagmatch", tags_filter=["alp"])
    assert result.items == []
    assert result.total_matches == 0


@pytest.mark.asyncio
async def test_async_scoped_tag_membership_is_exact(tmp_path) -> None:
    """Async tag filtering has the same literal membership contract."""
    db = str(tmp_path / "exact_tags_async.db")
    a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    b = AsyncLocalSQLiteBackend(db, project_id="project-b")
    try:
        wanted_id = await a.store(
            MemoryItem(text="asyncscopedtagmatch wanted", tags=["alpha", "100%_done"])
        )
        await a.store(MemoryItem(text="asyncscopedtagmatch false positive", tags=["alphabet"]))
        await b.store(MemoryItem(text="asyncscopedtagmatch other project", tags=["alpha"]))
        for tag in ("alpha", "100%_done"):
            result = await a.search("asyncscopedtagmatch", tags_filter=[tag])
            assert [item.id for item in result.items] == [wanted_id]
            assert result.total_matches == 1
        result = await a.search("asyncscopedtagmatch", tags_filter=["alp"])
        assert result.items == []
        assert result.total_matches == 0
    finally:
        await a.close()
        await b.close()


def test_scoped_sql_template_rejects_missing_repeated_or_untrusted_scope() -> None:
    """SQL construction must not silently omit scope or interpolate an alias."""
    with pytest.raises(ValueError, match="exactly one"):
        scoped_sql("SELECT id FROM memory_items")
    with pytest.raises(ValueError, match="exactly one"):
        scoped_sql("SELECT /*PROJECT_SCOPE*/ OR /*PROJECT_SCOPE*/")
    with pytest.raises(ValueError, match="invalid SQL alias"):
        scoped_sql("SELECT /*PROJECT_SCOPE*/", alias="m; DROP TABLE memory_items; --")


def test_scoped_sql_template_binds_project_values(tmp_path) -> None:
    """Template expansion preserves one value placeholder and legacy separation."""
    conn = sqlite3.connect(str(tmp_path / "template_scopes.db"))
    try:
        conn.execute("CREATE TABLE memory_items (id TEXT, metadata TEXT)")
        conn.executemany(
            "INSERT INTO memory_items(id, metadata) VALUES (?, ?)",
            [
                ("legacy", "{}"),
                ("a", '{"project_id":"project-a"}'),
                ("b", '{"project_id":"project-b"}'),
                ("null", '{"project_id":null}'),
                ("ambiguous-a", '{"project_id":"project-a","project_id":"project-b"}'),
                ("ambiguous-b", '{"project_id":"project-b","project_id":"project-a"}'),
            ],
        )
        sql = scoped_sql("SELECT id FROM memory_items WHERE /*PROJECT_SCOPE*/")
        assert sql.count("?") == 1
        for project_id, expected in (
            ("__legacy__", "legacy"),
            ("project-a", "a"),
            ("project-b", "b"),
        ):
            assert conn.execute(sql, (project_id,)).fetchall() == [(expected,)]
    finally:
        conn.close()

def test_project_memory_hash_changes_on_provenance_and_privacy_edits(tmp_path) -> None:
    """A source-revision or privacy edit must invalidate retained recall provenance."""
    db = str(tmp_path / "fingerprint.db")
    a = LocalSQLiteBackend(db, project_id="project-a")
    b = LocalSQLiteBackend(db, project_id="project-b")
    item_id = a.store(
        MemoryItem(text="synthetic revision-bound memory", metadata={"source_revision": "v1"})
    )
    original = a.compute_db_hash()
    other_before = b.compute_db_hash()
    assert original.startswith("sha256:") and len(original) == len("sha256:") + 64

    b.store(_memory("synthetic independent project-B memory"))
    assert a.compute_db_hash() == original
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_items SET metadata = json_set(metadata, '$.source_revision', 'v2') "
            "WHERE id = ?",
            (item_id,),
        )
    revised = a.compute_db_hash()
    assert revised != original
    assert b.compute_db_hash() != other_before  # Its own insertion is visible.

    b_stable = b.compute_db_hash()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE memory_items SET sensitivity = 'secret' WHERE id = ?", (item_id,))
    assert a.compute_db_hash() != revised
    assert b.compute_db_hash() == b_stable

    before_delete = a.compute_db_hash()
    assert a.delete(item_id)
    assert a.compute_db_hash() != before_delete


@pytest.mark.asyncio
async def test_async_memory_hash_matches_sync_and_invalidates_source_revision(tmp_path) -> None:
    """Async and sync fingerprints encode identical scoped active-row bytes."""
    db = str(tmp_path / "fingerprint_async.db")
    a = AsyncLocalSQLiteBackend(db, project_id="project-a")
    try:
        item_id = await a.store(
            MemoryItem(text="synthetic async revision", metadata={"source_revision": "v1"})
        )
        sync_backend = LocalSQLiteBackend(db, project_id="project-a")
        first = await a.compute_db_hash()
        assert first == sync_backend.compute_db_hash()
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE memory_items SET retention = ? WHERE id = ?",
                ('{"keep_days":31,"max_items":10000,"max_bytes":104857600}', item_id),
            )
        second = await a.compute_db_hash()
        assert second != first
        assert second == sync_backend.compute_db_hash()
    finally:
        await a.close()
