"""
Multi-Witness Dispute Resolution System.

Implements the TruthCert multi-witness verification with formal dispute resolution.
Based on the Burhan specification requirements:
- ≥3 independent witnesses for GOLD certification
- Formal dispute resolution protocol
- Witness agreement thresholds
- Majority voting with abstention handling

Reference:
TruthCert v3.1.0 Specification - Multi-Witness Protocol
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar

from .models import CertificationProfile, NumericClaim, ScopeLock


class WitnessVerdict(str, Enum):
    """Possible witness verdicts."""

    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"
    ERROR = "error"


class DisputeResolution(str, Enum):
    """Dispute resolution outcomes."""

    CONSENSUS = "consensus"  # All witnesses agree
    MAJORITY = "majority"  # Majority agrees
    SUPERMAJORITY = "supermajority"  # 2/3+ agree
    DEADLOCK = "deadlock"  # No clear majority
    INSUFFICIENT = "insufficient"  # Not enough witnesses


@dataclass
class WitnessResult:
    """Result from a single witness verification."""

    witness_id: str
    verdict: WitnessVerdict
    extracted_value: float | None = None
    confidence: float | None = None
    reasoning: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)

    def compute_hash(self) -> str:
        """Compute hash of witness result for audit."""
        canonical = json.dumps(
            {
                "witness_id": self.witness_id,
                "verdict": self.verdict.value,
                "extracted_value": self.extracted_value,
                "confidence": self.confidence,
            },
            sort_keys=True,
        )
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


@dataclass
class DisputeRecord:
    """Record of a dispute and its resolution."""

    claim_id: str
    witnesses: list[WitnessResult]
    resolution: DisputeResolution
    final_value: float | None = None
    agreement_score: float = 0.0
    majority_threshold: float = 0.5
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolution_details: dict = field(default_factory=dict)


class MultiWitnessVerifier:
    """
    Multi-witness verification system with dispute resolution.

    Profile requirements:
    - BRONZE: Single witness (no multi-witness required)
    - SILVER: 2+ witnesses with simple majority
    - GOLD: 3+ witnesses with supermajority (2/3)

    Dispute resolution protocol:
    1. Collect all witness results
    2. Check for consensus (all agree)
    3. If no consensus, apply majority voting
    4. If deadlock, escalate or reject
    """

    # Witness requirements by profile
    WITNESS_REQUIREMENTS: ClassVar[dict[CertificationProfile, dict[str, float]]] = {
        CertificationProfile.BRONZE: {"min_witnesses": 1, "threshold": 1.0},
        CertificationProfile.SILVER: {"min_witnesses": 2, "threshold": 0.5},
        CertificationProfile.GOLD: {"min_witnesses": 3, "threshold": 2 / 3},
    }

    # Value agreement tolerance (relative)
    VALUE_TOLERANCE: ClassVar[float] = 0.001  # 0.1% relative difference

    def __init__(
        self,
        profile: CertificationProfile = CertificationProfile.SILVER,
        custom_threshold: float | None = None,
    ):
        self.profile = profile
        self.requirements = self.WITNESS_REQUIREMENTS[profile]
        if custom_threshold is not None and not (0 < custom_threshold <= 1):
            raise ValueError("Witness threshold must be in (0, 1]")
        self.threshold = (
            custom_threshold if custom_threshold is not None else self.requirements["threshold"]
        )

    def verify_claim(
        self,
        claim: NumericClaim,
        witness_results: list[WitnessResult],
    ) -> DisputeRecord:
        """
        Verify a claim using multiple witness results.

        Returns a DisputeRecord with resolution outcome.
        """
        # Check minimum witnesses
        if len(witness_results) < self.requirements["min_witnesses"]:
            return DisputeRecord(
                claim_id=claim.claim_id,
                witnesses=witness_results,
                resolution=DisputeResolution.INSUFFICIENT,
                resolution_details={
                    "required": self.requirements["min_witnesses"],
                    "provided": len(witness_results),
                },
            )

        # Nonblank distinct IDs are necessary, but do NOT authenticate identities.
        ids = [w.witness_id for w in witness_results]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
            return DisputeRecord(
                claim_id=claim.claim_id,
                witnesses=witness_results,
                resolution=DisputeResolution.INSUFFICIENT,
                resolution_details={"reason": "duplicate_or_missing_witness_id"},
            )

        # Filter out ERROR results
        valid_witnesses = [w for w in witness_results if w.verdict != WitnessVerdict.ERROR]

        if len(valid_witnesses) < self.requirements["min_witnesses"]:
            return DisputeRecord(
                claim_id=claim.claim_id,
                witnesses=witness_results,
                resolution=DisputeResolution.INSUFFICIENT,
                resolution_details={
                    "required": self.requirements["min_witnesses"],
                    "valid_witnesses": len(valid_witnesses),
                    "errors": len(witness_results) - len(valid_witnesses),
                },
            )

        # Abstention is not an independent affirmative vote; it must not meet
        # the minimum voting quorum, even when a report was submitted.
        active_votes = [
            w
            for w in valid_witnesses
            if w.verdict in (WitnessVerdict.AGREE, WitnessVerdict.DISAGREE)
        ]
        if len(active_votes) < self.requirements["min_witnesses"]:
            return DisputeRecord(
                claim_id=claim.claim_id,
                witnesses=witness_results,
                resolution=DisputeResolution.INSUFFICIENT,
                resolution_details={
                    "required_voting_witnesses": self.requirements["min_witnesses"],
                    "actual_voting_witnesses": len(active_votes),
                },
            )

        # Separate by verdict
        agreeing = [w for w in valid_witnesses if w.verdict == WitnessVerdict.AGREE]
        disagreeing = [w for w in valid_witnesses if w.verdict == WitnessVerdict.DISAGREE]
        abstaining = [w for w in valid_witnesses if w.verdict == WitnessVerdict.ABSTAIN]

        total_voting = len(agreeing) + len(disagreeing)  # Exclude abstentions
        agreement_score = len(agreeing) / total_voting if total_voting > 0 else 0

        # Check for value agreement among agreeing witnesses
        value_agreement = self._check_value_agreement(claim.value, agreeing)

        # Determine resolution
        if len(valid_witnesses) == len(agreeing) and value_agreement:
            # Perfect consensus
            resolution = DisputeResolution.CONSENSUS
            final_value = self._compute_consensus_value(claim.value, agreeing)
        elif (
            value_agreement
            and agreement_score >= self.threshold
            and (self.profile != CertificationProfile.SILVER or agreement_score > 0.5)
        ):
            if agreement_score >= 2 / 3:
                resolution = DisputeResolution.SUPERMAJORITY
            else:
                resolution = DisputeResolution.MAJORITY
            final_value = self._compute_consensus_value(claim.value, agreeing)
        else:
            resolution = DisputeResolution.DEADLOCK
            final_value = None

        return DisputeRecord(
            claim_id=claim.claim_id,
            witnesses=witness_results,
            resolution=resolution,
            final_value=final_value,
            agreement_score=agreement_score,
            majority_threshold=self.threshold,
            resolution_details={
                "agreeing": len(agreeing),
                "disagreeing": len(disagreeing),
                "abstaining": len(abstaining),
                "errors": len(witness_results) - len(valid_witnesses),
                "value_agreement": value_agreement,
                "profile": self.profile.value,
            },
        )

    def _check_value_agreement(
        self,
        claimed_value: float,
        witnesses: list[WitnessResult],
    ) -> bool:
        """Check if witness-extracted values agree with claimed value."""
        if not witnesses:
            return True  # No witnesses to disagree

        extracted_values = [w.extracted_value for w in witnesses if w.extracted_value is not None]

        if not extracted_values:
            # No values extracted, assume agreement on verdict
            return True

        # Check each extracted value against claimed
        for value in extracted_values:
            if claimed_value == 0:
                if abs(value) > self.VALUE_TOLERANCE:
                    return False
            else:
                rel_diff = abs(value - claimed_value) / abs(claimed_value)
                if rel_diff > self.VALUE_TOLERANCE:
                    return False

        return True

    def _compute_consensus_value(
        self,
        claimed_value: float,
        witnesses: list[WitnessResult],
    ) -> float:
        """
        Compute consensus value from witnesses.

        If witnesses extracted values, use weighted average.
        Otherwise, use claimed value.
        """
        extracted = [
            (w.extracted_value, w.confidence or 1.0)
            for w in witnesses
            if w.extracted_value is not None
        ]

        if not extracted:
            return claimed_value

        # Weighted average by confidence
        total_weight = sum(conf for _, conf in extracted)
        if total_weight == 0:
            return claimed_value

        weighted_sum = sum(val * conf for val, conf in extracted)
        return weighted_sum / total_weight


class WitnessOrchestrator:
    """
    Orchestrates multi-witness verification across witnesses.

    In a production system, this would:
    1. Dispatch extraction tasks to multiple LLM instances
    2. Collect and compare results
    3. Run dispute resolution
    4. Record audit trail
    """

    def __init__(
        self,
        witness_ids: list[str],
        profile: CertificationProfile = CertificationProfile.SILVER,
    ):
        self.witness_ids = witness_ids
        self.profile = profile
        self.verifier = MultiWitnessVerifier(profile)

    def create_witness_task(
        self,
        claim: NumericClaim,
        scope_lock: ScopeLock,
    ) -> dict:
        """
        Create a witness verification task.

        Returns task specification for witness execution.
        """
        return {
            "task_id": f"witness-{claim.claim_id}-{datetime.now(UTC).isoformat()}",
            "claim_id": claim.claim_id,
            "expected_value": claim.value,
            "expected_type": claim.claim_type.value,
            "evidence_uris": [e.uri for e in claim.evidence],
            "evidence_hashes": [e.content_hash for e in claim.evidence],
            "scope_lock_hash": scope_lock.compute_hash(),
            "witness_count": len(self.witness_ids),
            "profile": self.profile.value,
        }

    def resolve_dispute(
        self,
        claim: NumericClaim,
        witness_results: list[WitnessResult],
    ) -> tuple[bool, DisputeRecord]:
        """
        Resolve dispute from witness results.

        Returns:
            Tuple of (passed, dispute_record)
        """
        record = self.verifier.verify_claim(claim, witness_results)

        # Determine if verification passed
        passed = record.resolution in (
            DisputeResolution.CONSENSUS,
            DisputeResolution.SUPERMAJORITY,
            DisputeResolution.MAJORITY,
        )

        return passed, record


def simulate_witness_verification(
    claim: NumericClaim,
    n_witnesses: int = 3,
    agreement_rate: float = 1.0,
) -> list[WitnessResult]:
    """
    Simulate witness verification for testing.

    Args:
        claim: Claim to verify
        n_witnesses: Number of witnesses
        agreement_rate: Probability of each witness agreeing

    Returns:
        List of simulated witness results
    """
    import random

    results = []
    for i in range(n_witnesses):
        agrees = random.random() < agreement_rate

        # Add small noise to extracted value
        noise = random.gauss(0, claim.value * 0.0001) if claim.value != 0 else 0
        extracted = claim.value + noise if agrees else claim.value * 1.5

        results.append(
            WitnessResult(
                witness_id=f"witness-{i}",
                verdict=WitnessVerdict.AGREE if agrees else WitnessVerdict.DISAGREE,
                extracted_value=extracted,
                confidence=0.95 if agrees else 0.3,
                reasoning=f"Extracted value {'matches' if agrees else 'differs from'} claim",
            )
        )

    return results
