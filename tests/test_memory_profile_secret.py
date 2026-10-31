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
