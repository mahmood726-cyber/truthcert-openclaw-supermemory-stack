"""
Memory capture module - auto-capture hooks for chat and tool calls.
"""

import re
from collections.abc import Callable
from typing import Any

from .backend_local_sqlite import LocalSQLiteBackend
from .redaction import Redactor, should_capture_tool
from .schema import MemoryItem, MemoryProfile, MemorySource, MemoryType

_SENSITIVE_FIELD_SUFFIXES = (
    "password",
    "passwd",
    "apikey",
    "apisecret",
    "secretkey",
    "clientsecret",
    "privatekey",
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "sessiontoken",
    "authorization",
    "credential",
    "credentials",
    "secretaccesskey",
    "accountkey",
    "token",
    "secret",
)


def _sensitive_field_name(name: str) -> bool:
    """Recognize credential field names even with case/separator variation."""
    normalized = "".join(char for char in name.casefold() if char.isalnum())
    return normalized == "pwd" or any(
        normalized.endswith(suffix) for suffix in _SENSITIVE_FIELD_SUFFIXES
    )


def _contains_sensitive_field(value: Any) -> bool:
    """Refuse credential-keyed structured data before formatting and truncation.

    Plain text redaction does not match quoted Python/JSON dictionary keys
    such as {'password': '...'}; do not store such tool payloads at all.
    Check nested mappings, list results and stringified structured output.
    A bounded traversal fails closed on pathological or cyclic objects.
    """
    pending = [value]
    seen: set[int] = set()
    inspected = 0
    while pending:
        inspected += 1
        if inspected > 10_000:
            return True
        current = pending.pop()
        if isinstance(current, dict):
            if id(current) in seen:
                continue
            seen.add(id(current))
            for key, nested in current.items():
                if _sensitive_field_name(str(key)):
                    return True
                pending.append(nested)
        elif isinstance(current, (list, tuple)):
            if id(current) in seen:
                continue
            seen.add(id(current))
            pending.extend(current)
        elif isinstance(current, str):
            # Handles JSON and Python repr, not just exact named token formats.
            for key in re.findall(r"""['"]([^'"]+)['"]\s*:""", current):
                if _sensitive_field_name(key):
                    return True
    return False


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
        redactor: Redactor | None = None,
    ) -> None:
        self.backend = backend
        self.profile = profile
        self.redactor = redactor or Redactor()

    def capture_chat_turn(
        self,
        user_message: str,
        assistant_response: str,
        turn_number: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
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

        # Redact before summarizing/truncating: a truncated secret may not
        # match the full-token redaction pattern and can otherwise leak.
        if self.profile.redact_before_store:
            user_message, _ = self.redactor.redact(user_message)
            assistant_response, _ = self.redactor.redact(assistant_response)
        summary = self._summarize_turn(user_message, assistant_response)

        item = MemoryItem(
            type=MemoryType.NOTE,
            source=MemorySource.CHAT,
            text=summary,
            tags=["chat", f"turn_{turn_number}"],
            metadata={
                "turn_number": turn_number,
                **self._safe_metadata(metadata),
            },
        )

        return self.backend.store(item)

    def capture_tool_call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        outputs: Any,
        execution_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
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
        if (self.profile.capture_mode == "selected") and (
            tool_name not in self.profile.capture_tools
        ):
            return None

        # Structured credential fields evade free-text key=value redaction,
        # notably dict repr with quoted keys. Refuse automatic persistence.
        if (
            (self.profile.store_tool_inputs and _contains_sensitive_field(inputs))
            or (self.profile.store_tool_results and _contains_sensitive_field(outputs))
            or _contains_sensitive_field(metadata)
        ):
            return None

        # Build capture text
        parts = [f"Tool: {tool_name}"]

        if self.profile.store_tool_inputs:
            input_str = str(inputs)
            if self.profile.redact_before_store:
                input_str, _ = self.redactor.redact(input_str)
            parts.append(f"Inputs: {input_str[:500]}")

        if self.profile.store_tool_results:
            output_str = str(outputs)
            if self.profile.redact_before_store:
                output_str, _ = self.redactor.redact(output_str)
            parts.append(f"Outputs: {output_str[:1000]}")

        text = "\n".join(parts)

        item = MemoryItem(
            type=MemoryType.TRACE,
            source=MemorySource.TOOL,
            text=text,
            tags=["tool", tool_name],
            metadata={
                "tool_name": tool_name,
                "execution_time_ms": execution_time_ms,
                **self._safe_metadata(metadata),
            },
        )

        return self.backend.store(item)

    def capture_decision(
        self,
        decision: str,
        context: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
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
            tags=["decision"]
            + (
                [self.redactor.redact(t)[0] for t in (tags or [])]
                if self.profile.redact_before_store
                else (tags or [])
            ),
            metadata=self._safe_metadata(metadata),
        )

        return self.backend.store(item)

    def capture_certification_result(
        self,
        bundle_id: str,
        outcome: str,
        profile: str,
        claim_count: int,
        errors: list[str] | None = None,
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

        if self.profile.redact_before_store:
            text, _ = self.redactor.redact(text)

        item = MemoryItem(
            type=MemoryType.DECISION,
            source=MemorySource.SYSTEM,
            text=text,
            tags=["certification", outcome.lower(), profile.lower()],
            metadata=self._safe_metadata(
                {
                    "bundle_id": bundle_id,
                    "outcome": outcome,
                    "profile": profile,
                    "claim_count": claim_count,
                    "errors": errors or [],
                }
            ),
        )

        return self.backend.store(item)

    def _safe_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Apply the configured data-minimisation rule to nested metadata."""
        raw = metadata or {}
        return self.redactor.redact_dict(raw) if self.profile.redact_before_store else raw

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
_capture_hooks: dict[str, list[Callable[..., None]]] = {
    "before_turn": [],
    "after_turn": [],
    "after_tool": [],
}


def register_capture_hook(event: str, callback: Callable[..., None]) -> None:
    """Register a capture hook for an event."""
    if event in _capture_hooks:
        _capture_hooks[event].append(callback)


def trigger_capture_hooks(event: str, **kwargs: Any) -> None:
    """Trigger all hooks for an event."""
    for callback in _capture_hooks.get(event, []):
        try:
            callback(**kwargs)
        except Exception as exc:
            raise RuntimeError("Memory capture hook failed") from exc
