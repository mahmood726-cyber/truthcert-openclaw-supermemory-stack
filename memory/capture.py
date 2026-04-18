"""
Memory capture module - auto-capture hooks for chat and tool calls.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Callable

from .schema import MemoryItem, MemoryType, MemorySource, MemoryProfile
from .backend_local_sqlite import LocalSQLiteBackend
from .redaction import Redactor, should_capture_tool


class MemoryCapture:
    """
    Handles automatic memory capture from chat and tool interactions.

    Features:
    - Chat turn summarization and capture
    - Tool input/output capture
    - Configurable capture modes
    - Redaction before storage
    """

    def __init__(
        self,
        backend: LocalSQLiteBackend,
        profile: MemoryProfile,
        redactor: Optional[Redactor] = None,
    ):
        self.backend = backend
        self.profile = profile
        self.redactor = redactor or Redactor()

    def capture_chat_turn(
        self,
        user_message: str,
        assistant_response: str,
        turn_number: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Capture a chat turn as a memory item.

        Args:
            user_message: The user's message
            assistant_response: The assistant's response
            turn_number: Turn number in conversation
            metadata: Additional metadata

        Returns:
            Memory item ID if captured, None if skipped
        """
        if not self.profile.auto_capture:
            return None

        # Create summary of the turn
        summary = self._summarize_turn(user_message, assistant_response)

        # Redact if enabled
        if self.profile.redact_before_store:
            summary, _ = self.redactor.redact(summary)

        item = MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text=summary,
            tags=["chat", f"turn_{turn_number}"],
            metadata={
                "turn_number": turn_number,
                **(metadata or {}),
            },
        )

        return self.backend.store(item)

    def capture_tool_call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        outputs: Any,
        execution_time_ms: float = 0.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Capture a tool call as a memory item.

        Args:
            tool_name: Name of the tool
            inputs: Tool inputs
            outputs: Tool outputs
            execution_time_ms: Execution time
            metadata: Additional metadata

        Returns:
            Memory item ID if captured, None if skipped
        """
        if not self.profile.auto_capture:
            return None

        # Check denylist
        if not should_capture_tool(tool_name, self.profile.skip_tools):
            return None

        # Check allowlist if in selected mode
        if self.profile.capture_mode == "selected":
            if tool_name not in self.profile.capture_tools:
                return None

        # Build capture text
        parts = [f"Tool: {tool_name}"]

        if self.profile.store_tool_inputs:
            input_str = str(inputs)[:500]  # Truncate
            if self.profile.redact_before_store:
                input_str, _ = self.redactor.redact(input_str)
            parts.append(f"Inputs: {input_str}")

        if self.profile.store_tool_results:
            output_str = str(outputs)[:1000]  # Truncate
            if self.profile.redact_before_store:
                output_str, _ = self.redactor.redact(output_str)
            parts.append(f"Outputs: {output_str}")

        text = "\n".join(parts)

        item = MemoryItem(
            type=MemoryType.TRACE,
            source=MemorySource.TOOL,
            text=text,
            tags=["tool", tool_name],
            metadata={
                "tool_name": tool_name,
                "execution_time_ms": execution_time_ms,
                **(metadata or {}),
            },
        )

        return self.backend.store(item)

    def capture_decision(
        self,
        decision: str,
        context: str = "",
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Capture a decision as a memory item.

        Args:
            decision: The decision made
            context: Context for the decision
            tags: Tags for the decision
            metadata: Additional metadata

        Returns:
            Memory item ID
        """
        text = decision
        if context:
            text = f"{decision}\n\nContext: {context}"

        if self.profile.redact_before_store:
            text, _ = self.redactor.redact(text)

        item = MemoryItem(
            type=MemoryType.DECISION,
            source=MemorySource.CHAT,
            text=text,
            tags=["decision"] + (tags or []),
            metadata=metadata or {},
        )

        return self.backend.store(item)

    def capture_certification_result(
        self,
        bundle_id: str,
        outcome: str,
        profile: str,
        claim_count: int,
        errors: Optional[list[str]] = None,
    ) -> str:
        """
        Capture a certification result as a memory item.

        This helps with long-term continuity but is NOT evidence.

        Args:
            bundle_id: The bundle ID
            outcome: PASS or REJECT
            profile: Certification profile used
            claim_count: Number of claims
            errors: Any errors

        Returns:
            Memory item ID
        """
        text = f"Certification {outcome}: {bundle_id}\n"
        text += f"Profile: {profile}, Claims: {claim_count}\n"
        if errors:
            text += f"Errors: {', '.join(errors)}"

        item = MemoryItem(
            type=MemoryType.DECISION,
            source=MemorySource.SYSTEM,
            text=text,
            tags=["certification", outcome.lower(), profile.lower()],
            metadata={
                "bundle_id": bundle_id,
                "outcome": outcome,
                "profile": profile,
                "claim_count": claim_count,
                "errors": errors or [],
            },
        )

        return self.backend.store(item)

    def _summarize_turn(
        self,
        user_message: str,
        assistant_response: str,
    ) -> str:
        """
        Create a compact summary of a chat turn.

        Uses simple truncation for now - could be enhanced with
        LLM-based summarization.
        """
        # Simple summarization: truncate to key content
        user_summary = user_message[:200]
        if len(user_message) > 200:
            user_summary += "..."

        # Extract key points from response (first sentence or two)
        response_parts = assistant_response.split(".")
        response_summary = ".".join(response_parts[:2])
        if len(response_summary) > 300:
            response_summary = response_summary[:300] + "..."

        return f"User: {user_summary}\nAssistant: {response_summary}"


# Hook registration for integration
_capture_hooks: dict[str, list[Callable]] = {
    "before_turn": [],
    "after_turn": [],
    "after_tool": [],
}


def register_capture_hook(event: str, callback: Callable) -> None:
    """Register a capture hook for an event."""
    if event in _capture_hooks:
        _capture_hooks[event].append(callback)


def trigger_capture_hooks(event: str, **kwargs) -> None:
    """Trigger all hooks for an event."""
    for callback in _capture_hooks.get(event, []):
        try:
            callback(**kwargs)
        except Exception:
            pass  # Don't let hook errors break the flow
