"""Synthetic fail-closed checks for explicitly supplied publication-bias statistics.

These check typed plausibility/refusal, not external source authentication.
"""

import math

import pytest

from certifier.constants import CertificationProfile, Severity
from certifier.models import ClaimType, EvidenceLocator, EvidenceType, NumericClaim, ScopeLock
from certifier.validators.domain_pack_publication_bias import PublicationBiasValidator


@pytest.fixture
def synthetic_scope():
    return ScopeLock(
        scope_id="synthetic-bias-scope",
        policy_id="synthetic-bias-policy",
        profile=CertificationProfile.GOLD,
    )


def synthetic_claim(metadata):
    return NumericClaim(
        claim_id="synthetic-publication-bias",
        claim_type=ClaimType.EGGER_INTERCEPT,
        value=0.2,
        metadata=metadata,
        evidence=[
            EvidenceLocator(
                source_type=EvidenceType.FIXTURE,
                uri="synthetic://publication-bias",
                content_hash="sha256:" + "b" * 64,
            )
        ],
    )


@pytest.mark.parametrize(
    ("metadata", "field"),
    [
        ({"egger_p": math.nan}, "egger_p"),
        ({"egger_p": math.inf}, "egger_p"),
        ({"egger_p": -math.inf}, "egger_p"),
        ({"Egger-p": math.nan}, "Egger-p"),
        ({"egger_p": "0.05"}, "egger_p"),
        ({"egger_p": None}, "egger_p"),
        ({"egger_p": True}, "egger_p"),
        ({"begg_tau": math.inf}, "begg_tau"),
        ({"fsn": "100"}, "fsn"),
        ({"imputed_studies": False}, "imputed_studies"),
        ({"peters_p": math.nan}, "peters_p"),
        ({"harbord_p": math.inf}, "harbord_p"),
        ({"egger_p": 0.5, "k": math.nan}, "k"),
    ],
)
def test_malformed_declared_statistic_refuses(metadata, field, synthetic_scope):
    result = PublicationBiasValidator().run([synthetic_claim(metadata)], synthetic_scope, {})
    assert result.details["validated_count"] == 1
    assert not result.passed
    assert result.severity == Severity.BLOCK
    assert any(
        error.get("statistic") == field
        and "not a finite numeric value" in error["issue"]
        for error in result.details["errors"]
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"peters_p": -0.01},
        {"harbord_p": 1.01},
        {"fsn": -1},
        {"begg_tau": -1.01},
        {"egger_p": 1.01},
    ],
)
def test_out_of_range_statistic_refuses_even_without_other_bias_keys(metadata, synthetic_scope):
    result = PublicationBiasValidator().run([synthetic_claim(metadata)], synthetic_scope, {})
    assert result.details["validated_count"] == 1
    assert not result.passed
    assert result.severity == Severity.BLOCK
    assert result.details["errors"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"egger_p": 0.5, "k": 15},
        {"Egger-p": 0.5, "k": 15},
        {"peters_p": 0.5, "k": 15},
        {"harbord_p": 0.5, "k": 15},
        {"begg_tau": 0.3, "begg_p": 0.5, "k": 15},
        {"fsn": 100, "k": 15},
        {"imputed_studies": 0, "k": 15},
    ],
)
def test_valid_synthetic_statistics_remain_accepted(metadata, synthetic_scope):
    result = PublicationBiasValidator().run([synthetic_claim(metadata)], synthetic_scope, {})
    assert result.passed
    assert result.details["validated_count"] == 1
    assert result.details["errors"] == []


def test_no_publication_bias_metadata_is_not_invented_as_checked(synthetic_scope):
    result = PublicationBiasValidator().run(
        [synthetic_claim({"unrelated": "fixture"})], synthetic_scope, {}
    )
    assert result.passed
    assert result.details["validated_count"] == 0
