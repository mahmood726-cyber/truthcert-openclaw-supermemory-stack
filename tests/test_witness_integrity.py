"""Synthetic vote-quorum refusals; declarative IDs are not identity attestation."""
import pytest
from certifier.constants import CertificationProfile
from certifier.models import ClaimType, EvidenceLocator, EvidenceType, NumericClaim
from certifier.multi_witness_dispute import (
    DisputeResolution, MultiWitnessVerifier, WitnessOrchestrator, WitnessResult, WitnessVerdict,
)

@pytest.fixture
def claim():
    return NumericClaim(claim_id="synthetic-witness", claim_type=ClaimType.EFFECT_SIZE,
        value=0.5, evidence=[EvidenceLocator(source_type=EvidenceType.FIXTURE,
            uri="fixture://synthetic-witness", content_hash="sha256:" + "a"*64)])

def vote(wid, verdict=WitnessVerdict.AGREE, value=0.5):
    return WitnessResult(witness_id=wid, verdict=verdict, extracted_value=value)

def test_three_distinct_gold_votes_pass(claim):
    result = MultiWitnessVerifier(CertificationProfile.GOLD).verify_claim(
        claim, [vote("a"), vote("b"), vote("c")])
    assert result.resolution == DisputeResolution.CONSENSUS
    assert result.final_value == pytest.approx(0.5)

def test_two_thirds_gold_supermajority(claim):
    passed, result = WitnessOrchestrator(["a","b","c"], CertificationProfile.GOLD).resolve_dispute(
        claim, [vote("a"), vote("b"), vote("c", WitnessVerdict.DISAGREE)])
    assert passed
    assert result.resolution == DisputeResolution.SUPERMAJORITY
    assert result.agreement_score == pytest.approx(2/3)

def test_duplicates_cannot_inflate_gold_quorum(claim):
    passed, result = WitnessOrchestrator(["a","b","c"], CertificationProfile.GOLD).resolve_dispute(
        claim, [vote("a"), vote("a"), vote("b")])
    assert not passed
    assert result.resolution == DisputeResolution.INSUFFICIENT
    assert result.resolution_details["reason"] == "duplicate_or_missing_witness_id"

@pytest.mark.parametrize("wid", ["", "  "])
def test_blank_identity_fails(claim, wid):
    result = MultiWitnessVerifier(CertificationProfile.SILVER).verify_claim(
        claim, [vote(wid), vote("b")])
    assert result.resolution == DisputeResolution.INSUFFICIENT

@pytest.mark.parametrize("nonvote", [WitnessVerdict.ABSTAIN, WitnessVerdict.ERROR])
def test_gold_nonvote_cannot_meet_quorum(claim, nonvote):
    result = MultiWitnessVerifier(CertificationProfile.GOLD).verify_claim(
        claim, [vote("a"), vote("b"), vote("c", nonvote)])
    assert result.resolution == DisputeResolution.INSUFFICIENT

def test_silver_half_is_deadlock(claim):
    passed, result = WitnessOrchestrator(["a","b"], CertificationProfile.SILVER).resolve_dispute(
        claim, [vote("a"), vote("b", WitnessVerdict.DISAGREE)])
    assert not passed
    assert result.resolution == DisputeResolution.DEADLOCK

def test_silver_positive_consensus(claim):
    result = MultiWitnessVerifier(CertificationProfile.SILVER).verify_claim(
        claim, [vote("a"), vote("b")])
    assert result.resolution == DisputeResolution.CONSENSUS

def test_gold_disagreement_in_extracted_value_fails(claim):
    result = MultiWitnessVerifier(CertificationProfile.GOLD).verify_claim(
        claim, [vote("a"), vote("b", value=0.8), vote("c")])
    assert result.resolution == DisputeResolution.DEADLOCK

@pytest.mark.parametrize("threshold", [0, -0.1, 1.1, float("nan")])
def test_invalid_threshold_is_not_silently_accepted(threshold):
    with pytest.raises(ValueError):
        MultiWitnessVerifier(CertificationProfile.GOLD, custom_threshold=threshold)

def test_witness_hash_binds_extracted_value():
    assert vote("a", value=0.5).compute_hash() != vote("a", value=0.8).compute_hash()
