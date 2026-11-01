"""Synthetic refusal: automatic /profile context must not disclose SECRET items.

Direct explicit backend reads remain unchanged. Profile-safe filtering happens
in scoped SQL before pagination for synchronous and asynchronous backends.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from memory.backend_async_sqlite import AsyncLocalSQLiteBackend
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.recall import MemoryRecall
from memory.schema import MemoryItem, MemoryProfile, MemorySensitivity, MemoryType


def _item(
    name: str,
    memory_type: MemoryType,
    sensitivity: MemorySensitivity,
    stamp: datetime,
    *,
    repo_path: str | None = None,
) -> MemoryItem:
    metadata = {"repo_path": repo_path} if repo_path is not None else {}
    return MemoryItem(
        id=name,
        text=f"Synthetic {name} classified memory",
        type=memory_type,
        sensitivity=sensitivity,
        metadata=metadata,
        created_at_utc=stamp,
        updated_at_utc=stamp,
    )


def test_profile_excludes_secret_before_pagination_and_keeps_scoped_context(tmp_path):
    path = str(tmp_path / "profile.db")
    a = LocalSQLiteBackend(path, project_id="project-a")
    b = LocalSQLiteBackend(path, project_id="project-b")
    now = datetime(2026, 10, 31, tzinfo=UTC)

    # More than one page of newer SECRET decisions must not hide an older
    # permitted decision. None of the SECRET strings can enter /profile.
    a.store(_item("safe-decision", MemoryType.DECISION, MemorySensitivity.PRIVATE, now))
    for i in range(7):
        a.store(
            _item(
                f"secret-decision-{i}",
                MemoryType.DECISION,
                MemorySensitivity.SECRET,
                now + timedelta(minutes=i + 1),
            )
        )
    a.store(
        _item(
            "safe-codebase",
            MemoryType.CODEBASE_INDEX,
            MemorySensitivity.PRIVATE,
            now,
            repo_path="/synthetic/allowed",
        )
    )
    a.store(
        _item(
            "secret-codebase",
            MemoryType.CODEBASE_INDEX,
            MemorySensitivity.SECRET,
            now + timedelta(minutes=1),
            repo_path="/synthetic/secret",
        )
    )
    a.store(_item("safe-summary", MemoryType.SUMMARY, MemorySensitivity.PUBLIC, now))
    a.store(
        _item(
            "secret-summary",
            MemoryType.SUMMARY,
            MemorySensitivity.SECRET,
            now + timedelta(minutes=1),
        )
    )
    b.store(
        _item(
            "foreign-secret",
            MemoryType.DECISION,
            MemorySensitivity.SECRET,
            now + timedelta(minutes=2),
        )
    )

    # Explicit retrieval is not suppressed: this changes only default
    # automatic profile injection, not a caller's authorized direct read.
    assert a.retrieve("secret-decision-0") is not None
    assert a.list_items(limit=1, type_filter=MemoryType.DECISION)[0].id.startswith(
        "secret-decision-"
    )
    filtered = a.list_items(limit=1, type_filter=MemoryType.DECISION, exclude_secret=True)
    assert [item.id for item in filtered] == ["safe-decision"]
    assert [item.id for item in b.list_items(exclude_secret=True)] == []

    profile = MemoryRecall(a, MemoryProfile(name="synthetic")).get_profile_summary()
    assert [d["text"] for d in profile["recent_decisions"]] == [
        "Synthetic safe-decision classified memory"
    ]
    assert profile["codebase_indexed"] is True
    assert profile["codebase_path"] == "/synthetic/allowed"
    assert profile["summaries"] == ["Synthetic safe-summary classified memory"]
    assert "secret" not in str(profile).lower()
    assert "foreign" not in str(profile).lower()


def test_profile_rejects_unknown_persisted_sensitivity_before_pagination(tmp_path):
    path = str(tmp_path / "unknown.db")
    backend = LocalSQLiteBackend(path, project_id="project-a")
    now = datetime(2026, 10, 31, tzinfo=UTC)
    backend.store(_item("safe", MemoryType.DECISION, MemorySensitivity.PRIVATE, now))
    backend.store(
        _item("corrupt", MemoryType.DECISION, MemorySensitivity.SECRET, now + timedelta(days=1))
    )
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE memory_items SET sensitivity = 'unknown' WHERE id = 'corrupt'")
    result = MemoryRecall(backend, MemoryProfile(name="test")).get_profile_summary()
    assert [d["text"] for d in result["recent_decisions"]] == ["Synthetic safe classified memory"]


@pytest.mark.asyncio
async def test_async_profile_safe_filter_keeps_scope_and_limit(tmp_path):
    path = str(tmp_path / "async-profile.db")
    backend = AsyncLocalSQLiteBackend(path, project_id="project-a")
    foreign = AsyncLocalSQLiteBackend(path, project_id="project-b")
    await backend.initialize()
    await foreign.initialize()
    now = datetime(2026, 10, 31, tzinfo=UTC)
    try:
        await backend.store(_item("safe", MemoryType.DECISION, MemorySensitivity.PUBLIC, now))
        await backend.store(
            _item(
                "secret",
                MemoryType.DECISION,
                MemorySensitivity.SECRET,
                now + timedelta(minutes=1),
            )
        )
        await foreign.store(_item("foreign", MemoryType.DECISION, MemorySensitivity.PRIVATE, now))
        normal = await backend.list_items(limit=1, type_filter=MemoryType.DECISION)
        assert [m.id for m in normal] == ["secret"]
        filtered = await backend.list_items(
            limit=1, type_filter=MemoryType.DECISION, exclude_secret=True
        )
        assert [m.id for m in filtered] == ["safe"]
        assert [m.id for m in await foreign.list_items(exclude_secret=True)] == ["foreign"]
    finally:
        await foreign.close()
        await backend.close()


def test_default_recall_and_packed_command_never_inject_secret_or_corrupt_items(tmp_path):
    """Default auto-recall must filter sensitive rows before LIMIT and packing."""
    from memory.commands import MemoryCommands

    path = str(tmp_path / "recall-secret.db")
    a = LocalSQLiteBackend(path, project_id="project-a")
    b = LocalSQLiteBackend(path, project_id="project-b")
    stamp = datetime(2026, 10, 31, tzinfo=UTC)
    for i in range(7):
        a.store(
            _item(
                f"secret-{i}",
                MemoryType.NOTE,
                MemorySensitivity.SECRET,
                stamp + timedelta(minutes=i),
            )
        )
    a.store(_item("safe", MemoryType.NOTE, MemorySensitivity.PRIVATE, stamp))
    a.store(_item("corrupt", MemoryType.NOTE, MemorySensitivity.SECRET, stamp))
    b.store(_item("foreign", MemoryType.NOTE, MemorySensitivity.PUBLIC, stamp))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE memory_items SET sensitivity='unknown' WHERE id='corrupt'")

    # Explicit backend retrieval remains available to a trusted, authorized caller.
    assert a.retrieve("secret-0") is not None
    safe = a.search("Synthetic", limit=1, exclude_secret=True)
    assert safe.total_matches == 1
    assert [item.id for item in safe.items] == ["safe"]
    automatic = MemoryRecall(a, MemoryProfile(name="synthetic")).recall("Synthetic", limit=1)
    assert [item.id for item in automatic.items] == ["safe"]
    assert automatic.total_matches == 1

    commands = MemoryCommands(
        db_path=path, profile=MemoryProfile(name="synthetic"), project_id="project-a"
    )
    plain = commands.recall_memories("Synthetic", limit=1)
    assert [item["id"] for item in plain["items"]] == ["safe"]
    packed = commands.recall_memories("Synthetic", pack=True, limit=1)
    assert packed["items_included"] == 1
    assert "Synthetic safe classified memory" in packed["content"]
    assert "Synthetic secret-" not in packed["content"]
    assert "Synthetic corrupt" not in packed["content"]
    assert "Synthetic foreign" not in packed["content"]


@pytest.mark.asyncio
async def test_async_default_safe_search_filters_secret_and_invalid_classes(tmp_path):
    """Async filtering must match sync semantics and preserve project isolation."""
    path = str(tmp_path / "async-recall-secret.db")
    a = AsyncLocalSQLiteBackend(path, project_id="project-a")
    b = AsyncLocalSQLiteBackend(path, project_id="project-b")
    await a.initialize()
    await b.initialize()
    stamp = datetime(2026, 10, 31, tzinfo=UTC)
    try:
        await a.store(_item("secret", MemoryType.NOTE, MemorySensitivity.SECRET, stamp))
        await a.store(_item("safe", MemoryType.NOTE, MemorySensitivity.PUBLIC, stamp))
        await a.store(_item("corrupt", MemoryType.NOTE, MemorySensitivity.SECRET, stamp))
        await b.store(_item("foreign", MemoryType.NOTE, MemorySensitivity.PUBLIC, stamp))
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE memory_items SET sensitivity='unknown' WHERE id='corrupt'")
        # Direct, expressly requested searches can still include SECRET.
        assert (await a.retrieve("secret")) is not None
        safe = await a.search("Synthetic", limit=1, exclude_secret=True)
        assert safe.total_matches == 1
        assert [item.id for item in safe.items] == ["safe"]
        foreign_safe = await b.search("Synthetic", limit=1, exclude_secret=True)
        assert [item.id for item in foreign_safe.items] == ["foreign"]
    finally:
        await b.close()
        await a.close()
