"""Synthetic memory-as-evidence refusal tests for Unicode identity ambiguity."""

import pytest

from certifier.validators.memory_leak import MemoryLeakValidator, normalize_text


@pytest.mark.parametrize("letter", ["o", "\u043e", "\u03bf", "\uff4f"])
def test_ascii_cyrillic_greek_and_fullwidth_omicron_normalize(letter):
    """All confusable 'o' characters must normalize into a memory: marker."""
    assert normalize_text(f"mem{letter}ry:synthetic-id") == "memory:synthetic-id"


@pytest.mark.parametrize("letter", ["\u043e", "\u03bf", "\uff4f"])
def test_confusable_memory_source_is_refused_in_evidence_metadata(letter):
    """A visually disguised memory reference cannot become external evidence."""
    validator = MemoryLeakValidator()
    result = validator._check_metadata_for_memory(
        {"source": f"mem{letter}ry:synthetic-source"},
        deep=True,
    )
    assert result is not None
    assert "obfuscated" in result


def test_external_source_is_not_rejected_by_memory_normalization():
    """Prevent a false refusal for ordinary non-memory citation metadata."""
    validator = MemoryLeakValidator()
    assert validator._check_metadata_for_memory(
        {"source": "https://example.org/synthetic-trial"},
        deep=True,
    ) is None
