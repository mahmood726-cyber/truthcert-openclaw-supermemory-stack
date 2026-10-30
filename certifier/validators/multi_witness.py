"""Validate declarative multi-witness metadata without counting duplicate or malformed votes.

Witness IDs and values are claims supplied by the caller, not external identity
attestation or proof that any independent human actually checked the source.
"""

from math import isfinite
from typing import Any

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class MultiWitnessValidator(Validator):
    """Fail closed on missing, duplicate, malformed or disagreeing witness records."""

    name = "multi_witness"
    description = "Validates multi-witness requirements"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Check the required count of distinct, agreeing witness declarations."""
        require_multi = context.get("require_multi_witness", False)
        witness_count = context.get("witness_count", 1)

        if scope_lock.profile == CertificationProfile.GOLD:
            require_multi = True
            minimum = 3
        elif scope_lock.profile == CertificationProfile.SILVER:
            require_multi = True
            minimum = 2
        else:
            minimum = 1

        if not require_multi:
            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.INFO,
                message="Multi-witness check skipped (BRONZE profile or not required)",
                details={"required_witnesses": 1},
            )

        if (
            isinstance(witness_count, bool)
            or not isinstance(witness_count, int)
            or witness_count < 1
        ):
            return ValidatorResult(
                validator_name=self.name,
                passed=False,
                severity=self.severity,
                message="Invalid required witness count",
                details={"required_witnesses": witness_count},
            )
        witness_count = max(witness_count, minimum)
        issues: list[dict[str, Any]] = []

        for claim in claims:
            witnesses = claim.metadata.get("witnesses", [])
            if not isinstance(witnesses, list):
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Witness records must be a list",
                    }
                )
                continue

            seen_ids: set[str] = set()
            hashes: list[str] = []
            for index, witness in enumerate(witnesses):
                if not isinstance(witness, dict):
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Witness {index} must be an object",
                        }
                    )
                    continue

                raw_id = witness.get("witness_id")
                if not isinstance(raw_id, str) or not raw_id.strip():
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Witness {index} missing nonblank identity",
                        }
                    )
                else:
                    witness_id = raw_id.strip()
                    if witness_id in seen_ids:
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "issue": f"Duplicate witness identity: {witness_id}",
                            }
                        )
                    else:
                        seen_ids.add(witness_id)

                value = witness.get("value")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isfinite(value)
                ):
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Witness {index} has no finite numeric value",
                        }
                    )
                elif value != claim.value:
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Witness {index} disagrees with claim value",
                        }
                    )

                if "content_hash" in witness:
                    content_hash = witness["content_hash"]
                    if not isinstance(content_hash, str) or not content_hash.strip():
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "issue": f"Witness {index} has an invalid content hash",
                            }
                        )
                    else:
                        hashes.append(content_hash)

            if len(seen_ids) < witness_count:
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Insufficient distinct witnesses: {len(seen_ids)} < {witness_count}",
                        "witnesses_found": len(seen_ids),
                        "witnesses_required": witness_count,
                    }
                )

            if hashes:
                if len(hashes) != len(witnesses):
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": "Witness content hashes must all be present if any is supplied",
                        }
                    )
                if len(set(hashes)) > 1:
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": "Witnesses disagree on content hash",
                        }
                    )

        passed = not issues
        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.INFO if passed else self.severity,
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
