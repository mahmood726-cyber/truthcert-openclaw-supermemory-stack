"""
Memory drift validator - detects when memory contradicts extracted evidence.
"""

from typing import Any, ClassVar

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class MemoryDriftValidator(Validator):
    """
    Detects when memory-based expectations contradict extracted evidence.

    This validator checks claim metadata for 'expected_*' fields that may
    have been populated from memory, and compares them against actual values.

    Severity depends on profile:
    - BRONZE: INFO only
    - SILVER: WARN
    - GOLD: BLOCK
    """

    name = "memory_drift"
    description = "Detects memory vs evidence contradictions"
    default_severity = Severity.WARN

    # Fields to check for drift
    DRIFT_FIELDS: ClassVar[list[tuple[str, str]]] = [
        ("expected_n", "sample_size"),
        ("expected_value", "value"),
        ("expected_effect", "value"),
        ("memory_n", "sample_size"),
        ("memory_value", "value"),
    ]

    # Tolerance for numeric comparisons (relative)
    DEFAULT_TOLERANCE = 0.01  # 1% difference

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate for memory drift."""
        drifts = []
        tolerance = self.config.params.get("tolerance", self.DEFAULT_TOLERANCE)

        for claim in claims:
            # Check metadata for expected values from memory
            for memory_field, claim_field in self.DRIFT_FIELDS:
                expected = claim.metadata.get(memory_field)
                if expected is None:
                    continue

                # Get actual value
                actual: float | None = None
                if claim_field == "value":
                    actual = claim.value
                elif claim_field == "sample_size":
                    # Sample size might be in metadata or derived
                    actual = claim.metadata.get("n") or claim.metadata.get("sample_size")

                if actual is None:
                    continue

                # Compare values
                try:
                    expected_float = float(expected)
                    actual_float = float(actual)

                    # Check for drift
                    if not self._values_match(expected_float, actual_float, tolerance):
                        drift_pct = (
                            abs(expected_float - actual_float)
                            / max(abs(expected_float), 1e-10)
                            * 100
                        )
                        drifts.append(
                            {
                                "claim_id": claim.claim_id,
                                "field": memory_field,
                                "expected_from_memory": expected_float,
                                "actual_from_evidence": actual_float,
                                "drift_percentage": round(drift_pct, 2),
                                "issue": f"Memory expected {expected_float}, evidence shows {actual_float}",
                            }
                        )
                except (ValueError, TypeError):
                    # Non-numeric comparison
                    if str(expected) != str(actual):
                        drifts.append(
                            {
                                "claim_id": claim.claim_id,
                                "field": memory_field,
                                "expected_from_memory": str(expected),
                                "actual_from_evidence": str(actual),
                                "issue": f"Memory expected '{expected}', evidence shows '{actual}'",
                            }
                        )

        # Determine severity based on profile
        severity = self._get_severity_for_profile(scope_lock.profile)
        passed = len(drifts) == 0 or severity == Severity.INFO

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=severity if drifts else Severity.INFO,
            message=(
                "No memory drift detected"
                if not drifts
                else f"Memory drift detected in {len(drifts)} claims"
            ),
            details={
                "drifts": drifts,
                "tolerance": tolerance,
                "profile": scope_lock.profile.value,
            },
        )

    def _values_match(self, v1: float, v2: float, tolerance: float) -> bool:
        """Check if two values match within tolerance."""
        if v1 == v2:
            return True

        # Handle zero case
        if v1 == 0 or v2 == 0:
            return abs(v1 - v2) < tolerance

        # Relative difference
        rel_diff = abs(v1 - v2) / max(abs(v1), abs(v2))
        return rel_diff <= tolerance

    def _get_severity_for_profile(self, profile: CertificationProfile) -> Severity:
        """Get appropriate severity based on certification profile."""
        if profile == CertificationProfile.GOLD:
            return Severity.BLOCK
        elif profile == CertificationProfile.SILVER:
            return Severity.WARN
        else:
            return Severity.INFO
