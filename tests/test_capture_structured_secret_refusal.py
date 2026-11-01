"""Synthetic regression checks: credential-shaped structured tool data must not persist.

Default redaction protects free-text key=value tokens, but quoted dictionary keys
require a distinct fail-closed boundary. No actual credentials are used.
"""

import pytest

from memory.capture import MemoryCapture


@pytest.mark.parametrize(
    ("inputs", "outputs", "metadata"),
    [
        ({"password": "synthetic-passphrase"}, {}, None),
        ({"outer": [{"Auth-Token": "synthetic-token"}]}, {}, None),
        ({}, {"headers": {"Authorization": "Basic synthetic"}}, None),
        ({}, {"items": [{"refresh_token": "synthetic-refresh"}]}, None),
        ({}, '{"client_secret": "synthetic-client"}', None),
        ({}, "{'private_key': 'synthetic-private'}", None),
        ({}, {}, {"nested": {"api_key": "synthetic-api"}}),
    ],
)
def test_sensitive_structured_tool_data_is_not_captured(
    memory_db, memory_profile, inputs, outputs, metadata
):
    capture = MemoryCapture(memory_db, memory_profile)
    result = capture.capture_tool_call(
        "synthetic_safe_tool", inputs, outputs, metadata=metadata
    )
    assert result is None
    assert memory_db.get_stats().total_items == 0


def test_benign_structured_tool_call_remains_capturable(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_tool_call(
        "synthetic_safe_tool", {"query": "synthetic"}, {"status": "ok"},
        metadata={"page": 1}
    )
    assert item_id is not None
    assert memory_db.retrieve(item_id) is not None


def test_ignored_input_payload_does_not_block_safe_result(memory_db, memory_profile):
    memory_profile.store_tool_inputs = False
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_tool_call(
        "synthetic_safe_tool", {"password": "synthetic-secret"}, {"status": "ok"}
    )
    assert item_id is not None
    item = memory_db.retrieve(item_id)
    assert "synthetic-secret" not in item.text


def test_explicit_redaction_opt_out_does_not_override_sensitive_field_refusal(
    memory_db, memory_profile
):
    memory_profile.redact_before_store = False
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_tool_call(
        "synthetic_safe_tool", {"password": "synthetic-secret"}, {}
    ) is None
    assert memory_db.get_stats().total_items == 0
