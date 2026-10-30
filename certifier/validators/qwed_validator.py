"""
QWED (Quantitative Workflow with External Determinism) Validator.

Integrates QWED deterministic verification into the TruthCert validation pipeline.
This validator runs mathematical consistency checks on numeric claims.

Checks performed:
1. CI/SE consistency (CI ≈ value ± z*SE)
2. Ratio measure constraints (RR, OR, HR > 0)
3. Correlation bounds (-1 ≤ r ≤ 1)
4. I² bounds (0 ≤ I² ≤ 100)
5. Pooled effect verification (when study data available)
6. Variance/SE consistency (var = SE²)
"""

from typing import Any

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from ..qwed import QWEDVerifier, VerificationStatus, get_verification_summary
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class QWEDValidator(Validator):
    """
    Validates claims using QWED deterministic verification.

    This validator treats the LLM as an untrusted source and verifies
    mathematical consistency of all numeric claims using deterministic
    checks that don't require external data access.

    Verification failures indicate either:
    1. Extraction errors (wrong value extracted)
    2. Calculation errors (pooled effect miscalculated)
    3. Inconsistent metadata (SE doesn't match CI)
    """

    name = "qwed"
    description = "QWED deterministic mathematical verification"
    default_severity = Severity.WARN

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        super().__init__(config)
        params = config.params if config else {}

        # Tolerance for floating-point comparisons
        self.tolerance = params.get("tolerance", 0.01)

        # Whether to block on verification failures (stricter mode)
        self.strict_mode = params.get("strict_mode", False)

        # Create verifier with configured tolerance
        self.verifier = QWEDVerifier(tolerance=self.tolerance)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Run QWED verification on all claims."""
        all_results = []
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        for claim in claims:
            claim_results = self.verifier.verify_claim(claim)
            all_results.extend(claim_results)

            # Categorize results
            for result in claim_results:
                if result.status == VerificationStatus.FAILED:
                    if self.strict_mode:
                        errors.append(
                            {
                                "claim_id": result.claim_id,
                                "check_type": result.check_type,
                                "issue": result.message,
                                "expected": result.expected,
                                "actual": result.actual,
                                "tolerance": result.tolerance,
                            }
                        )
                    else:
                        warnings.append(
                            {
                                "claim_id": result.claim_id,
                                "check_type": result.check_type,
                                "issue": result.message,
                                "expected": result.expected,
                                "actual": result.actual,
                            }
                        )
                elif result.status == VerificationStatus.ERROR:
                    warnings.append(
                        {
                            "claim_id": result.claim_id,
                            "check_type": result.check_type,
                            "issue": f"Verification error: {result.message}",
                        }
                    )

        # Get summary statistics
        summary = get_verification_summary(all_results)

        passed = len(errors) == 0

        # Determine severity
        if not passed:
            severity = Severity.BLOCK
        elif warnings:
            severity = Severity.WARN
        else:
            severity = Severity.INFO

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=severity,
            message=(
                f"QWED: {summary['verified']}/{summary['total_checks']} checks passed "
                f"({summary['pass_rate'] * 100:.0f}%)"
                if summary["total_checks"] > 0
                else "QWED: No verifiable claims"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "summary": summary,
                "tolerance": self.tolerance,
                "strict_mode": self.strict_mode,
            },
        )


@ValidatorRegistry.register
class MathConsistencyValidator(Validator):
    """
    Lightweight math consistency validator.

    A simpler version of QWED that only checks basic mathematical
    constraints without full verification. Suitable for quick validation.
    """

    name = "math_consistency"
    description = "Basic mathematical consistency checks"
    default_severity = Severity.WARN

    # Tolerance for floating-point comparisons
    EPSILON = 1e-10

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Run basic math consistency checks."""
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        checked_count = 0

        for claim in claims:
            checked_count += 1

            # Check 1: CI bounds ordering
            if claim.lower_bound is not None and claim.upper_bound is not None:
                if claim.lower_bound > claim.upper_bound:
                    errors.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"CI bounds inverted: [{claim.lower_bound}, {claim.upper_bound}]",
                        }
                    )
                elif claim.value < claim.lower_bound or claim.value > claim.upper_bound:
                    warnings.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": f"Point estimate ({claim.value}) outside CI",
                        }
                    )

            # Check 2: Non-negative measures
            if (claim.claim_type.value in ("risk_ratio", "odds_ratio", "hazard_ratio")) and (
                claim.value <= 0
            ):
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Ratio measure must be positive, got {claim.value}",
                    }
                )

            # Check 3: Bounded measures
            if claim.claim_type.value == "correlation" and not -1 <= claim.value <= 1:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Correlation must be in [-1, 1], got {claim.value}",
                    }
                )

            if (claim.claim_type.value in ("sensitivity", "specificity", "ppv", "npv")) and (
                not 0 <= claim.value <= 1
            ):
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"{claim.claim_type.value} must be in [0, 1], got {claim.value}",
                    }
                )

            if claim.claim_type.value == "i_squared" and not 0 <= claim.value <= 100:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"I² must be in [0, 100], got {claim.value}",
                    }
                )

            # Check 4: Sample size positive integer
            if claim.sample_size is not None and claim.sample_size < 1:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Sample size must be positive, got {claim.sample_size}",
                    }
                )

            # Check 5: SE non-negative
            if claim.standard_error is not None and claim.standard_error < 0:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Standard error cannot be negative, got {claim.standard_error}",
                    }
                )

            # Check 6: Variance non-negative
            if claim.variance is not None and claim.variance < 0:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"Variance cannot be negative, got {claim.variance}",
                    }
                )

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK
            if not passed
            else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Math consistency: {checked_count} claims checked"
                if passed
                else f"Math consistency: {len(errors)} errors found"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "checked_count": checked_count,
            },
        )
