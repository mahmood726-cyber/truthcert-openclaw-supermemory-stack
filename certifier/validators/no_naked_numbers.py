"""
No naked numbers validator - ensures all claims have provenance.
"""

from typing import Any

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class NoNakedNumbersValidator(Validator):
    """
    Validates that all numeric claims have proper provenance coverage.
    No naked numbers allowed - every claim must trace back to evidence.
    """

    name = "no_naked_numbers"
    description = "Ensures all claims have provenance and evidence"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate provenance coverage."""
        issues: list[dict[str, Any]] = []
        naked_numbers = []

        for claim in claims:
            # Check for evidence
            if not claim.evidence:
                naked_numbers.append(
                    {
                        "claim_id": claim.claim_id,
                        "value": claim.value,
                        "issue": "No evidence locators",
                    }
                )
                continue

            # Check all evidence has content hashes
            for i, evidence in enumerate(claim.evidence):
                if not evidence.content_hash:
                    naked_numbers.append(
                        {
                            "claim_id": claim.claim_id,
                            "value": claim.value,
                            "evidence_index": i,
                            "issue": "Evidence missing content hash",
                        }
                    )

                if not evidence.uri:
                    naked_numbers.append(
                        {
                            "claim_id": claim.claim_id,
                            "value": claim.value,
                            "evidence_index": i,
                            "issue": "Evidence missing URI",
                        }
                    )

            # Check provenance exists
            if not claim.provenance:
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Missing provenance metadata (warning)",
                        "severity": "warn",
                    }
                )

        # Naked numbers are blocking
        if naked_numbers:
            issues.extend(naked_numbers)

        passed = len(naked_numbers) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=self.severity if not passed else Severity.INFO,
            message=(
                "No naked numbers detected"
                if passed
                else f"Found {len(naked_numbers)} naked numbers without proper evidence"
            ),
            details={
                "naked_numbers": naked_numbers,
                "warnings": [i for i in issues if i.get("severity") == "warn"],
            },
        )
