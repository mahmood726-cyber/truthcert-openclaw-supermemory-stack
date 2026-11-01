"""Synthetic security regressions: profile skips cannot disable core capture denies.

All examples are invented tool names and non-secret payloads. Automatic memory
capture must never persist the output of a core sensitive tool, even when a
profile supplies its own exclusion list or explicitly selects that tool.
"""

import pytest

from memory.capture import MemoryCapture
from memory.redaction import SENSITIVE_TOOL_DENYLIST, should_capture_tool


@pytest.mark.parametrize("tool_name", [*SENSITIVE_TOOL_DENYLIST, "GeT_SeCrEtS"])
def test_core_sensitive_tools_remain_denied_with_custom_skip_list(
    memory_db, memory_profile, tool_name
):
    memory_profile.skip_tools = ["synthetic_custom_skip"]
    capture = MemoryCapture(memory_db, memory_profile)

    assert not should_capture_tool(tool_name, memory_profile.skip_tools)
    assert (
        capture.capture_tool_call(
            tool_name, {"payload": "synthetic"}, {"result": "synthetic"}
        )
        is None
    )
    assert memory_db.get_stats().total_items == 0


def test_selected_capture_allowlist_cannot_override_core_sensitive_denial(
    memory_db, memory_profile
):
    memory_profile.capture_mode = "selected"
    memory_profile.capture_tools = ["get_secrets", "synthetic_allowed"]
    memory_profile.skip_tools = ["synthetic_custom_skip"]
    capture = MemoryCapture(memory_db, memory_profile)

    assert capture.capture_tool_call("get_secrets", {}, "synthetic") is None
    assert memory_db.get_stats().total_items == 0
    assert capture.capture_tool_call("synthetic_allowed", {}, "synthetic") is not None
    assert memory_db.get_stats().total_items == 1


def test_custom_skips_extend_core_denial_without_blocking_unrelated_tools(
    memory_db, memory_profile
):
    memory_profile.skip_tools = ["synthetic_custom_skip"]
    capture = MemoryCapture(memory_db, memory_profile)

    assert not should_capture_tool("SYNTHETIC_CUSTOM_SKIP", memory_profile.skip_tools)
    assert capture.capture_tool_call("SYNTHETIC_CUSTOM_SKIP", {}, "synthetic") is None
    assert should_capture_tool("synthetic_safe", memory_profile.skip_tools)
    assert capture.capture_tool_call("synthetic_safe", {}, "synthetic") is not None
    assert memory_db.get_stats().total_items == 1
