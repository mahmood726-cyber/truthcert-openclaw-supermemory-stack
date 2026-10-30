"""
Memory leak validator - CRITICAL: Memory is never evidence.

This validator enforces the non-negotiable boundary that memory content
cannot be used as evidence for certified numeric claims.

Enhanced with detection for evasion attempts:
- Base64 encoded memory references
- Unicode confusables (homoglyphs)
- Leetspeak variations
- Nested/obfuscated references
- URL-encoded memory references (including double-encoding)
- RTL/bidi control character attacks
"""

import base64
import binascii
import re
import unicodedata
from typing import Any, ClassVar
from urllib.parse import unquote

from ..constants import MEMORY_SOURCE_LITERAL, Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry

# RTL/bidi control characters to strip (security: prevent text direction attacks)
RTL_BIDI_CHARS = [
    "\u202a",  # LRE - Left-to-Right Embedding
    "\u202b",  # RLE - Right-to-Left Embedding
    "\u202c",  # PDF - Pop Directional Formatting
    "\u202d",  # LRO - Left-to-Right Override
    "\u202e",  # RLO - Right-to-Left Override
    "\u2066",  # LRI - Left-to-Right Isolate
    "\u2067",  # RLI - Right-to-Left Isolate
    "\u2068",  # FSI - First Strong Isolate
    "\u2069",  # PDI - Pop Directional Isolate
]

# Unicode confusables mapping (homoglyphs that look like ASCII)
CONFUSABLES = {
    # Latin homoglyphs
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",  # Cyrillic
    "ɑ": "a",
    "ε": "e",
    "ι": "i",
    "ο": "o",
    "υ": "u",  # Greek omicron (U+03BF)
    "ａ": "a",
    "ｂ": "b",
    "ｃ": "c",
    "ｄ": "d",
    "ｅ": "e",
    "ｆ": "f",
    "ｇ": "g",  # Fullwidth
    "ｈ": "h",
    "ｉ": "i",
    "ｊ": "j",
    "ｋ": "k",
    "ｌ": "l",
    "ｍ": "m",
    "ｎ": "n",
    "ｏ": "o",
    "ｐ": "p",
    "ｑ": "q",
    "ｒ": "r",
    "ｓ": "s",
    "ｔ": "t",
    "ｕ": "u",
    "ｖ": "v",
    "ｗ": "w",
    "ｘ": "x",
    "ｙ": "y",
    "ｚ": "z",
    # Zero-width characters (strip)
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
}

# Leetspeak substitutions
LEETSPEAK = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
    "!": "i",
    "|": "l",
}


def url_decode_recursive(text: str, max_iterations: int = 3) -> str:
    """
    Recursively decode URL-encoded strings to handle double/triple encoding.

    Handles attacks like:
    - memory%3A -> memory:
    - memory%253A -> memory%3A -> memory: (double-encoded)
    - memory%25253A -> memory%253A -> memory%3A -> memory: (triple-encoded)

    Args:
        text: Text that may contain URL-encoded sequences
        max_iterations: Maximum decode iterations to prevent infinite loops

    Returns:
        Fully decoded text
    """
    result = text
    for _ in range(max_iterations):
        decoded = unquote(result)
        if decoded == result:
            # No more decoding needed
            break
        result = decoded
    return result


def normalize_text(text: str) -> str:
    """
    Normalize text to detect obfuscated memory references.

    Handles:
    - URL encoding (including double/triple encoding)
    - Unicode NFC normalization
    - RTL/bidi control characters
    - Unicode confusables
    - Leetspeak
    - Mixed case
    - Zero-width characters

    Security note: This function is critical for detecting evasion attempts
    where attackers try to hide "memory:" patterns using various encoding tricks.
    """
    # Step 1: URL decode (handles memory%3A, memory%253A, etc.)
    result = url_decode_recursive(text)

    # Step 2: Apply Unicode NFC normalization (canonicalize composed characters)
    # This ensures that characters like 'e' + combining acute accent become 'é'
    result = unicodedata.normalize("NFC", result)

    # Step 3: Convert to lowercase
    result = result.lower()

    # Step 4: Strip RTL/bidi control characters (prevent text direction attacks)
    for char in RTL_BIDI_CHARS:
        result = result.replace(char, "")

    # Step 5: Remove zero-width characters and soft hyphen
    for char in ["\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad"]:
        result = result.replace(char, "")

    # Step 6: Replace confusables (homoglyphs)
    for conf, ascii_char in CONFUSABLES.items():
        result = result.replace(conf, ascii_char)

    # Step 7: Replace leetspeak
    for leet, char in LEETSPEAK.items():
        result = result.replace(leet, char)

    return result


def check_base64_for_memory(text: str) -> str | None:
    """
    Check if text contains base64-encoded memory references.

    Returns decoded content if memory reference found, None otherwise.
    """
    # Find potential base64 strings (at least 8 chars)
    b64_pattern = re.compile(r"[A-Za-z0-9+/]{8,}={0,2}")

    for match in b64_pattern.finditer(text):
        try:
            decoded = base64.b64decode(match.group()).decode("utf-8", errors="ignore")
            normalized = normalize_text(decoded)
            if any(
                pattern.replace(":", "") in normalized
                for pattern in ["memory", "recall", "remembered", "supermemory", "mem"]
            ):
                return decoded
        except (binascii.Error, ValueError):
            # Malformed candidate, not evidence; internal processing failures
            # propagate to Validator.run, which returns a blocking failure.
            continue

    return None


@ValidatorRegistry.register
class MemoryLeakValidator(Validator):
    """
    CRITICAL VALIDATOR: Detects and blocks claims that cite memory as evidence.

    Non-negotiable rule: Memory is never evidence.

    This validator checks for:
    1. Evidence URIs starting with "memory:" prefix
    2. Evidence source types of "memory"
    3. Evidence metadata containing memory references
    4. Provenance fields referencing memory
    5. Base64-encoded memory references (evasion attempt)
    6. Unicode confusables/homoglyphs (evasion attempt)
    7. Leetspeak variations (evasion attempt)
    8. Obfuscated references in nested structures

    Any detection results in BLOCK severity - no exceptions.
    """

    name = "memory_leak"
    description = "Blocks claims citing memory as evidence (with anti-evasion)"
    default_severity = Severity.BLOCK

    # Patterns that indicate memory references (direct)
    MEMORY_PATTERNS: ClassVar[list[str]] = [
        "memory:",
        "mem:",
        "recall:",
        "remembered:",
        "supermemory:",
        "mемоry:",  # Cyrillic
        "мemory:",  # Mixed
        "m3m0ry:",  # Leetspeak
        "m3mory:",
        "mem0ry:",
    ]

    # Additional patterns for normalized text
    NORMALIZED_PATTERNS: ClassVar[list[str]] = [
        "memory",
        "recall",
        "remembered",
        "supermemory",
    ]

    # Suspicious keys in metadata that might hide memory refs
    SUSPICIOUS_KEYS: ClassVar[list[str]] = [
        "source",
        "origin",
        "derived_from",
        "based_on",
        "reference",
        "citation",
        "from",
        "via",
        "using",
        "data_source",
    ]

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate that no claims cite memory as evidence.

        This is a BLOCKING validator - any memory reference fails certification.

        Enhanced detection includes:
        - Direct pattern matching
        - Normalized pattern matching (homoglyphs, leetspeak)
        - Base64 decoding
        - Deep metadata inspection
        """
        memory_leaks = []

        for claim in claims:
            # Check evidence URIs
            for i, evidence in enumerate(claim.evidence):
                # Check URI patterns (direct)
                uri_lower = evidence.uri.lower()
                for pattern in self.MEMORY_PATTERNS:
                    if uri_lower.startswith(pattern):
                        memory_leaks.append(
                            {
                                "claim_id": claim.claim_id,
                                "evidence_index": i,
                                "evidence_uri": evidence.uri[:100],
                                "issue": f"Evidence URI starts with memory pattern: {pattern}",
                                "rule": "MEMORY IS NEVER EVIDENCE",
                                "detection": "direct_pattern",
                            }
                        )
                        break

                # Check URI with normalization (anti-evasion)
                uri_normalized = normalize_text(evidence.uri)
                for pattern in self.NORMALIZED_PATTERNS:
                    if uri_normalized.startswith(pattern + ":") or f"/{pattern}:" in uri_normalized:
                        memory_leaks.append(
                            {
                                "claim_id": claim.claim_id,
                                "evidence_index": i,
                                "evidence_uri": evidence.uri[:100],
                                "issue": f"Evidence URI contains obfuscated memory pattern (normalized: {pattern})",
                                "rule": "MEMORY IS NEVER EVIDENCE",
                                "detection": "normalized_pattern",
                            }
                        )
                        break

                # Check for base64-encoded memory references
                b64_decoded = check_base64_for_memory(evidence.uri)
                if b64_decoded:
                    memory_leaks.append(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_index": i,
                            "evidence_uri": evidence.uri[:100],
                            "issue": "Evidence URI contains base64-encoded memory reference",
                            "decoded_content": b64_decoded[:50],
                            "rule": "MEMORY IS NEVER EVIDENCE",
                            "detection": "base64_evasion",
                        }
                    )

                # Check source type
                source_type_lower = evidence.source_type.value.lower()
                source_type_normalized = normalize_text(evidence.source_type.value)
                if source_type_lower == MEMORY_SOURCE_LITERAL or source_type_normalized == "memory":
                    memory_leaks.append(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_index": i,
                            "evidence_uri": evidence.uri[:100],
                            "issue": "Evidence source_type is 'memory'",
                            "rule": "MEMORY IS NEVER EVIDENCE",
                            "detection": "source_type",
                        }
                    )

                # Check metadata for memory references (deep inspection)
                meta_leak = self._check_metadata_for_memory(evidence.metadata, deep=True)
                if meta_leak:
                    memory_leaks.append(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_index": i,
                            "evidence_uri": evidence.uri[:100],
                            "issue": f"Evidence metadata contains memory reference: {meta_leak}",
                            "rule": "MEMORY IS NEVER EVIDENCE",
                            "detection": "metadata",
                        }
                    )

            # Check claim provenance for memory-only sources
            prov_leak = self._check_provenance_memory_only(claim.provenance, deep=True)
            if prov_leak:
                memory_leaks.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Claim provenance indicates memory-only source: {prov_leak}",
                        "rule": "MEMORY IS NEVER EVIDENCE",
                        "detection": "provenance",
                    }
                )

            # Check claim metadata
            meta_leak = self._check_metadata_for_memory(claim.metadata, deep=True)
            if meta_leak:
                memory_leaks.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Claim metadata references memory as source: {meta_leak}",
                        "rule": "MEMORY IS NEVER EVIDENCE",
                        "detection": "claim_metadata",
                    }
                )

        passed = len(memory_leaks) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else Severity.INFO,
            message=(
                "No memory leaks detected - claims properly cite external evidence"
                if passed
                else f"MEMORY LEAK DETECTED: {len(memory_leaks)} claims cite memory as evidence"
            ),
            details={
                "memory_leaks": memory_leaks,
                "rule": "Memory is never evidence. All certified claims must cite OA sources or fixtures.",
                "detection_methods": [
                    "direct_pattern",
                    "normalized_pattern",
                    "base64_evasion",
                    "source_type",
                    "metadata",
                    "provenance",
                ],
            },
        )

    def _check_metadata_for_memory(
        self, metadata: dict[str, Any], deep: bool = False
    ) -> str | None:
        """
        Check if metadata contains memory references.

        Args:
            metadata: Metadata dictionary to check
            deep: If True, perform deep inspection including base64 and normalization

        Returns:
            Description of the leak if found, None otherwise
        """
        if not metadata:
            return None

        # Check for explicit memory source markers
        for key in self.SUSPICIOUS_KEYS:
            value = metadata.get(key, "")
            if isinstance(value, str):
                value_lower = value.lower()
                if value_lower in ["memory", "recall", "remembered", "supermemory"]:
                    return f"key '{key}' = '{value}'"

                if deep:
                    # Check normalized value
                    value_normalized = normalize_text(value)
                    for pattern in self.NORMALIZED_PATTERNS:
                        if value_normalized == pattern or value_normalized.startswith(
                            pattern + ":"
                        ):
                            return f"key '{key}' contains obfuscated '{pattern}'"

                    # Check for base64-encoded references
                    b64_decoded = check_base64_for_memory(value)
                    if b64_decoded:
                        return f"key '{key}' contains base64-encoded memory reference"

        # Check for memory_id field (any variation)
        memory_id_keys = ["memory_id", "recall_id", "mem_id", "supermemory_id"]
        for key in memory_id_keys:
            if key in metadata or key.replace("_", "") in metadata:
                return f"contains memory ID key '{key}'"

        # Check for source_type field
        source_type = metadata.get("source_type", "")
        if isinstance(source_type, str):
            source_type_normalized = normalize_text(source_type)
            if source_type_normalized == "memory":
                return "source_type = 'memory'"

        # Deep inspection: recursively check nested dicts
        if deep:
            for key, value in metadata.items():
                if isinstance(value, dict):
                    nested_leak = self._check_metadata_for_memory(value, deep=True)
                    if nested_leak:
                        return f"nested in '{key}': {nested_leak}"
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            nested_leak = self._check_metadata_for_memory(item, deep=True)
                            if nested_leak:
                                return f"nested in '{key}[{i}]': {nested_leak}"
                        elif isinstance(item, str):
                            item_normalized = normalize_text(item)
                            for pattern in self.NORMALIZED_PATTERNS:
                                if item_normalized.startswith(pattern + ":"):
                                    return f"list '{key}' contains '{pattern}' reference"

        return None

    def _check_provenance_memory_only(
        self, provenance: dict[str, Any], deep: bool = False
    ) -> str | None:
        """
        Check if provenance indicates memory-only derivation.

        Args:
            provenance: Provenance dictionary to check
            deep: If True, perform deep inspection

        Returns:
            Description of the leak if found, None otherwise
        """
        if not provenance:
            return None

        # Check derivation chain
        derivation = provenance.get("derivation", [])
        if isinstance(derivation, list):
            for i, step in enumerate(derivation):
                if isinstance(step, dict):
                    source = step.get("source", "")
                    if isinstance(source, str):
                        source_lower = source.lower()
                        if source_lower.startswith("memory"):
                            return f"derivation[{i}].source = '{source}'"

                        if deep:
                            source_normalized = normalize_text(source)
                            for pattern in self.NORMALIZED_PATTERNS:
                                if source_normalized.startswith(pattern):
                                    return f"derivation[{i}].source contains obfuscated '{pattern}'"

        # Check source field directly
        source = provenance.get("source", "")
        if isinstance(source, str):
            source_lower = source.lower()
            if source_lower.startswith("memory"):
                return f"source = '{source}'"

            if deep:
                source_normalized = normalize_text(source)
                for pattern in self.NORMALIZED_PATTERNS:
                    if source_normalized.startswith(pattern):
                        return f"source contains obfuscated '{pattern}'"

                # Check for base64 in provenance
                b64_decoded = check_base64_for_memory(source)
                if b64_decoded:
                    return "source contains base64-encoded memory reference"

        # Deep inspection of all provenance fields
        if deep:
            for key, value in provenance.items():
                if key in ["derivation", "source"]:
                    continue  # Already checked
                if isinstance(value, str):
                    value_normalized = normalize_text(value)
                    for pattern in self.NORMALIZED_PATTERNS:
                        if pattern in value_normalized:
                            return f"provenance.{key} contains '{pattern}'"

        return None
