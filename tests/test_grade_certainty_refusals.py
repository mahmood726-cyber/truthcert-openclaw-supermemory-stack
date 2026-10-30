"""Synthetic positive and negative tests for reported GRADE levels."""

import math

import pytest

from certifier.models import ClaimType
from certifier.validators.grade_validator import GRADECertaintyValidator


def make_claim(sample_claim, metadata, grade_certainty=None):
    return sample_claim.model_copy(update={
        "claim_type": ClaimType.GRADE_CERTAINTY,
        "grade_certainty": grade_certainty,
        "metadata": {"study_design": "RCT", **metadata},
    })


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grade_certainty", "HIGH"),
        ("grade_certainty", " high "),
        ("certainty", "high"),
        ("certainty-of-evidence", "HIGH"),
        ("quality_of_evidence", 4),
        ("grade_certainty", 4.0),
    ],
)
def test_consistent_high_grade_passes(sample_claim, sample_scope_lock, field, value):
    claim = make_claim(sample_claim, {field: value})
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert result.passed, result.details
    assert result.details["validated_count"] == 1
    assert result.details["assessments"][0]["final_certainty"] == "high"


@pytest.mark.parametrize("value", ["LOW", 2, "very-low"])
def test_metadata_grade_mismatch_blocks(sample_claim, sample_scope_lock, value):
    claim = make_claim(sample_claim, {"grade_certainty": value})
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert not result.passed
    assert any(e["issue"] == "Certainty mismatch" for e in result.details["errors"])


@pytest.mark.parametrize(
    "value", [None, True, False, "", "unassessed", math.nan, math.inf, 3.5, [], {}]
)
def test_malformed_explicit_grade_blocks(sample_claim, sample_scope_lock, value):
    claim = make_claim(sample_claim, {"grade_certainty": value})
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert not result.passed
    assert any(
        e["issue"] == "Invalid or conflicting declared GRADE certainty"
        for e in result.details["errors"]
    )


def test_model_metadata_conflict_blocks(sample_claim, sample_scope_lock):
    claim = make_claim(sample_claim, {"grade_certainty": "HIGH"}, "LOW")
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert not result.passed
    assert any(
        e["issue"] == "Invalid or conflicting declared GRADE certainty"
        for e in result.details["errors"]
    )


def test_metadata_alias_conflict_blocks(sample_claim, sample_scope_lock):
    claim = make_claim(sample_claim, {"grade_certainty": "HIGH", "certainty": "LOW"})
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert not result.passed
    assert any(
        e["issue"] == "Invalid or conflicting declared GRADE certainty"
        for e in result.details["errors"]
    )


def test_consistent_model_metadata_passes(sample_claim, sample_scope_lock):
    claim = make_claim(sample_claim, {"grade_certainty": "HIGH"}, "HIGH")
    result = GRADECertaintyValidator().run([claim], sample_scope_lock, {})
    assert result.passed, result.details
