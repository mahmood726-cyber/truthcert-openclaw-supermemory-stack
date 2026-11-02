"""Fail-closed synthetic tests for encoded credential field names in tool output."""

import pytest

from memory.capture import MemoryCapture


@pytest.mark.parametrize(
    "payload",
    [
        r'{"p\u0061ssword": "synthetic-only-value"}',
        r"{\u0022password\u0022:\u0022synthetic-only-value\u0022}",
        r'{"headers": {"auth\u005ftoken": "synthetic-only-value"}}',
        r"{'p\x61ssword': 'synthetic-only-value'}",
    ],
)
def test_escaped_credential_field_never_enters_tool_memory(memory_db, memory_profile, payload):
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_tool_call("synthetic_safe_tool", {}, payload) is None
    assert memory_db.get_stats().total_items == 0


def test_encoded_credential_in_nested_metadata_is_refused(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    result = capture.capture_tool_call(
        "synthetic_safe_tool",
        {"query": "safe"},
        {"status": "ok"},
        metadata={"payload": r'{"client\u005fsecret": "synthetic-only-value"}'},
    )
    assert result is None
    assert memory_db.get_stats().total_items == 0


def test_benign_unicode_escaped_text_still_captures(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    memory_id = capture.capture_tool_call(
        "synthetic_safe_tool",
        {"query": "safe"},
        r'{"description": "unicode \u263A"}',
    )
    assert memory_id is not None
    assert memory_db.retrieve(memory_id) is not None


def test_ignored_credential_output_is_not_persisted(memory_db, memory_profile):
    memory_profile.store_tool_results = False
    capture = MemoryCapture(memory_db, memory_profile)
    memory_id = capture.capture_tool_call(
        "synthetic_safe_tool",
        {"query": "safe"},
        r'{"p\u0061ssword": "synthetic-only-value"}',
    )
    assert memory_id is not None
    item = memory_db.retrieve(memory_id)
    assert item is not None
    assert "synthetic-only-value" not in item.text


def test_oversize_tool_output_is_not_truncated_into_memory(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_tool_call("synthetic_safe_tool", {}, "x" * 100_001) is None
    assert memory_db.get_stats().total_items == 0
