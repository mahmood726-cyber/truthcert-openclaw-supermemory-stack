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
    assert (
        validator._check_metadata_for_memory(
            {"source": "https://example.org/synthetic-trial"},
            deep=True,
        )
        is None
    )


def test_malformed_base64_candidate_does_not_create_a_false_memory_refusal():
    """A padded-string decoding error is not itself evidence of memory use."""
    from certifier.validators.memory_leak import check_base64_for_memory

    assert check_base64_for_memory("AAAAAAAAAA") is None


def test_unexpected_base64_normalization_failure_is_not_silently_ignored(monkeypatch):
    """Internal detection failure must propagate into blocking validator handling."""
    from certifier.validators import memory_leak

    def broken_normalizer(_value):
        raise RuntimeError("synthetic normalizer failure")

    monkeypatch.setattr(memory_leak, "normalize_text", broken_normalizer)
    with pytest.raises(RuntimeError, match="synthetic normalizer failure"):
        memory_leak.check_base64_for_memory("bWVtb3J5OnN5bnRoZXRpYw==")
