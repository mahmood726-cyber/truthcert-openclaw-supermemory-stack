"""Synthetic privacy boundary controls for persisted memory capture.

No patient identifiers or real credentials are used. Redact before truncation,
and never save unredacted nested metadata or certification error strings.
"""

from memory.capture import MemoryCapture
from memory.schema import MemoryProfile

SECRET = "ABCDEFGHIJKLMNOPQRSTUVWX"
TOKEN = "api_key=" + SECRET


def test_chat_redacts_before_truncation(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_chat_turn(
        "X" * 183 + " " + TOKEN,
        "synthetic reply",
        turn_number=7,
        metadata={"nested": {"source": TOKEN}},
    )
    item = memory_db.retrieve(item_id)
    assert SECRET not in item.text
    assert "api_key=[API_KEY" in item.text  # truncated redaction marker is safe
    assert SECRET not in str(item.metadata)
    assert "API_KEY_REDACTED" in str(item.metadata)


def test_tool_inputs_and_outputs_redacted_before_truncation(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_tool_call(
        "synthetic_tool",
        {"payload": "X" * 470 + " " + TOKEN},
        {"payload": "Y" * 980 + " " + TOKEN},
        metadata={"nested": {"payload": TOKEN}},
    )
    item = memory_db.retrieve(item_id)
    assert SECRET not in item.text
    assert SECRET not in str(item.metadata)
    assert "API_KEY_REDACTED" in str(item.metadata)


def test_skipped_capture_does_not_write(memory_db, memory_profile):
    memory_profile.auto_capture = False
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_chat_turn("synthetic", "synthetic") is None
    assert capture.capture_tool_call("synthetic", {}, {}) is None
    assert memory_db.get_stats().total_items == 0


def test_tool_denylist_blocks_sensitive_outputs(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_tool_call("get_secrets", {}, TOKEN) is None
    assert memory_db.get_stats().total_items == 0


def test_selected_mode_prevents_unapproved_tool_capture(memory_db, memory_profile):
    memory_profile.capture_mode = "selected"
    memory_profile.capture_tools = ["synthetic_allowed"]
    capture = MemoryCapture(memory_db, memory_profile)
    assert capture.capture_tool_call("synthetic_other", {}, {}) is None
    assert capture.capture_tool_call("synthetic_allowed", {}, {}) is not None


def test_decision_redacts_text_tags_and_nested_metadata(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_decision(
        TOKEN, context=TOKEN, tags=[TOKEN], metadata={"nested": {"sensitive": TOKEN}}
    )
    item = memory_db.retrieve(item_id)
    assert SECRET not in item.text
    assert SECRET not in str(item.metadata)
    assert SECRET not in str(item.tags)


def test_certification_errors_do_not_escape_memory_redaction(memory_db, memory_profile):
    capture = MemoryCapture(memory_db, memory_profile)
    item_id = capture.capture_certification_result(
        "synthetic-bundle", "REJECT", "SILVER", 1, errors=[TOKEN]
    )
    item = memory_db.retrieve(item_id)
    assert SECRET not in item.text
    assert SECRET not in str(item.metadata)
    assert "API_KEY_REDACTED" in item.text
    assert item.metadata["errors"][0].endswith("[API_KEY_REDACTED]")


def test_redaction_opt_out_retains_explicit_legacy_behaviour(memory_db):
    profile = MemoryProfile(name="synthetic-no-redaction", redact_before_store=False)
    capture = MemoryCapture(memory_db, profile)
    item_id = capture.capture_certification_result(
        "synthetic-bundle", "REJECT", "SILVER", 1, errors=[TOKEN]
    )
    item = memory_db.retrieve(item_id)
    assert SECRET in item.text
    assert SECRET in str(item.metadata)
