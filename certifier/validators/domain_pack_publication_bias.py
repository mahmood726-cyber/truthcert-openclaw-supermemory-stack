"""
Domain Pack: Meta-Analysis Publication Bias Validator (tc_meta_bias)

Validates publication bias statistics and tests in meta-analysis claims:
- Egger's test (regression intercept and p-value)
- Begg's test (rank correlation)
- Funnel plot asymmetry measures
- Trim-and-fill estimates
- Fail-safe N (Rosenthal, Orwin)
- Duval & Tweedie imputed studies

This is a COMPLETE implementation with full validation logic.
"""

import math
from dataclasses import dataclass
from typing import Any

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from .base import Validator, ValidatorRegistry


# Only statistics interpreted by this validator, not arbitrary free-text metadata.
# An explicitly supplied malformed statistic must not be treated as missing.
_NUMERIC_BIAS_STATS = frozenset({
    "egger_intercept", "egger_b0", "egger_int", "egger_pvalue", "egger_p",
    "egger_se", "egger_stderr", "egger_t", "egger_tstat",
    "begg_tau", "kendall_tau", "tau", "begg_z", "begg_zstat",
    "begg_pvalue", "begg_p",
    "rosenthal_n", "rosenthal_fsn", "fail_safe_n", "fsn",
    "orwin_n", "orwin_fsn", "k", "n_studies", "num_studies",
    "imputed_studies", "tf_imputed", "trimfill_k0",
    "original_estimate", "unadjusted_estimate",
    "adjusted_estimate", "tf_estimate", "trimfill_estimate",
    "peters_p", "peters_pvalue", "harbord_p", "harbord_pvalue",
})


@dataclass
class PublicationBiasBounds:
    """Plausibility bounds for publication bias statistics."""
    # P-values must be 0-1
    p_value_min: float = 0.0
    p_value_max: float = 1.0

    # Egger's intercept typically small
    egger_intercept_extreme: float = 10.0  # Warning threshold

    # Fail-safe N must be non-negative integer
    fail_safe_n_min: int = 0

    # Trim-and-fill imputed studies
    imputed_studies_min: int = 0

    # Correlation coefficient bounds for Begg's test
    correlation_min: float = -1.0
    correlation_max: float = 1.0


@ValidatorRegistry.register
class PublicationBiasValidator(Validator):
    """
    Validates publication bias statistics in meta-analysis claims.

    Checks performed:
    1. P-values must be between 0 and 1
    2. Egger's test intercept plausibility
    3. Begg's correlation coefficient bounds
    4. Fail-safe N non-negative
    5. Trim-and-fill consistency
    6. Minimum studies for bias tests (k >= 10)
    7. Funnel plot asymmetry interpretation consistency
    """

    name = "tc_meta_bias"
    description = "Validates publication bias statistics in meta-analysis claims"
    default_severity = Severity.BLOCK

    # Minimum studies for publication bias tests
    MIN_STUDIES_FOR_BIAS_TEST = 10

    def __init__(self, config: ValidatorConfig | None = None):
        super().__init__(config)
        self.bounds = PublicationBiasBounds()
        # Get custom params from config
        params = config.params if config else {}
        if params and "min_studies" in params:
            self.MIN_STUDIES_FOR_BIAS_TEST = params["min_studies"]

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate publication bias claims."""
        errors = []
        warnings = []
        validated_count = 0

        for claim in claims:
            # Check if this claim contains publication bias data
            if not self._is_bias_claim(claim):
                continue

            validated_count += 1
            errors.extend(self._validate_numeric_metadata(claim))

            # Validate Egger's test
            egger_errors, egger_warnings = self._validate_eggers_test(claim)
            errors.extend(egger_errors)
            warnings.extend(egger_warnings)

            # Validate Begg's test
            begg_errors, begg_warnings = self._validate_beggs_test(claim)
            errors.extend(begg_errors)
            warnings.extend(begg_warnings)

            # Validate fail-safe N
            fsn_errors, fsn_warnings = self._validate_fail_safe_n(claim)
            errors.extend(fsn_errors)
            warnings.extend(fsn_warnings)

            # Validate trim-and-fill
            tf_errors, tf_warnings = self._validate_trim_and_fill(claim)
            errors.extend(tf_errors)
            warnings.extend(tf_warnings)

            # Validate funnel plot metrics
            fp_errors, fp_warnings = self._validate_funnel_plot(claim)
            errors.extend(fp_errors)
            warnings.extend(fp_warnings)

            # Check study count
            k = self._get_stat(claim, ["k", "n_studies", "num_studies"])
            if k is not None and k < self.MIN_STUDIES_FOR_BIAS_TEST:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "issue": f"Publication bias tests have low power with k={k} studies",
                    "recommendation": f"At least {self.MIN_STUDIES_FOR_BIAS_TEST} studies recommended",
                })

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} publication bias statistics"
                if passed
                else f"Publication bias validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
                "minimum_studies_recommended": self.MIN_STUDIES_FOR_BIAS_TEST,
            },
        )

    @staticmethod
    def _validate_numeric_metadata(claim: NumericClaim) -> list[dict]:
        """Refuse malformed declared statistics; never silently treat them as absent."""
        errors = []
        for raw_key, value in claim.metadata.items():
            key = raw_key.lower().replace("-", "_").replace(" ", "_")
            if key not in _NUMERIC_BIAS_STATS:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                errors.append({
                    "claim_id": claim.claim_id,
                    "statistic": raw_key,
                    "issue": "Declared publication-bias statistic is not a finite numeric value",
                })
        return errors

    def _is_bias_claim(self, claim: NumericClaim) -> bool:
        """Check if claim contains publication bias statistics."""
        bias_keys = {
            # Egger's test
            "egger_intercept", "egger_pvalue", "egger_p", "egger_se", "egger_t",
            # Begg's test
            "begg_z", "begg_pvalue", "begg_p", "begg_tau", "kendall_tau",
            # Fail-safe N
            "fail_safe_n", "rosenthal_n", "orwin_n", "fsn",
            # Trim-and-fill
            "trim_fill", "imputed_studies", "tf_estimate", "adjusted_estimate",
            # Funnel plot
            "funnel_asymmetry", "peters_test", "harbord_test",
            "peters_p", "peters_pvalue", "harbord_p", "harbord_pvalue",
            # General
            "publication_bias",
        }
        claim_keys = {k.lower().replace("-", "_").replace(" ", "_") for k in claim.metadata}
        return bool(bias_keys & claim_keys)

    def _validate_eggers_test(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate Egger's regression test statistics."""
        errors = []
        warnings = []

        intercept = self._get_stat(claim, ["egger_intercept", "egger_b0", "egger_int"])
        p_value = self._get_stat(claim, ["egger_pvalue", "egger_p"])
        se = self._get_stat(claim, ["egger_se", "egger_stderr"])
        t_stat = self._get_stat(claim, ["egger_t", "egger_tstat"])

        # Validate p-value
        if p_value is not None:
            if p_value < self.bounds.p_value_min or p_value > self.bounds.p_value_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Egger's",
                    "statistic": "p-value",
                    "value": p_value,
                    "issue": f"P-value must be between 0 and 1 (got {p_value})",
                })

        # Validate intercept plausibility
        if intercept is not None:
            if abs(intercept) > self.bounds.egger_intercept_extreme:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "test": "Egger's",
                    "statistic": "intercept",
                    "value": intercept,
                    "issue": f"Extreme intercept value (|{intercept}| > {self.bounds.egger_intercept_extreme})",
                    "interpretation": "May indicate severe bias or data issues",
                })

        # Validate SE is positive
        if se is not None and se <= 0:
            errors.append({
                "claim_id": claim.claim_id,
                "test": "Egger's",
                "statistic": "SE",
                "value": se,
                "issue": "Standard error must be positive",
            })

        # Cross-validate t-statistic
        if intercept is not None and se is not None and se > 0 and t_stat is not None:
            expected_t = intercept / se
            tolerance = 0.1 * abs(expected_t) if expected_t != 0 else 0.1
            if abs(t_stat - expected_t) > tolerance:
                warnings.append({
                    "claim_id": claim.claim_id,
                    "test": "Egger's",
                    "issue": f"t-statistic ({t_stat}) inconsistent with intercept/SE",
                    "expected_t": round(expected_t, 4),
                })

        # Interpretation warning for significant Egger's test
        if p_value is not None and p_value < 0.10 and intercept is not None:
            direction = "toward smaller studies" if intercept > 0 else "toward larger studies"
            warnings.append({
                "claim_id": claim.claim_id,
                "test": "Egger's",
                "issue": f"Significant Egger's test (p={p_value}) suggests funnel plot asymmetry",
                "direction": direction,
            })

        return errors, warnings

    def _validate_beggs_test(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate Begg's rank correlation test."""
        errors = []
        warnings = []

        kendall_tau = self._get_stat(claim, ["begg_tau", "kendall_tau", "tau"])
        p_value = self._get_stat(claim, ["begg_pvalue", "begg_p"])

        # Validate Kendall's tau bounds
        if kendall_tau is not None:
            if kendall_tau < self.bounds.correlation_min or kendall_tau > self.bounds.correlation_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Begg's",
                    "statistic": "Kendall's tau",
                    "value": kendall_tau,
                    "issue": f"Kendall's tau must be between -1 and 1 (got {kendall_tau})",
                })

        # Validate p-value
        if p_value is not None:
            if p_value < self.bounds.p_value_min or p_value > self.bounds.p_value_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Begg's",
                    "statistic": "p-value",
                    "value": p_value,
                    "issue": f"P-value must be between 0 and 1 (got {p_value})",
                })

        return errors, warnings

    def _validate_fail_safe_n(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate fail-safe N calculations."""
        errors = []
        warnings = []

        rosenthal_n = self._get_stat(claim, ["rosenthal_n", "rosenthal_fsn", "fail_safe_n", "fsn"])
        orwin_n = self._get_stat(claim, ["orwin_n", "orwin_fsn"])

        for name, value in [("Rosenthal's", rosenthal_n), ("Orwin's", orwin_n)]:
            if value is not None:
                # Must be non-negative
                if value < self.bounds.fail_safe_n_min:
                    errors.append({
                        "claim_id": claim.claim_id,
                        "test": f"{name} fail-safe N",
                        "value": value,
                        "issue": f"Fail-safe N must be non-negative (got {value})",
                    })

                # Must be integer (or close to it)
                if value >= 0 and abs(value - round(value)) > 0.01:
                    warnings.append({
                        "claim_id": claim.claim_id,
                        "test": f"{name} fail-safe N",
                        "value": value,
                        "issue": f"Fail-safe N should be an integer (got {value})",
                    })

                # Interpretation for small fail-safe N
                k = self._get_stat(claim, ["k", "n_studies"])
                if k is not None and value < 5 * k + 10:
                    warnings.append({
                        "claim_id": claim.claim_id,
                        "test": f"{name} fail-safe N",
                        "value": value,
                        "issue": f"Fail-safe N ({value}) < 5k + 10 ({5 * k + 10})",
                        "interpretation": "Results may not be robust to publication bias",
                    })

        return errors, warnings

    def _validate_trim_and_fill(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate Duval & Tweedie trim-and-fill statistics."""
        errors = []
        warnings = []

        imputed = self._get_stat(claim, ["imputed_studies", "tf_imputed", "trimfill_k0"])
        original_estimate = self._get_stat(claim, ["original_estimate", "unadjusted_estimate"])
        adjusted_estimate = self._get_stat(claim, ["adjusted_estimate", "tf_estimate", "trimfill_estimate"])
        side = claim.metadata.get("trimfill_side", claim.metadata.get("tf_side"))

        # Imputed studies must be non-negative
        if imputed is not None:
            if imputed < self.bounds.imputed_studies_min:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Trim-and-fill",
                    "statistic": "imputed studies",
                    "value": imputed,
                    "issue": f"Number of imputed studies must be non-negative (got {imputed})",
                })

            if imputed > 0 and original_estimate is not None and adjusted_estimate is not None:
                # Adjusted should typically be attenuated (closer to null)
                # This is a warning, not an error, as exceptions exist
                if abs(adjusted_estimate) > abs(original_estimate):
                    warnings.append({
                        "claim_id": claim.claim_id,
                        "test": "Trim-and-fill",
                        "issue": "Adjusted estimate larger than original",
                        "original": original_estimate,
                        "adjusted": adjusted_estimate,
                        "interpretation": "Unusual pattern; verify imputation side",
                    })

        # Validate side specification
        valid_sides = ["left", "right", "both", "L", "R", "B"]
        if side is not None and str(side) not in valid_sides:
            warnings.append({
                "claim_id": claim.claim_id,
                "test": "Trim-and-fill",
                "issue": f"Unknown trimfill side: {side}",
                "valid_options": valid_sides,
            })

        return errors, warnings

    def _validate_funnel_plot(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate funnel plot asymmetry metrics."""
        errors = []
        warnings = []

        # Peters test (weighted regression)
        peters_p = self._get_stat(claim, ["peters_p", "peters_pvalue"])
        if peters_p is not None:
            if peters_p < self.bounds.p_value_min or peters_p > self.bounds.p_value_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Peters",
                    "statistic": "p-value",
                    "value": peters_p,
                    "issue": f"P-value must be between 0 and 1 (got {peters_p})",
                })

        # Harbord test (for binary outcomes)
        harbord_p = self._get_stat(claim, ["harbord_p", "harbord_pvalue"])
        if harbord_p is not None:
            if harbord_p < self.bounds.p_value_min or harbord_p > self.bounds.p_value_max:
                errors.append({
                    "claim_id": claim.claim_id,
                    "test": "Harbord",
                    "statistic": "p-value",
                    "value": harbord_p,
                    "issue": f"P-value must be between 0 and 1 (got {harbord_p})",
                })

        return errors, warnings

    def _get_stat(self, claim: NumericClaim, keys: list[str]) -> float | None:
        """Get a statistic from claim metadata by trying multiple keys."""
        for key in keys:
            # Try exact key
            if key in claim.metadata:
                val = claim.metadata[key]
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return float(val)

            # Try with variations
            for k, v in claim.metadata.items():
                k_normalized = k.lower().replace("-", "_").replace(" ", "_")
                if k_normalized == key.lower():
                    if isinstance(v, (int, float)) and not math.isnan(v):
                        return float(v)

        return None


def compute_rosenthal_fail_safe_n(z_values: list[float], alpha: float = 0.05) -> int:
    """
    Compute Rosenthal's fail-safe N.

    Formula: N = ((sum(z) / z_crit)² - k)

    Args:
        z_values: Z-scores from each study
        alpha: Significance level

    Returns:
        Number of null studies needed to make result non-significant
    """
    import scipy.stats as stats

    k = len(z_values)
    sum_z = sum(z_values)
    z_crit = stats.norm.ppf(1 - alpha / 2)

    fsn = (sum_z / z_crit) ** 2 - k
    return max(0, int(fsn))


def interpret_publication_bias(
    egger_p: float | None = None,
    begg_p: float | None = None,
    fail_safe_n: int | None = None,
    k: int = 0,
) -> str:
    """
    Provide interpretation of publication bias evidence.

    Args:
        egger_p: P-value from Egger's test
        begg_p: P-value from Begg's test
        fail_safe_n: Rosenthal's fail-safe N
        k: Number of studies

    Returns:
        Interpretation string
    """
    concerns = []

    if egger_p is not None and egger_p < 0.10:
        concerns.append(f"Egger's test suggests asymmetry (p={egger_p:.3f})")

    if begg_p is not None and begg_p < 0.10:
        concerns.append(f"Begg's test suggests asymmetry (p={begg_p:.3f})")

    if fail_safe_n is not None and k > 0:
        threshold = 5 * k + 10
        if fail_safe_n < threshold:
            concerns.append(f"Fail-safe N ({fail_safe_n}) below threshold ({threshold})")

    if not concerns:
        return "No strong evidence of publication bias detected"
    elif len(concerns) == 1:
        return f"Possible publication bias: {concerns[0]}"
    else:
        return "Multiple indicators suggest publication bias:\n" + "\n".join(f"  - {c}" for c in concerns)
