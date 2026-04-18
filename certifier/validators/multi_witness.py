"""
Multi-witness validator - requires multiple independent verifications.
"""

from typing import Any
from collections import defaultdict

from ..constants import Severity, CertificationProfile
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class MultiWitnessValidator(Validator):
    """
    Validates that claims meet multi-witness requirements.

    For critical fields, multiple independent witnesses must agree:
    - SILVER: 2-witness rule
    - GOLD: 3-witness rule

    Witnesses are tracked via claim metadata 'witnesses' field.
    """

    name = "multi_witness"
    description = "Validates multi-witness requirements"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate multi-witness requirements."""
        issues = []

        # Determine required witness count
        require_multi = context.get("require_multi_witness", False)
        witness_count = context.get("witness_count", 1)

        if scope_lock.profile == CertificationProfile.GOLD:
            require_multi = True
            witness_count = max(witness_count, 3)
        elif scope_lock.profile == CertificationProfile.SILVER:
            require_multi = True
            witness_count = max(witness_count, 2)

        if not require_multi:
            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.INFO,
                message="Multi-witness check skipped (BRONZE profile or not required)",
                details={"required_witnesses": 1},
            )

        for claim in claims:
            witnesses = claim.metadata.get("witnesses", [])

            # Check witness count
            if len(witnesses) < witness_count:
                issues.append({
                    "claim_id": claim.claim_id,
                    "issue": f"Insufficient witnesses: {len(witnesses)} < {witness_count}",
                    "witnesses_found": len(witnesses),
                    "witnesses_required": witness_count,
                })
                continue

            # Check witness agreement
            witness_values = defaultdict(list)
            for witness in witnesses:
                if isinstance(witness, dict):
                    w_id = witness.get("witness_id", "unknown")
                    w_value = witness.get("value")
                    w_hash = witness.get("content_hash")
                    witness_values["value"].append((w_id, w_value))
                    if w_hash:
                        witness_values["hash"].append((w_id, w_hash))

            # Check value agreement
            if witness_values["value"]:
                values = [v for _, v in witness_values["value"] if v is not None]
                unique_values = set(values)
                if len(unique_values) > 1:
                    issues.append({
                        "claim_id": claim.claim_id,
                        "issue": "Witnesses disagree on value",
                        "witness_values": witness_values["value"],
                    })

            # Check hash agreement
            if witness_values["hash"]:
                hashes = [h for _, h in witness_values["hash"]]
                unique_hashes = set(hashes)
                if len(unique_hashes) > 1:
                    issues.append({
                        "claim_id": claim.claim_id,
                        "issue": "Witnesses disagree on content hash",
                        "witness_hashes": witness_values["hash"],
                    })

        passed = len(issues) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=self.severity if not passed else Severity.INFO,
            message=(
                f"Multi-witness validation passed ({witness_count}-witness rule)"
                if passed
                else f"Multi-witness validation failed: {len(issues)} issues"
            ),
            details={
                "issues": issues,
                "required_witnesses": witness_count,
                "profile": scope_lock.profile.value,
            },
        )
