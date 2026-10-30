"""
Determinism validator - ensures reproducible computations.
"""

import hashlib
import json
from typing import Any

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class DeterminismValidator(Validator):
    """
    Validates that claim computations are deterministic and reproducible.

    For SILVER/GOLD profiles, claims that involve computed values must:
    1. Include computation metadata
    2. Be reproducible with the same inputs
    3. Use pinned dependencies (when applicable)
    """

    name = "determinism"
    description = "Validates computation reproducibility"
    default_severity = Severity.BLOCK

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate determinism requirements."""
        issues: list[dict[str, Any]] = []

        # Check if determinism is required for this profile
        require_determinism = context.get("require_determinism", False)
        if scope_lock.profile in [CertificationProfile.SILVER, CertificationProfile.GOLD]:
            require_determinism = True

        if not require_determinism:
            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.INFO,
                message="Determinism check skipped (BRONZE profile)",
                details={"profile": scope_lock.profile.value},
            )

        for claim in claims:
            # Check for computed claims
            is_computed = any(e.source_type.value == "computed" for e in claim.evidence)

            if is_computed:
                # Must have computation metadata
                computation = claim.provenance.get("computation", {})
                if not computation:
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": "Computed claim missing computation metadata",
                        }
                    )
                    continue

                # Check for reproducibility fields
                required_fields = ["algorithm", "inputs_hash", "inputs"]
                for field in required_fields:
                    if (
                        field not in computation
                        or computation[field] is None
                        or (field != "inputs" and not computation[field])
                    ):
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "issue": f"Computation metadata missing required field: {field}",
                            }
                        )

                # Verify inputs hash if provided
                inputs = computation.get("inputs")
                expected_hash = computation.get("inputs_hash")
                if inputs is not None and expected_hash:
                    computed_hash = self._compute_inputs_hash(inputs)
                    if computed_hash != expected_hash:
                        issues.append(
                            {
                                "claim_id": claim.claim_id,
                                "issue": "Computation inputs hash mismatch",
                                "expected": expected_hash,
                                "computed": computed_hash,
                            }
                        )

                # Check for seed if algorithm involves randomness
                algorithm = computation.get("algorithm", "")
                if (
                    any(
                        kw in algorithm.lower() for kw in ["random", "monte", "bootstrap", "sample"]
                    )
                    and computation.get("seed") is None
                ):
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": "Stochastic algorithm missing seed for reproducibility",
                            "algorithm": algorithm,
                        }
                    )

        passed = len(issues) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=self.severity if not passed else Severity.INFO,
            message=(
                "Determinism validation passed"
                if passed
                else f"Determinism validation failed: {len(issues)} issues"
            ),
            details={"issues": issues},
        )

    def _compute_inputs_hash(self, inputs: Any) -> str:
        """Compute deterministic hash of computation inputs."""
        canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
