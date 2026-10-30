"""Synthetic risk-of-bias contract tests; no assessment of real studies."""

import pytest

from certifier.models import ValidatorConfig
from certifier.validators.risk_of_bias import (
    PROBASTValidator,
    QUADAS2Validator,
    ROB2Validator,
    ROBINSIValidator,
)


PACKS = [
    (ROB2Validator, "rob2_assessments"),
    (ROBINSIValidator, "robinsi_assessments"),
    (QUADAS2Validator, "quadas2_assessments"),
    (PROBASTValidator, "probast_assessments"),
]


def complete_assessment(validator_class):
    """Create internally coherent but synthetic domain judgments."""
    if validator_class in (ROB2Validator, ROBINSIValidator):
        return {
            "domain_judgments": {name: "low" for name in validator_class.DOMAIN_KEYS},
            "domain_support": {name: "synthetic assessment" for name in validator_class.DOMAIN_KEYS},
            "overall_judgment": "low",
        }
    return {
        "domain_risk_of_bias": {name: "low" for name in validator_class.DOMAIN_KEYS},
        "domain_applicability": {
            name: "low"
            for name in (
                QUADAS2Validator.DOMAIN_KEYS[:-1]
                if validator_class is QUADAS2Validator
                else PROBASTValidator.APPLICABILITY_DOMAINS
            )
        },
        "domain_support": {name: "synthetic assessment" for name in validator_class.DOMAIN_KEYS},
        **(
            {
                "overall_risk_of_bias": "low",
                "overall_applicability": "low",
            }
            if validator_class is PROBASTValidator
            else {}
        ),
    }


def run_assessment(validator_class, metadata_key, assessment, scope):
    config = ValidatorConfig(
        name=validator_class.name,
        params={"strict_mode": True, "require_support": True},
    )
    locked = scope.model_copy(update={"metadata": {metadata_key: {"study-synthetic": assessment}}})
    return validator_class(config).run([], locked, {})


@pytest.mark.parametrize(("validator_class", "metadata_key"), PACKS)
def test_complete_synthetic_assessment_validates(
    sample_scope_lock, validator_class, metadata_key
):
    assessment = complete_assessment(validator_class)
    result = run_assessment(validator_class, metadata_key, assessment, sample_scope_lock)
    assert result.passed, result.details
    assert result.details["studies_assessed"] == 1
    assert result.details["complete_assessments"] == 1
    assert not result.details["errors"]


@pytest.mark.parametrize(("validator_class", "metadata_key"), PACKS)
def test_strict_mode_refuses_missing_domain_assessments(
    sample_scope_lock, validator_class, metadata_key
):
    result = run_assessment(validator_class, metadata_key, {}, sample_scope_lock)
    assert not result.passed
    assert result.details["errors"]
    assert result.details["complete_assessments"] == 0


@pytest.mark.parametrize(("validator_class", "metadata_key"), PACKS)
def test_invalid_judgment_is_blocked(
    sample_scope_lock, validator_class, metadata_key
):
    assessment = complete_assessment(validator_class)
    field = (
        "domain_judgments"
        if validator_class in (ROB2Validator, ROBINSIValidator)
        else "domain_risk_of_bias"
    )
    assessment[field][validator_class.DOMAIN_KEYS[0]] = "synthetic-invalid-level"
    result = run_assessment(validator_class, metadata_key, assessment, sample_scope_lock)
    assert not result.passed
    assert any(
        "Invalid judgment" in error["issue"]
        for error in result.details["errors"]
    )


@pytest.mark.parametrize(("validator_class", "metadata_key"), PACKS)
def test_overall_or_summary_reflects_non_low_domains(
    sample_scope_lock, validator_class, metadata_key
):
    assessment = complete_assessment(validator_class)
    field = (
        "domain_judgments"
        if validator_class in (ROB2Validator, ROBINSIValidator)
        else "domain_risk_of_bias"
    )
    assessment[field][validator_class.DOMAIN_KEYS[0]] = "high" if validator_class is not ROBINSIValidator else "critical"
    result = run_assessment(validator_class, metadata_key, assessment, sample_scope_lock)
    assert result.passed, result.details
    if validator_class in (ROB2Validator, ROBINSIValidator, PROBASTValidator):
        assert any(
            "inconsistent" in warning["issue"]
            for warning in result.details["warnings"]
        )
    else:
        assert result.details["summary"]["risk_of_bias"]["patient_selection"]["high"] == 1


@pytest.mark.parametrize(
    ("validator_class", "metadata_key", "flag"),
    [
        (ROB2Validator, "rob2_assessments", None),
        (ROBINSIValidator, "robinsi_assessments", "has_nonrandomized_studies"),
        (QUADAS2Validator, "quadas2_assessments", "is_diagnostic_accuracy_review"),
        (PROBASTValidator, "probast_assessments", "is_prediction_model_review"),
    ],
)
def test_missing_risk_assessments_are_explicitly_flagged_not_counted(
    sample_scope_lock, validator_class, metadata_key, flag
):
    metadata = {flag: True} if flag else {}
    locked = sample_scope_lock.model_copy(update={"metadata": metadata})
    result = validator_class().run([], locked, {})
    assert result.passed
    assert result.details["warnings"]
    assert "No " in result.message
