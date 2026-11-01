"""Synthetic regression: an OFF memory profile cannot inject /profile context.

The administrative stats view remains separately available to explicit callers.
Memory is never a source of certifiable evidence.
"""

from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.commands import MemoryCommands
from memory.recall import MemoryRecall
from memory.schema import MemoryItem, MemoryProfile, MemorySensitivity, MemoryType


EXPECTED_DISABLED_SUMMARY = {
    "recent_decisions": [],
    "codebase_indexed": False,
    "codebase_path": None,
    "summaries": [],
    "total_memories": None,
}


class NoReadBackend:
    """An OFF profile must not touch persisted records or their statistics."""

    def list_items(self, **kwargs):
        raise AssertionError("OFF profile attempted to list memories")

    def get_stats(self):
        raise AssertionError("OFF profile attempted to read memory statistics")


def test_off_profile_summary_does_not_read_backend():
    off = MemoryProfile(name="off", auto_recall=False, auto_capture=False)
    assert MemoryRecall(NoReadBackend(), off).get_profile_summary() == EXPECTED_DISABLED_SUMMARY


def test_off_profile_refuses_context_through_high_level_caller(tmp_path):
    path = str(tmp_path / "off-profile.db")
    a = LocalSQLiteBackend(path, project_id="project-a")
    b = LocalSQLiteBackend(path, project_id="project-b")
    for item in (
        MemoryItem(
            id="private-decision",
            type=MemoryType.DECISION,
            sensitivity=MemorySensitivity.PRIVATE,
            text="Synthetic private planning decision",
        ),
        MemoryItem(
            id="secret-decision",
            type=MemoryType.DECISION,
            sensitivity=MemorySensitivity.SECRET,
            text="Synthetic secret planning decision",
        ),
        MemoryItem(
            id="private-codebase",
            type=MemoryType.CODEBASE_INDEX,
            sensitivity=MemorySensitivity.PRIVATE,
            text="Synthetic private repository index",
            metadata={"repo_path": "/synthetic/private"},
        ),
        MemoryItem(
            id="private-summary",
            type=MemoryType.SUMMARY,
            sensitivity=MemorySensitivity.PRIVATE,
            text="Synthetic private summary content",
        ),
    ):
        a.store(item)
    b.store(
        MemoryItem(
            id="foreign",
            type=MemoryType.DECISION,
            text="Synthetic foreign project decision",
        )
    )

    off = MemoryProfile(
        name="off",
        auto_recall=False,
        auto_capture=False,
        max_recall_results=0,
        max_inject_chars=0,
    )
    commands = MemoryCommands(db_path=path, profile=off, project_id="project-a")
    result = commands.get_profile()
    assert result["summary"] == EXPECTED_DISABLED_SUMMARY
    assert result["stats"]["total_items"] == 4  # Explicit administrative stats only.
    assert "Synthetic" not in str(result["summary"])
    assert "/synthetic/private" not in str(result["summary"])

    # Disabling automatic injection does not destroy data or change authorized reads.
    assert commands.backend.retrieve("private-decision") is not None
    assert commands.backend.retrieve("secret-decision") is not None
    assert commands.backend.retrieve("foreign") is None

    # Enabled behavior and pre-pagination SECRET exclusion must be preserved.
    enabled = MemoryRecall(a, MemoryProfile(name="enabled"))
    summary = enabled.get_profile_summary()
    assert [entry["text"] for entry in summary["recent_decisions"]] == [
        "Synthetic private planning decision"
    ]
    assert summary["codebase_path"] == "/synthetic/private"
    assert summary["summaries"] == ["Synthetic private summary content"]
    assert summary["total_memories"] == 4
    assert "secret" not in str(summary).lower()
    assert "foreign" not in str(summary).lower()
