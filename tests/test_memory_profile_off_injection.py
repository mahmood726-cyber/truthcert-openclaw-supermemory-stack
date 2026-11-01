"""Synthetic regression: an OFF memory profile cannot inject /profile context.

The administrative stats view remains separately available to explicit callers.
Memory is never a source of certifiable evidence.
"""

from memory import backend_local_sqlite, commands, recall, schema

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
    off = schema.MemoryProfile(name="off", auto_recall=False, auto_capture=False)
    assert (
        recall.MemoryRecall(NoReadBackend(), off).get_profile_summary() == EXPECTED_DISABLED_SUMMARY
    )


def test_off_profile_refuses_context_through_high_level_caller(tmp_path):
    path = str(tmp_path / "off-profile.db")
    a = backend_local_sqlite.LocalSQLiteBackend(path, project_id="project-a")
    b = backend_local_sqlite.LocalSQLiteBackend(path, project_id="project-b")
    for item in (
        schema.MemoryItem(
            id="private-decision",
            type=schema.MemoryType.DECISION,
            sensitivity=schema.MemorySensitivity.PRIVATE,
            text="Synthetic private planning decision",
        ),
        schema.MemoryItem(
            id="secret-decision",
            type=schema.MemoryType.DECISION,
            sensitivity=schema.MemorySensitivity.SECRET,
            text="Synthetic secret planning decision",
        ),
        schema.MemoryItem(
            id="private-codebase",
            type=schema.MemoryType.CODEBASE_INDEX,
            sensitivity=schema.MemorySensitivity.PRIVATE,
            text="Synthetic private repository index",
            metadata={"repo_path": "/synthetic/private"},
        ),
        schema.MemoryItem(
            id="private-summary",
            type=schema.MemoryType.SUMMARY,
            sensitivity=schema.MemorySensitivity.PRIVATE,
            text="Synthetic private summary content",
        ),
    ):
        a.store(item)
    b.store(
        schema.MemoryItem(
            id="foreign",
            type=schema.MemoryType.DECISION,
            text="Synthetic foreign project decision",
        )
    )

    off = schema.MemoryProfile(
        name="off",
        auto_recall=False,
        auto_capture=False,
        max_recall_results=0,
        max_inject_chars=0,
    )
    memory_commands = commands.MemoryCommands(db_path=path, profile=off, project_id="project-a")
    result = memory_commands.get_profile()
    assert result["summary"] == EXPECTED_DISABLED_SUMMARY
    assert result["stats"]["total_items"] == 4  # Explicit administrative stats only.
    assert "Synthetic" not in str(result["summary"])
    assert "/synthetic/private" not in str(result["summary"])

    # Disabling automatic injection does not destroy data or change authorized reads.
    assert memory_commands.backend.retrieve("private-decision") is not None
    assert memory_commands.backend.retrieve("secret-decision") is not None
    assert memory_commands.backend.retrieve("foreign") is None

    # Enabled behavior and pre-pagination SECRET exclusion must be preserved.
    enabled = recall.MemoryRecall(a, schema.MemoryProfile(name="enabled"))
    summary = enabled.get_profile_summary()
    assert [entry["text"] for entry in summary["recent_decisions"]] == [
        "Synthetic private planning decision"
    ]
    assert summary["codebase_path"] == "/synthetic/private"
    assert summary["summaries"] == ["Synthetic private summary content"]
    assert summary["total_memories"] == 4
    assert "secret" not in str(summary).lower()
    assert "foreign" not in str(summary).lower()
