"""Trusted in-process project scope for SQLite memory.

A project scope must be selected by a trusted caller, not by untrusted memory
text or raw user-request parameters. Historical unlabelled rows are accessible
only through the reserved legacy scope; memory is never certification evidence.
"""

from .schema import MemoryItem

LEGACY_PROJECT_ID = "__legacy__"


def validate_project_id(project_id: str) -> str:
    """Reject missing or ambiguous scope identifiers instead of reading all."""
    if (
        not isinstance(project_id, str)
        or not project_id
        or project_id != project_id.strip()
        or len(project_id) > 128
    ):
        raise ValueError("project_id must be a nonempty canonical string")
    return project_id


def enforce_store_scope(item: MemoryItem, project_id: str) -> None:
    """Bind trusted backend scope; never accept a conflicting metadata label."""
    if "project_id" in item.metadata and item.metadata["project_id"] != project_id:
        raise ValueError("memory project scope mismatch")
    if project_id != LEGACY_PROJECT_ID:
        item.metadata["project_id"] = project_id


def scope_clause(alias: str = "") -> str:
    """SQL predicate: absent legacy labels are distinct from explicit JSON null.

    Only hard-coded SQL aliases may be used. Scope *values* remain SQL parameters.
    """
    if alias not in ("", "m."):
        raise ValueError("invalid SQL alias")
    column = f"{alias}metadata"
    return (
        f"(CASE WHEN json_type({column}, '$.project_id') IS NULL "
        f"THEN '{LEGACY_PROJECT_ID}' "
        f"ELSE json_extract({column}, '$.project_id') END) = ?"
    )
