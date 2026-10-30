"""
Effect Size Plausibility Validator

Validates that effect sizes fall within plausible bounds based on their type:
- Risk Ratio (RR): > 0, typically 0.1 - 10 for most interventions
- Odds Ratio (OR): > 0, typically 0.1 - 10 for most interventions
- Hazard Ratio (HR): > 0, typically 0.1 - 10 for survival analyses
- Mean Difference (MD): context-dependent, but extreme values flagged
- Standardized Mean Difference (SMD/Cohen's d): typically -3 to +3
- Number Needed to Treat (NNT): > 0 (absolute value for NNH)
- Proportion/Percentage: 0-100%
- P-values: 0-1

This prevents implausible values from being certified.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..constants import Severity
from ..models import ClaimType, NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from .base import Validator, ValidatorRegistry


class EffectSizeType(str, Enum):
    """Extended effect size types for plausibility checking."""

    RISK_RATIO = "risk_ratio"
    ODDS_RATIO = "odds_ratio"
    HAZARD_RATIO = "hazard_ratio"
    MEAN_DIFFERENCE = "mean_difference"
    STANDARDIZED_MEAN_DIFFERENCE = "standardized_mean_difference"
    NUMBER_NEEDED_TO_TREAT = "number_needed_to_treat"
    PROPORTION = "proportion"
    PERCENTAGE = "percentage"
    P_VALUE = "p_value"
    CORRELATION = "correlation"
    RELATIVE_RISK_REDUCTION = "relative_risk_reduction"
    ABSOLUTE_RISK_REDUCTION = "absolute_risk_reduction"


@dataclass
class EffectSizeBounds:
    """Plausibility bounds for effect sizes by type."""

    # Ratio measures (RR, OR, HR)
    ratio_hard_min: float = 0.0  # Must be positive
    ratio_hard_max: float = float("inf")  # No hard max
    ratio_plausible_min: float = 0.01  # Very extreme
    ratio_plausible_max: float = 100.0  # Very extreme
    ratio_typical_min: float = 0.1  # Typical range
    ratio_typical_max: float = 10.0  # Typical range

    # SMD/Cohen's d
    smd_hard_min: float = -10.0  # Mathematically possible but extreme
    smd_hard_max: float = 10.0
    smd_plausible_min: float = -5.0
    smd_plausible_max: float = 5.0
    smd_typical_min: float = -3.0  # Cohen's large = 0.8
    smd_typical_max: float = 3.0

    # NNT
    nnt_hard_min: float = 1.0  # Minimum possible NNT
    nnt_hard_max: float = float("inf")
    nnt_plausible_max: float = 10000.0  # Very large NNT is implausible

    # Proportion
    proportion_min: float = 0.0
    proportion_max: float = 1.0

    # Percentage
    percentage_min: float = 0.0
    percentage_max: float = 100.0

    # P-value
    p_value_min: float = 0.0
    p_value_max: float = 1.0

    # Correlation
    correlation_min: float = -1.0
    correlation_max: float = 1.0


# Type aliases for claim detection
TYPE_ALIASES = {
    # Risk Ratio
    "rr": EffectSizeType.RISK_RATIO,
    "risk_ratio": EffectSizeType.RISK_RATIO,
    "relative_risk": EffectSizeType.RISK_RATIO,
    "rate_ratio": EffectSizeType.RISK_RATIO,
    # Odds Ratio
    "or": EffectSizeType.ODDS_RATIO,
    "odds_ratio": EffectSizeType.ODDS_RATIO,
    # Hazard Ratio
    "hr": EffectSizeType.HAZARD_RATIO,
    "hazard_ratio": EffectSizeType.HAZARD_RATIO,
    # Mean Difference
    "md": EffectSizeType.MEAN_DIFFERENCE,
    "mean_difference": EffectSizeType.MEAN_DIFFERENCE,
    "wmd": EffectSizeType.MEAN_DIFFERENCE,  # Weighted MD
    # Standardized Mean Difference
    "smd": EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE,
    "standardized_mean_difference": EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE,
    "cohens_d": EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE,
    "hedges_g": EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE,
    "glass_delta": EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE,
    # NNT
    "nnt": EffectSizeType.NUMBER_NEEDED_TO_TREAT,
    "number_needed_to_treat": EffectSizeType.NUMBER_NEEDED_TO_TREAT,
    "nnh": EffectSizeType.NUMBER_NEEDED_TO_TREAT,  # Number needed to harm
    # Proportion
    "proportion": EffectSizeType.PROPORTION,
    "prevalence": EffectSizeType.PROPORTION,
    "incidence": EffectSizeType.PROPORTION,
    "probability": EffectSizeType.PROPORTION,
    # Percentage
    "percentage": EffectSizeType.PERCENTAGE,
    "percent": EffectSizeType.PERCENTAGE,
    "rate": EffectSizeType.PERCENTAGE,
    # P-value
    "p_value": EffectSizeType.P_VALUE,
    "pvalue": EffectSizeType.P_VALUE,
    "p": EffectSizeType.P_VALUE,
    # Correlation
    "correlation": EffectSizeType.CORRELATION,
    "r": EffectSizeType.CORRELATION,
    "pearson_r": EffectSizeType.CORRELATION,
    "spearman_rho": EffectSizeType.CORRELATION,
    # RRR/ARR
    "rrr": EffectSizeType.RELATIVE_RISK_REDUCTION,
    "relative_risk_reduction": EffectSizeType.RELATIVE_RISK_REDUCTION,
    "arr": EffectSizeType.ABSOLUTE_RISK_REDUCTION,
    "absolute_risk_reduction": EffectSizeType.ABSOLUTE_RISK_REDUCTION,
}


@ValidatorRegistry.register
class EffectSizePlausibilityValidator(Validator):
    """
    Validates effect sizes against plausible bounds.

    Checks performed:
    1. Hard bounds (mathematically impossible values)
    2. Plausible bounds (extreme but technically possible)
    3. Typical bounds (warning for unusual values)
    4. Confidence interval consistency
    5. SE/variance positivity
    """

    name = "effect_size_plausibility"
    description = "Validates effect sizes against plausible bounds"
    default_severity = Severity.BLOCK

    def __init__(self, config: ValidatorConfig | None = None):
        super().__init__(config)
        self.bounds = EffectSizeBounds()
        # Get custom params from config
        params = config.params if config else {}
        if params:
            # Allow customization of bounds
            for key, value in params.items():
                if hasattr(self.bounds, key):
                    setattr(self.bounds, key, value)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate effect size plausibility."""
        errors = []
        warnings = []
        validated_count = 0

        for claim in claims:
            # Determine effect size type
            es_type = self._determine_effect_size_type(claim)
            if es_type is None:
                continue

            validated_count += 1
            claim_errors, claim_warnings = self._validate_claim(claim, es_type)
            errors.extend(claim_errors)
            warnings.extend(claim_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK
            if not passed
            else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} effect size claims"
                if passed
                else f"Effect size validation failed: {len(errors)} implausible values"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
            },
        )

    def _determine_effect_size_type(self, claim: NumericClaim) -> EffectSizeType | None:
        """Determine the effect size type from claim."""
        # Check metadata for explicit type
        es_type_raw = claim.metadata.get("effect_size_type", "")
        if not es_type_raw:
            es_type_raw = claim.metadata.get("statistic_type", "")
        if not es_type_raw:
            es_type_raw = claim.metadata.get("measure", "")

        # Check claim type
        if claim.claim_type == ClaimType.P_VALUE:
            return EffectSizeType.P_VALUE
        elif claim.claim_type == ClaimType.PROPORTION:
            return EffectSizeType.PROPORTION

        # Check unit field
        unit = (claim.unit or "").lower()
        if unit in TYPE_ALIASES:
            return TYPE_ALIASES[unit]

        # Check type string
        type_str = str(es_type_raw).lower().replace(" ", "_").replace("-", "_")
        if type_str in TYPE_ALIASES:
            return TYPE_ALIASES[type_str]

        # Check claim_id for hints
        claim_id_lower = claim.claim_id.lower()
        for alias, es_type in TYPE_ALIASES.items():
            if alias in claim_id_lower:
                return es_type

        # Default to effect size type for general effect size claims
        if claim.claim_type == ClaimType.EFFECT_SIZE:
            # Try to infer from value range
            if claim.value > 0 and claim.lower_bound is not None and claim.lower_bound > 0:
                # Positive-only suggests ratio measure
                return EffectSizeType.ODDS_RATIO
            elif -5 < claim.value < 5:
                # Could be SMD
                return EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE

        return None

    def _validate_claim(
        self,
        claim: NumericClaim,
        es_type: EffectSizeType,
    ) -> tuple[list[dict], list[dict]]:
        """Validate a single effect size claim."""
        errors = []
        warnings = []
        value = claim.value

        # Check for NaN or Inf
        if math.isnan(value) or math.isinf(value):
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": es_type.value,
                    "value": str(value),
                    "issue": "Value is NaN or Infinite",
                }
            )
            return errors, warnings

        # Validate based on type
        if es_type in (
            EffectSizeType.RISK_RATIO,
            EffectSizeType.ODDS_RATIO,
            EffectSizeType.HAZARD_RATIO,
        ):
            self._validate_ratio(claim, es_type, errors, warnings)

        elif es_type == EffectSizeType.STANDARDIZED_MEAN_DIFFERENCE:
            self._validate_smd(claim, errors, warnings)

        elif es_type == EffectSizeType.NUMBER_NEEDED_TO_TREAT:
            self._validate_nnt(claim, errors, warnings)

        elif es_type == EffectSizeType.PROPORTION:
            self._validate_proportion(claim, errors, warnings)

        elif es_type == EffectSizeType.PERCENTAGE:
            self._validate_percentage(claim, errors, warnings)

        elif es_type == EffectSizeType.P_VALUE:
            self._validate_p_value(claim, errors, warnings)

        elif es_type == EffectSizeType.CORRELATION:
            self._validate_correlation(claim, errors, warnings)

        elif es_type == EffectSizeType.MEAN_DIFFERENCE:
            self._validate_mean_difference(claim, errors, warnings)

        # Validate confidence intervals
        ci_errors, ci_warnings = self._validate_confidence_interval(claim, es_type)
        errors.extend(ci_errors)
        warnings.extend(ci_warnings)

        # Validate SE/variance
        se_errors, se_warnings = self._validate_se_variance(claim)
        errors.extend(se_errors)
        warnings.extend(se_warnings)

        return errors, warnings

    def _validate_ratio(
        self,
        claim: NumericClaim,
        es_type: EffectSizeType,
        errors: list[dict],
        warnings: list[dict],
    ):
        """Validate ratio measures (RR, OR, HR)."""
        value = claim.value
        b = self.bounds

        # Hard bound: must be positive
        if value <= b.ratio_hard_min:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": es_type.value,
                    "value": value,
                    "issue": f"{es_type.value} must be positive (got {value})",
                    "bound": f"> {b.ratio_hard_min}",
                }
            )
            return

        # Plausible bounds
        if value < b.ratio_plausible_min:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": es_type.value,
                    "value": value,
                    "issue": f"Extremely small {es_type.value} ({value})",
                    "interpretation": "Nearly complete prevention; verify data",
                }
            )
        elif value > b.ratio_plausible_max:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": es_type.value,
                    "value": value,
                    "issue": f"Extremely large {es_type.value} ({value})",
                    "interpretation": "100x risk increase; verify data",
                }
            )
        elif value < b.ratio_typical_min or value > b.ratio_typical_max:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": es_type.value,
                    "value": value,
                    "issue": f"Unusual {es_type.value} magnitude",
                    "typical_range": f"{b.ratio_typical_min} - {b.ratio_typical_max}",
                }
            )

    def _validate_smd(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate standardized mean difference."""
        value = claim.value
        b = self.bounds

        # Hard bounds
        if value < b.smd_hard_min or value > b.smd_hard_max:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "SMD",
                    "value": value,
                    "issue": f"SMD outside valid range [{b.smd_hard_min}, {b.smd_hard_max}]",
                }
            )
            return

        # Plausible bounds
        if value < b.smd_plausible_min or value > b.smd_plausible_max:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "SMD",
                    "value": value,
                    "issue": f"Extreme SMD value ({value})",
                    "interpretation": "Cohen's d > 0.8 is already 'large'",
                }
            )
        elif value < b.smd_typical_min or value > b.smd_typical_max:
            # Interpret magnitude
            abs_val = abs(value)
            if abs_val >= 2.0:
                size = "very large"
            elif abs_val >= 0.8:
                size = "large"
            elif abs_val >= 0.5:
                size = "medium"
            elif abs_val >= 0.2:
                size = "small"
            else:
                size = "negligible"

            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "SMD",
                    "value": value,
                    "magnitude": size,
                    "interpretation": f"Cohen's d = {value} indicates {size} effect",
                }
            )

    def _validate_nnt(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate number needed to treat."""
        value = abs(claim.value)  # NNH can be negative by convention
        b = self.bounds

        # Hard bound: must be >= 1
        if value < b.nnt_hard_min:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "NNT",
                    "value": value,
                    "issue": f"NNT must be >= 1 (got {value})",
                }
            )
            return

        # Plausible bound
        if value > b.nnt_plausible_max:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "NNT",
                    "value": value,
                    "issue": f"Very large NNT ({value})",
                    "interpretation": "Effect may not be clinically meaningful",
                }
            )

    def _validate_proportion(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate proportion (0-1)."""
        value = claim.value
        b = self.bounds

        if value < b.proportion_min or value > b.proportion_max:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "proportion",
                    "value": value,
                    "issue": f"Proportion must be between 0 and 1 (got {value})",
                }
            )

    def _validate_percentage(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate percentage (0-100)."""
        value = claim.value
        b = self.bounds

        if value < b.percentage_min or value > b.percentage_max:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "percentage",
                    "value": value,
                    "issue": f"Percentage must be between 0 and 100 (got {value})",
                }
            )

    def _validate_p_value(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate p-value (0-1)."""
        value = claim.value
        b = self.bounds

        if value < b.p_value_min or value > b.p_value_max:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "p-value",
                    "value": value,
                    "issue": f"P-value must be between 0 and 1 (got {value})",
                }
            )
            return

        # Warning for suspiciously precise p-values
        if 0 < value < 0.0001:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "p-value",
                    "value": value,
                    "issue": "Very small p-value; consider reporting as p < 0.001",
                }
            )

    def _validate_correlation(self, claim: NumericClaim, errors: list[dict], warnings: list[dict]):
        """Validate correlation coefficient (-1 to 1)."""
        value = claim.value
        b = self.bounds

        if value < b.correlation_min or value > b.correlation_max:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "correlation",
                    "value": value,
                    "issue": f"Correlation must be between -1 and 1 (got {value})",
                }
            )

    def _validate_mean_difference(
        self, claim: NumericClaim, errors: list[dict], warnings: list[dict]
    ):
        """Validate mean difference (context-dependent)."""
        # Mean differences are context-dependent, so we mainly check for NaN/Inf
        # and that SE/CI are provided for proper interpretation
        if claim.metadata.get("se") is None and claim.lower_bound is None:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "type": "mean_difference",
                    "value": claim.value,
                    "issue": "Mean difference reported without SE or CI",
                    "recommendation": "Include standard error or confidence interval",
                }
            )

    def _validate_confidence_interval(
        self,
        claim: NumericClaim,
        es_type: EffectSizeType,
    ) -> tuple[list[dict], list[dict]]:
        """Validate confidence interval consistency."""
        errors = []
        warnings = []

        lower = claim.lower_bound
        upper = claim.upper_bound
        value = claim.value

        if lower is None or upper is None:
            return errors, warnings

        # Lower must be <= upper
        if lower > upper:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": f"CI lower ({lower}) > upper ({upper})",
                }
            )
            return errors, warnings

        # Point estimate should be within CI
        if value < lower or value > upper:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": f"Point estimate ({value}) outside CI [{lower}, {upper}]",
                }
            )

        # For ratio measures, CI should not span 1 if claiming significance
        # CI crosses null
        if (
            es_type
            in (EffectSizeType.RISK_RATIO, EffectSizeType.ODDS_RATIO, EffectSizeType.HAZARD_RATIO)
            and lower < 1 < upper
        ) and (claim.metadata.get("significant", False)):
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": "Claimed significant but CI crosses null (1.0)",
                    "ci": f"[{lower}, {upper}]",
                }
            )

        return errors, warnings

    def _validate_se_variance(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate standard error and variance are positive."""
        errors = []
        warnings = []

        se = claim.metadata.get("se", claim.metadata.get("standard_error"))
        variance = claim.metadata.get("variance", claim.metadata.get("var"))

        if se is not None and se <= 0:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": f"Standard error must be positive (got {se})",
                }
            )

        if variance is not None and variance < 0:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": f"Variance cannot be negative (got {variance})",
                }
            )

        # Cross-validate SE and variance
        if se is not None and variance is not None:
            expected_var = se**2
            tolerance = 0.01 * expected_var if expected_var > 0 else 0.01
            if abs(variance - expected_var) > tolerance:
                warnings.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": f"SE ({se}) and variance ({variance}) inconsistent",
                        "expected_variance": round(expected_var, 6),
                    }
                )

        return errors, warnings
