"""Fail-closed synthetic tests for the active witness and determinism validators.

Declarative witness metadata is not external human identity attestation.
"""
import pytest

from certifier.constants import CertificationProfile
from certifier.models import EvidenceLocator, EvidenceType
from certifier.validators.determinism import DeterminismValidator
from certifier.validators.multi_witness import MultiWitnessValidator


def _claim_with_witnesses(sample_claim, witnesses):
    return sample_claim.model_copy(update={"metadata": {"witnesses": witnesses}})


def _scope(sample_scope_lock, profile):
    return sample_scope_lock.model_copy(update={"profile": profile})


def _witness(wid, value=0.45, content_hash=None):
    record = {"witness_id": wid, "value": value}
    if content_hash is not None:
        record["content_hash"] = content_hash
    return record


@pytest.mark.parametrize("profile,count", [
    (CertificationProfile.SILVER, 2),
    (CertificationProfile.GOLD, 3),
])
def test_distinct_agreeing_witnesses_pass(sample_claim, sample_scope_lock, profile, count):
    witnesses = [_witness(f"human-{i}") for i in range(count)]
    result = MultiWitnessValidator().run(
        [_claim_with_witnesses(sample_claim, witnesses)],
        _scope(sample_scope_lock, profile),
        {},
    )
    assert result.passed
    assert result.details["required_witnesses"] == count


@pytest.mark.parametrize("witnesses", [
    [_witness("a"), _witness("a")],
    [_witness("a"), _witness(" a ")],
    [_witness(""), _witness("b")],
    [_witness("  "), _witness("b")],
    [_witness("a"), {"witness_id": "b"}],
    [_witness("a"), _witness("b", value="0.45")],
    [_witness("a"), _witness("b", value=True)],
    [_witness("a"), _witness("b", value=float("nan"))],
    [_witness("a"), _witness("b", value=float("inf"))],
    [_witness("a"), _witness("b", value=0.55)],
    [_witness("a"), "not-a-witness"],
    [_witness("a"), _witness("b", content_hash="hash-a")],
    [_witness("a", content_hash="hash-a"), _witness("b", content_hash="hash-b")],
    [_witness("a", content_hash=""), _witness("b", content_hash="hash-b")],
    [_witness("a")],
])
def test_malformed_or_disagreeing_witnesses_cannot_certify(
    sample_claim, sample_scope_lock, witnesses,
):
    result = MultiWitnessValidator().run(
        [_claim_with_witnesses(sample_claim, witnesses)],
        sample_scope_lock,
        {},
    )
    assert not result.passed, result.model_dump()
    assert result.details["issues"]


@pytest.mark.parametrize("witnesses", [None, {}, "two witnesses"])
def test_nonlist_witnesses_refused(sample_claim, sample_scope_lock, witnesses):
    result = MultiWitnessValidator().run(
        [_claim_with_witnesses(sample_claim, witnesses)],
        sample_scope_lock,
        {},
    )
    assert not result.passed


@pytest.mark.parametrize("requested", [0, -1, True, "2", 1.5])
def test_invalid_context_witness_count_refused(sample_claim, sample_scope_lock, requested):
    result = MultiWitnessValidator().run(
        [sample_claim],
        sample_scope_lock,
        {"witness_count": requested},
    )
    assert not result.passed


def test_bronze_without_witness_requirement_is_explicitly_skipped(
    sample_claim, sample_scope_lock,
):
    result = MultiWitnessValidator().run(
        [sample_claim],
        _scope(sample_scope_lock, CertificationProfile.BRONZE),
        {},
    )
    assert result.passed
    assert "skipped" in result.message.lower()


def _computed_claim(sample_claim, computation):
    evidence = EvidenceLocator(
        source_type=EvidenceType.COMPUTED,
        uri="fixture://determinism-inputs",
        content_hash="sha256:" + "a" * 64,
    )
    return sample_claim.model_copy(update={
        "evidence": [evidence],
        "provenance": {"computation": computation},
    })


@pytest.mark.parametrize("computation", [
    {},
    {"algorithm": "mean", "inputs_hash": "sha256:" + "0" * 64},
    {"algorithm": "mean", "inputs": {}},
    {"algorithm": "", "inputs": {}, "inputs_hash": "sha256:" + "0" * 64},
    {"algorithm": "mean", "inputs": {}, "inputs_hash": "sha256:" + "0" * 64},
    {"algorithm": "bootstrap", "inputs": {}, "inputs_hash": "sha256:" + "0" * 64},
])
def test_missing_or_tampered_computation_metadata_refused(
    sample_claim, sample_scope_lock, computation,
):
    result = DeterminismValidator().run(
        [_computed_claim(sample_claim, computation)],
        sample_scope_lock,
        {},
    )
    assert not result.passed, result.model_dump()


def test_empty_inputs_hash_is_checked_not_bypassed(sample_claim, sample_scope_lock):
    validator = DeterminismValidator()
    inputs = {}
    computation = {
        "algorithm": "deterministic-mean",
        "inputs": inputs,
        "inputs_hash": validator._compute_inputs_hash(inputs),
    }
    result = validator.run(
        [_computed_claim(sample_claim, computation)],
        sample_scope_lock,
        {},
    )
    assert result.passed, result.model_dump()


def test_stochastic_algorithm_with_seed_and_valid_hash_passes(
    sample_claim, sample_scope_lock,
):
    validator = DeterminismValidator()
    inputs = [1, 2, 3]
    computation = {
        "algorithm": "bootstrap",
        "inputs": inputs,
        "inputs_hash": validator._compute_inputs_hash(inputs),
        "seed": 0,
    }
    result = validator.run(
        [_computed_claim(sample_claim, computation)],
        sample_scope_lock,
        {},
    )
    assert result.passed, result.model_dump()
