"""
Scope lock validation - ensures request integrity.
"""

from typing import Any

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class ScopeLockValidator(Validator):
    """Validates scope lock hash matches request."""

    name = "scope_lock"
    description = "Validates scope lock integrity"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate scope lock."""
        issues = []

        # Check if expected hash is provided in context
        expected_hash = context.get("expected_scope_lock_hash")
        if expected_hash:
            computed_hash = scope_lock.compute_hash()
            if computed_hash != expected_hash:
                issues.append(
                    {
                        "issue": "Scope lock hash mismatch",
                        "expected": expected_hash,
                        "computed": computed_hash,
                    }
                )

        # Validate required validators are in scope
        policy = context.get("policy")
        if policy:
            required_validators = set(scope_lock.required_validators)
            policy_validators = {v.name for v in policy.validators if v.enabled}

            missing = required_validators - policy_validators
            if missing:
                issues.append(
                    {
                        "issue": "Required validators not in policy",
                        "missing": list(missing),
                    }
                )

        # Validate allowed sources
        for claim in claims:
            for evidence in claim.evidence:
                source_type = evidence.source_type.value
                if scope_lock.allowed_sources and source_type not in scope_lock.allowed_sources:
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Evidence source type '{source_type}' not in allowed sources",
                            "allowed": scope_lock.allowed_sources,
                        }
                    )

        passed = len(issues) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=self.severity if not passed else Severity.INFO,
            message="Scope lock validation passed"
            if passed
            else f"Scope lock validation failed: {len(issues)} issues",
            details={"issues": issues} if issues else {},
        )
