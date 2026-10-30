"""
Schema validation for claims and scope locks.
"""

from typing import Any

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult, is_canonical_sha256_content_hash
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class SchemaValidator(Validator):
    """Validates that all claims conform to required schema."""

    name = "schema"
    description = "Validates claim schema compliance"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate claim schemas."""
        issues: list[dict[str, Any]] = []

        for claim in claims:
            # Check required fields
            if not claim.claim_id:
                issues.append(
                    {
                        "claim_id": claim.claim_id or "unknown",
                        "issue": "Missing claim_id",
                    }
                )

            if claim.value is None:
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Missing value",
                    }
                )

            # Check evidence
            if not claim.evidence:
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "No evidence provided",
                    }
                )
            else:
                for i, evidence in enumerate(claim.evidence):
                    # Check content hash format
                    if not is_canonical_sha256_content_hash(evidence.content_hash):
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "evidence_index": i,
                                "issue": "Invalid content hash format: expected sha256: and 64 lowercase hex characters",
                            }
                        )

                    # Check URI
                    if not evidence.uri:
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "evidence_index": i,
                                "issue": "Missing evidence URI",
                            }
                        )

            # Check numeric constraints
            if (claim.lower_bound is not None and claim.upper_bound is not None) and (
                claim.lower_bound > claim.upper_bound
            ):
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Lower bound exceeds upper bound",
                    }
                )

            if (claim.confidence_level is not None) and (not 0 <= claim.confidence_level <= 1):
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Confidence level must be between 0 and 1",
                    }
                )

        # Validate scope lock
        if not scope_lock.scope_id:
            issues.append(
                {
                    "scope": "scope_lock",
                    "issue": "Missing scope_id",
                }
            )

        if not scope_lock.policy_id:
            issues.append(
                {
                    "scope": "scope_lock",
                    "issue": "Missing policy_id",
                }
            )

        passed = len(issues) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=self.severity if not passed else Severity.INFO,
            message="Schema validation passed"
            if passed
            else f"Schema validation failed: {len(issues)} issues",
            details={"issues": issues} if issues else {},
        )
