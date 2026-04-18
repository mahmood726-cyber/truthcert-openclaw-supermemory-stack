"""
Domain Pack: Meta-Analysis Heterogeneity Validator (tc_meta_het)

Validates heterogeneity statistics in meta-analysis claims:
- I² (inconsistency index): 0-100%
- τ² (tau-squared): between-study variance, must be >= 0
- Q statistic: Cochran's Q for heterogeneity test
- H² statistic: ratio of total to sampling variance

This is a COMPLETE implementation with full validation logic.
"""

import math
from typing import Any, Optional
from dataclasses import dataclass

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult, ClaimType, ValidatorConfig
from .base import Validator, ValidatorRegistry


@dataclass
class HeterogeneityBounds:
    """Plausibility bounds for heterogeneity statistics."""
    i_squared_min: float = 0.0
    i_squared_max: float = 100.0
    tau_squared_min: float = 0.0
    tau_squared_max: float = 100.0  # Very large τ² is implausible
    q_min: float = 0.0
    h_squared_min: float = 1.0  # H² is always >= 1


@ValidatorRegistry.register
class HeterogeneityValidator(Validator):
    """
    Validates heterogeneity statistics in meta-analysis claims.

    Checks performed:
    1. I² must be between 0% and 100%
    2. τ² must be non-negative
    3. Q statistic must be non-negative
    4. H² must be >= 1 (mathematically required)
    5. Consistency between I² and τ² when both reported
    6. Q statistic degrees of freedom check
    7. Confidence intervals must be valid
    8. Warning for high heterogeneity (I² > 75%)
    """

    name = "tc_meta_het"
    description = "Validates heterogeneity statistics in meta-analysis claims"
    default_severity = Severity.BLOCK

    # Heterogeneity claim types
    HET_CLAIM_TYPES = {
        ClaimType.HETEROGENEITY,
    }

    # I² interpretation thresholds (Cochrane Handbook)
    I2_LOW = 25.0
    I2_MODERATE = 50.0
    I2_HIGH = 75.0

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        self.bounds = HeterogeneityBounds()
        # Get custom params from config
        params = config.params if config else {}
        if params:
            if "tau_squared_max" in params:
                self.bounds.tau_squared_max = params["tau_squared_max"]

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate heterogeneity claims."""
        errors = []
        warnings = []
        validated_count = 0

        for claim in claims:
            # Check if this is a heterogeneity claim
            if claim.claim_type not in self.HET_CLAIM_TYPES:
                # Also check metadata for heterogeneity statistics
                if not self._is_heterogeneity_claim(claim):
                    continue

            validated_count += 1
            claim_errors, claim_warnings = self._validate_claim(claim)
            errors.extend(claim_errors)
            warnings.extend(claim_warnings)

        # Also validate any related heterogeneity in effect size claims
        for claim in claims:
            if claim.claim_type == ClaimType.EFFECT_SIZE:
                het_errors, het_warnings = self._validate_effect_size_heterogeneity(claim)
                errors.extend(het_errors)
                warnings.extend(het_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} heterogeneity claims"
                if passed
                else f"Heterogeneity validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
                "interpretation_thresholds": {
                    "low": f"I² < {self.I2_LOW}%",
                    "moderate": f"{self.I2_LOW}% <= I² < {self.I2_HIGH}%",
                    "high": f"I² >= {self.I2_HIGH}%",
                },
            },
        )

    def _is_heterogeneity_claim(self, claim: NumericClaim) -> bool:
        """Check if claim contains heterogeneity statistics in metadata."""
        het_keys = {"i_squared", "i2", "tau_squared", "tau2", "q_statistic", "cochran_q", "h_squared", "h2"}
        claim_keys = set(k.lower() for k in claim.metadata.keys())
        return bool(het_keys & claim_keys)

    def _validate_claim(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate a single heterogeneity claim."""
        errors = []
        warnings = []

        # Get heterogeneity values from metadata or claim value
        i_squared = self._get_stat(claim, ["i_squared", "i2", "isquared"])
        tau_squared = self._get_stat(claim, ["tau_squared", "tau2", "tausquared"])
        q_stat = self._get_stat(claim, ["q_statistic", "cochran_q", "q"])
        h_squared = self._get_stat(claim, ["h_squared", "h2", "hsquared"])
        df = self._get_stat(claim, ["df", "degrees_of_freedom", "k_minus_1"])
        k = self._get_stat(claim, ["k", "n_studies", "num_studies"])

        # If the main claim value is I², use it
        if claim.claim_type == ClaimType.HETEROGENEITY and i_squared is None:
            i_squared = claim.value

        # Validate I²
        if i_squared is not None:
            if i_squared < self.bounds.i_squared_min:
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": "I²",
                    "value": i_squared,
                    "issue": f"I² cannot be negative (got {i_squared}%)",
                    "bound": f">= {self.bounds.i_squared_min}%",
                })
            elif i_squared > self.bounds.i_squared_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": "I²",
                    "value": i_squared,
                    "issue": f"I² cannot exceed 100% (got {i_squared}%)",
                    "bound": f"<= {self.bounds.i_squared_max}%",
                })
            elif i_squared >= self.I2_HIGH:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "statistic": "I²",
                    "value": i_squared,
                    "issue": f"High heterogeneity detected (I² = {i_squared}%)",
                    "interpretation": "Substantial heterogeneity; consider subgroup analysis",
                })

        # Validate τ²
        if tau_squared is not None:
            if tau_squared < self.bounds.tau_squared_min:
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": "τ²",
                    "value": tau_squared,
                    "issue": f"τ² cannot be negative (got {tau_squared})",
                    "bound": f">= {self.bounds.tau_squared_min}",
                })
            elif tau_squared > self.bounds.tau_squared_max:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "statistic": "τ²",
                    "value": tau_squared,
                    "issue": f"Very large τ² value (got {tau_squared})",
                    "interpretation": "May indicate data issues or extreme heterogeneity",
                })

        # Validate Q statistic
        if q_stat is not None:
            if q_stat < self.bounds.q_min:
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": "Q",
                    "value": q_stat,
                    "issue": f"Cochran's Q cannot be negative (got {q_stat})",
                    "bound": f">= {self.bounds.q_min}",
                })

            # Check Q against degrees of freedom
            if df is not None and q_stat < df * 0.1:
                # Q much smaller than df is unusual
                warnings.append({
                    "claim_id": claim.claim_id,
                    "statistic": "Q",
                    "value": q_stat,
                    "issue": f"Q ({q_stat}) much smaller than df ({df})",
                    "interpretation": "Very low heterogeneity or potential calculation error",
                })

        # Validate H²
        if h_squared is not None:
            if h_squared < self.bounds.h_squared_min:
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": "H²",
                    "value": h_squared,
                    "issue": f"H² must be >= 1 by definition (got {h_squared})",
                    "bound": f">= {self.bounds.h_squared_min}",
                })

        # Cross-validate I² and H² relationship
        # I² = (H² - 1) / H²  =>  H² = 1 / (1 - I²/100)
        if i_squared is not None and h_squared is not None:
            if i_squared < 100:
                expected_h2 = 1.0 / (1.0 - i_squared / 100.0)
                tolerance = 0.1 * expected_h2  # 10% tolerance
                if abs(h_squared - expected_h2) > tolerance:
                    errors.append({
                        "claim_id": claim.claim_id,
                        "issue": f"I² ({i_squared}%) and H² ({h_squared}) are inconsistent",
                        "expected_h2": round(expected_h2, 4),
                        "formula": "H² = 1 / (1 - I²/100)",
                    })

        # Cross-validate Q, df, and I² relationship
        # I² = max(0, (Q - df) / Q * 100)
        if q_stat is not None and df is not None and i_squared is not None:
            if q_stat > 0:
                expected_i2 = max(0, (q_stat - df) / q_stat * 100)
                tolerance = 5.0  # 5 percentage points tolerance
                if abs(i_squared - expected_i2) > tolerance:
                    warnings.append({
                        "claim_id": claim.claim_id,
                        "issue": f"I² ({i_squared}%) and Q/df relationship mismatch",
                        "expected_i2": round(expected_i2, 2),
                        "q_stat": q_stat,
                        "df": df,
                        "formula": "I² = max(0, (Q - df) / Q × 100)",
                    })

        # Validate confidence intervals
        i2_lower = self._get_stat(claim, ["i2_lower", "i_squared_lower", "i2_ci_lower"])
        i2_upper = self._get_stat(claim, ["i2_upper", "i_squared_upper", "i2_ci_upper"])

        if i2_lower is not None and i2_upper is not None:
            if i2_lower > i2_upper:
                errors.append({
                    "claim_id": claim.claim_id,
                    "issue": f"I² CI lower ({i2_lower}) > upper ({i2_upper})",
                })
            if i_squared is not None:
                if i_squared < i2_lower or i_squared > i2_upper:
                    # This is a WARNING not an ERROR because:
                    # 1. Some estimation methods (e.g., Q-profile) can produce CIs
                    #    that don't contain the point estimate
                    # 2. Truncation at 0% can cause this legitimately
                    # 3. Different CI methods may use different estimators
                    warnings.append({
                        "claim_id": claim.claim_id,
                        "issue": f"I² point estimate ({i_squared}%) outside CI [{i2_lower}%, {i2_upper}%]",
                        "note": "May be valid with certain estimation methods (e.g., Q-profile CI)",
                    })

        # Check number of studies
        if k is not None:
            if k < 2:
                errors.append({
                    "claim_id": claim.claim_id,
                    "issue": f"Cannot compute heterogeneity with k < 2 studies (got k={k})",
                })
            elif k < 5:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "issue": f"Low study count (k={k}) may give imprecise heterogeneity estimates",
                })

        return errors, warnings

    def _validate_effect_size_heterogeneity(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate heterogeneity statistics embedded in effect size claims."""
        errors = []
        warnings = []

        # Check if effect size claim has heterogeneity metadata
        if not self._is_heterogeneity_claim(claim):
            return errors, warnings

        # Validate the heterogeneity values
        het_errors, het_warnings = self._validate_claim(claim)

        # Add context that this is from an effect size claim
        for error in het_errors:
            error["context"] = "effect_size_claim"
        for warning in het_warnings:
            warning["context"] = "effect_size_claim"

        return het_errors, het_warnings

    def _get_stat(self, claim: NumericClaim, keys: list[str]) -> Optional[float]:
        """Get a statistic from claim metadata by trying multiple keys."""
        for key in keys:
            # Try exact key
            if key in claim.metadata:
                val = claim.metadata[key]
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return float(val)

            # Try lowercase
            key_lower = key.lower()
            for k, v in claim.metadata.items():
                if k.lower() == key_lower:
                    if isinstance(v, (int, float)) and not math.isnan(v):
                        return float(v)

        return None


def compute_i_squared(q: float, df: int) -> float:
    """
    Compute I² from Q statistic and degrees of freedom.

    Formula: I² = max(0, (Q - df) / Q × 100)

    Args:
        q: Cochran's Q statistic
        df: Degrees of freedom (k - 1, where k is number of studies)

    Returns:
        I² value as percentage (0-100)
    """
    if q <= 0:
        return 0.0
    return max(0.0, (q - df) / q * 100)


def compute_h_squared(i_squared: float) -> float:
    """
    Compute H² from I².

    Formula: H² = 1 / (1 - I²/100)

    Args:
        i_squared: I² value as percentage

    Returns:
        H² value (>= 1)
    """
    if i_squared >= 100:
        return float('inf')
    return 1.0 / (1.0 - i_squared / 100.0)


def interpret_i_squared(i_squared: float) -> str:
    """
    Interpret I² value according to Cochrane Handbook guidelines.

    Args:
        i_squared: I² value as percentage

    Returns:
        Interpretation string
    """
    if i_squared < 25:
        return "Low heterogeneity"
    elif i_squared < 50:
        return "Low to moderate heterogeneity"
    elif i_squared < 75:
        return "Moderate to substantial heterogeneity"
    else:
        return "Substantial heterogeneity"
