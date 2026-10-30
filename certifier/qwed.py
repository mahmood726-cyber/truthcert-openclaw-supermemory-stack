"""
QWED (Quantitative Workflow with External Determinism) Integration.

QWED treats the LLM as an untrusted translator that proposes numeric outputs,
which are then verified by deterministic engines (SymPy, Z3, statistical checks).

This module provides:
1. Mathematical expression verification (via SymPy)
2. Statistical constraint verification
3. Confidence interval consistency checks
4. Meta-analysis formula verification

References:
- "Formal Methods for Machine Learning" - A. Platzer
- "QWED: Verifiable LLM Outputs" (conceptual framework)
"""

import ast
import math
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from .models import ClaimType, NumericClaim

# =============================================================================
# Statistical Distribution Helper Functions
# =============================================================================


def _t_ppf(p: float, df: float) -> float:
    """
    Approximate the inverse CDF (percent point function) of Student's t-distribution.

    Uses a polynomial approximation based on the Hill (1970) algorithm.
    For large df (>100), falls back to normal approximation.

    Args:
        p: Probability (typically 0.975 for 95% CI upper tail)
        df: Degrees of freedom

    Returns:
        t-value corresponding to probability p

    References:
        - Hill, G.W. (1970). "Algorithm 396: Student's t-quantiles".
          Communications of the ACM. 13 (10): 619-620.
    """
    if df <= 0:
        raise ValueError("Degrees of freedom must be positive")
    if p <= 0 or p >= 1:
        raise ValueError("Probability must be between 0 and 1")

    # Standard normal quantile using rational approximation (Abramowitz & Stegun 26.2.23)
    def _normal_ppf(prob: float) -> float:
        if prob < 0.5:
            sign = -1
            p_adj = prob
        else:
            sign = 1
            p_adj = 1 - prob

        t = math.sqrt(-2 * math.log(p_adj))
        c0 = 2.515517
        c1 = 0.802853
        c2 = 0.010328
        d1 = 1.432788
        d2 = 0.189269
        d3 = 0.001308

        z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
        return sign * z

    # For large df, use normal approximation
    if df > 100:
        return _normal_ppf(p)

    # Hill's algorithm for t-distribution quantile
    x = _normal_ppf(p)

    # Correction for t-distribution using Cornish-Fisher expansion
    g1 = (x**3 + x) / 4
    g2 = (5 * x**5 + 16 * x**3 + 3 * x) / 96
    g3 = (3 * x**7 + 19 * x**5 + 17 * x**3 - 15 * x) / 384
    g4 = (79 * x**9 + 776 * x**7 + 1482 * x**5 - 1920 * x**3 - 945 * x) / 92160

    t_val = x + g1 / df + g2 / (df**2) + g3 / (df**3) + g4 / (df**4)

    return t_val


def _get_critical_value(confidence: float, df: int | None = None, use_t: bool = False) -> float:
    """
    Get the critical value for a two-tailed confidence interval.

    Args:
        confidence: Confidence level (e.g., 0.95)
        df: Degrees of freedom (required if use_t=True)
        use_t: Whether to use t-distribution instead of normal

    Returns:
        Critical value (z or t)
    """
    alpha = 1 - confidence
    p = 1 - alpha / 2  # Upper tail probability

    if use_t and df is not None and df > 0:
        return _t_ppf(p, df)

    # Standard z-values for common confidence levels (faster than computing)
    z_values = {
        0.90: 1.645,
        0.95: 1.96,
        0.99: 2.576,
    }

    if confidence in z_values:
        return z_values[confidence]

    # Compute z-value for non-standard confidence levels
    # Using Abramowitz & Stegun approximation
    if p < 0.5:
        sign = -1
        p_adj = p
    else:
        sign = 1
        p_adj = 1 - p

    t = math.sqrt(-2 * math.log(p_adj))
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return sign * z


class VerificationStatus(str, Enum):
    """Status of deterministic verification."""

    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class VerificationResult:
    """Result of a QWED verification check."""

    status: VerificationStatus
    message: str
    claim_id: str
    check_type: str
    expected: Any | None = None
    actual: Any | None = None
    tolerance: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class QWEDVerifier:
    """
    Deterministic verification engine for numeric claims.

    Verifies that claimed numeric values are mathematically consistent
    with their associated metadata (e.g., CI from SE, pooled effects, etc.)
    """

    # Tolerance levels for floating-point comparisons
    TOLERANCE_STRICT = 1e-10
    TOLERANCE_NORMAL = 1e-6
    TOLERANCE_RELAXED = 1e-4
    TOLERANCE_STATISTICAL = 0.01  # 1% for statistical calculations

    def __init__(self, tolerance: float | None = None) -> None:
        self.tolerance = tolerance or self.TOLERANCE_STATISTICAL

    def verify_claim(self, claim: NumericClaim) -> list[VerificationResult]:
        """
        Run all applicable deterministic verifications on a claim.

        Returns list of verification results.
        """
        results = []

        # CI consistency check
        if claim.lower_bound is not None and claim.upper_bound is not None:
            results.append(self._verify_ci_bounds(claim))

            if claim.standard_error is not None:
                # Use t-distribution for small samples (n < 30)
                use_t = claim.sample_size is not None and claim.sample_size < 30
                results.append(self._verify_ci_from_se(claim, use_t_distribution=use_t))

        # Effect size specific checks for ratio measures (RR, OR, HR)
        if claim.claim_type in (ClaimType.RISK_RATIO, ClaimType.ODDS_RATIO, ClaimType.HAZARD_RATIO):
            results.append(self._verify_ratio_constraints(claim))
            # Log-scale CI verification for ratio measures
            if claim.lower_bound is not None and claim.upper_bound is not None:
                results.append(self._verify_log_scale_ci_symmetry(claim))

        if claim.claim_type == ClaimType.CORRELATION:
            results.append(self._verify_correlation_bounds(claim))

        # Meta-analysis checks
        if claim.claim_type == ClaimType.I_SQUARED:
            results.append(self._verify_i_squared(claim))

        if claim.claim_type == ClaimType.POOLED_EFFECT and claim.n_studies:
            if claim.metadata.get("study_effects") and claim.metadata.get("study_weights"):
                results.append(self._verify_pooled_effect(claim))

            # Random-effects pooling verification (DerSimonian-Laird)
            if claim.metadata.get("study_effects") and claim.metadata.get("study_variances"):
                results.append(self._verify_random_effects_pooling(claim))

        # Prediction interval validation
        if claim.claim_type == ClaimType.PREDICTION_INTERVAL:
            results.append(self._verify_prediction_interval(claim))

        # Variance/SE consistency
        if claim.variance is not None and claim.standard_error is not None:
            results.append(self._verify_variance_se_consistency(claim))

        return results

    def _verify_ci_bounds(self, claim: NumericClaim) -> VerificationResult:
        """Verify CI bounds are ordered correctly."""
        lower = claim.lower_bound
        upper = claim.upper_bound
        value = claim.value

        if lower is None or upper is None:
            raise ValueError("CI bounds are required")

        # Check ordering
        if lower > upper:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"CI bounds inverted: lower ({lower}) > upper ({upper})",
                claim_id=claim.claim_id,
                check_type="ci_ordering",
                expected="lower <= upper",
                actual=f"lower={lower}, upper={upper}",
            )

        # Check value is within CI
        if not (lower <= value <= upper):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Point estimate ({value}) outside CI [{lower}, {upper}]",
                claim_id=claim.claim_id,
                check_type="ci_containment",
                expected=f"{lower} <= {value} <= {upper}",
                actual=f"value={value} not in [{lower}, {upper}]",
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="CI bounds verified",
            claim_id=claim.claim_id,
            check_type="ci_ordering",
        )

    def _verify_ci_from_se(
        self, claim: NumericClaim, use_t_distribution: bool = False
    ) -> VerificationResult:
        """
        Verify CI is consistent with SE using normal or t-distribution.

        For 95% CI with normal distribution: value +/- 1.96 * SE
        For 95% CI with t-distribution: value +/- t(df, 0.975) * SE

        Args:
            claim: The numeric claim to verify
            use_t_distribution: If True and sample_size is available, use
                t-distribution (recommended when n < 30)

        References:
            - Altman DG, et al. (2000). "Statistics with Confidence"
            - For small samples, t-distribution provides wider, more accurate CIs
        """
        se = claim.standard_error
        value = claim.value
        lower = claim.lower_bound
        upper = claim.upper_bound
        confidence = claim.confidence_level or 0.95

        if lower is None or upper is None or se is None:
            raise ValueError("CI bounds and standard error are required")

        # Determine critical value (z or t)
        distribution_used = "normal"
        if use_t_distribution and claim.sample_size is not None and claim.sample_size > 1:
            df = claim.sample_size - 1
            critical_value = _get_critical_value(confidence, df=df, use_t=True)
            distribution_used = f"t(df={df})"
        else:
            critical_value = _get_critical_value(confidence, use_t=False)

        # Expected CI
        expected_lower = value - critical_value * se
        expected_upper = value + critical_value * se

        # Check with tolerance
        lower_diff = abs(lower - expected_lower)
        upper_diff = abs(upper - expected_upper)

        # Use relative tolerance for larger values
        rel_tol = max(abs(value) * self.tolerance, self.TOLERANCE_NORMAL)

        if lower_diff > rel_tol or upper_diff > rel_tol:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"CI inconsistent with SE ({distribution_used}): expected [{expected_lower:.4f}, {expected_upper:.4f}]",
                claim_id=claim.claim_id,
                check_type="ci_se_consistency",
                expected=f"[{expected_lower:.4f}, {expected_upper:.4f}]",
                actual=f"[{lower:.4f}, {upper:.4f}]",
                tolerance=rel_tol,
                details={
                    "se": se,
                    "critical_value": critical_value,
                    "distribution": distribution_used,
                    "confidence_level": confidence,
                    "lower_diff": lower_diff,
                    "upper_diff": upper_diff,
                    "sample_size": claim.sample_size,
                },
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message=f"CI consistent with SE ({distribution_used})",
            claim_id=claim.claim_id,
            check_type="ci_se_consistency",
            details={
                "distribution": distribution_used,
                "critical_value": critical_value,
            },
        )

    def _verify_ratio_constraints(self, claim: NumericClaim) -> VerificationResult:
        """Verify ratio measures (RR, OR, HR) are positive."""
        value = claim.value

        if value <= 0:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Ratio measure must be positive, got {value}",
                claim_id=claim.claim_id,
                check_type="ratio_positive",
                expected="> 0",
                actual=value,
            )

        # Check CI bounds if present
        if claim.lower_bound is not None and claim.lower_bound <= 0:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Ratio CI lower bound must be positive, got {claim.lower_bound}",
                claim_id=claim.claim_id,
                check_type="ratio_ci_positive",
                expected="> 0",
                actual=claim.lower_bound,
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Ratio constraints verified",
            claim_id=claim.claim_id,
            check_type="ratio_positive",
        )

    def _verify_log_scale_ci_symmetry(self, claim: NumericClaim) -> VerificationResult:
        """
        Verify that CI for ratio measures (RR, OR, HR) is symmetric on log scale.

        For ratio measures, CIs are calculated on the log scale:
        - log(lower) and log(upper) should be symmetric around log(value)
        - Formula: log_value +/- z * SE_log
        - Where: SE_log = (log(upper) - log(lower)) / (2 * z)

        This ensures the reported CI follows proper statistical methodology.

        References:
            - Bland JM, Altman DG (2000). "The odds ratio". BMJ 320:1468.
            - Borenstein M, et al. (2009). "Introduction to Meta-Analysis". Wiley.
        """
        value = claim.value
        lower = claim.lower_bound
        upper = claim.upper_bound
        confidence = claim.confidence_level or 0.95

        if lower is None or upper is None:
            raise ValueError("CI bounds are required")

        # Get z-value for confidence level
        z = _get_critical_value(confidence, use_t=False)

        # Values must be positive for log transformation
        if value <= 0 or lower <= 0 or upper <= 0:
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message="Cannot verify log-scale symmetry: non-positive values",
                claim_id=claim.claim_id,
                check_type="log_scale_ci_symmetry",
                details={"value": value, "lower": lower, "upper": upper},
            )

        # Transform to log scale
        log_value = math.log(value)
        log_lower = math.log(lower)
        log_upper = math.log(upper)

        # Calculate distances from point estimate on log scale
        dist_lower = log_value - log_lower
        dist_upper = log_upper - log_value

        # Calculate SE on log scale (derived from CI width)
        se_log = (log_upper - log_lower) / (2 * z)

        # Check symmetry: distances should be equal (both equal to z * SE_log)
        symmetry_diff = abs(dist_lower - dist_upper)

        # Use relative tolerance based on the SE
        rel_tol = max(se_log * self.tolerance * 2, self.TOLERANCE_RELAXED)

        if symmetry_diff > rel_tol:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Log-scale CI not symmetric: lower distance={dist_lower:.4f}, upper distance={dist_upper:.4f}",
                claim_id=claim.claim_id,
                check_type="log_scale_ci_symmetry",
                expected=f"symmetric distances (~{z * se_log:.4f})",
                actual=f"lower_dist={dist_lower:.4f}, upper_dist={dist_upper:.4f}",
                tolerance=rel_tol,
                details={
                    "log_value": log_value,
                    "log_lower": log_lower,
                    "log_upper": log_upper,
                    "se_log": se_log,
                    "z_value": z,
                    "symmetry_difference": symmetry_diff,
                },
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Log-scale CI symmetry verified",
            claim_id=claim.claim_id,
            check_type="log_scale_ci_symmetry",
            details={
                "se_log": se_log,
                "log_value": log_value,
                "symmetry_difference": symmetry_diff,
            },
        )

    def _verify_correlation_bounds(self, claim: NumericClaim) -> VerificationResult:
        """Verify correlation is in [-1, 1]."""
        value = claim.value

        if not -1 <= value <= 1:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Correlation must be in [-1, 1], got {value}",
                claim_id=claim.claim_id,
                check_type="correlation_bounds",
                expected="[-1, 1]",
                actual=value,
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Correlation bounds verified",
            claim_id=claim.claim_id,
            check_type="correlation_bounds",
        )

    def _verify_i_squared(self, claim: NumericClaim) -> VerificationResult:
        """Verify I² is in [0, 100]."""
        value = claim.value

        if not 0 <= value <= 100:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"I² must be in [0, 100], got {value}",
                claim_id=claim.claim_id,
                check_type="i_squared_bounds",
                expected="[0, 100]",
                actual=value,
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="I² bounds verified",
            claim_id=claim.claim_id,
            check_type="i_squared_bounds",
        )

    def _verify_pooled_effect(self, claim: NumericClaim) -> VerificationResult:
        """
        Verify pooled effect from study-level data.

        For inverse-variance weighting:
        pooled = sum(w_i * y_i) / sum(w_i)
        """
        effects = claim.metadata.get("study_effects", [])
        weights = claim.metadata.get("study_weights", [])

        if len(effects) != len(weights):
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message="Mismatched effects and weights arrays",
                claim_id=claim.claim_id,
                check_type="pooled_effect",
            )

        if sum(weights) == 0:
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message="Sum of weights is zero",
                claim_id=claim.claim_id,
                check_type="pooled_effect",
            )

        # Calculate expected pooled effect
        expected = sum(e * w for e, w in zip(effects, weights)) / sum(weights)

        # Compare with claimed value
        diff = abs(claim.value - expected)
        rel_tol = max(abs(expected) * self.tolerance, self.TOLERANCE_NORMAL)

        if diff > rel_tol:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Pooled effect verification failed: expected {expected:.4f}, got {claim.value:.4f}",
                claim_id=claim.claim_id,
                check_type="pooled_effect",
                expected=expected,
                actual=claim.value,
                tolerance=rel_tol,
                details={
                    "difference": diff,
                    "n_studies": len(effects),
                },
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Pooled effect verified",
            claim_id=claim.claim_id,
            check_type="pooled_effect",
            expected=expected,
            actual=claim.value,
        )

    def _verify_random_effects_pooling(self, claim: NumericClaim) -> VerificationResult:
        """
        Verify random-effects pooling using DerSimonian-Laird method.

        The DerSimonian-Laird (DL) method is the most commonly used approach for
        random-effects meta-analysis. It estimates tau-squared (between-study variance)
        and adjusts study weights accordingly.

        Key formulas:
        - Fixed-effects weights: w_i = 1 / var_i
        - Q statistic: Q = sum(w_i * (y_i - pooled_FE)^2)
        - tau^2 = max(0, (Q - (k-1)) / (sum(w_i) - sum(w_i^2)/sum(w_i)))
        - Random-effects weights: w_i* = 1 / (var_i + tau^2)
        - Pooled RE = sum(w_i* * y_i) / sum(w_i*)

        References:
            - DerSimonian R, Laird N (1986). "Meta-analysis in clinical trials".
              Controlled Clinical Trials 7:177-188.
            - Borenstein M, et al. (2009). "Introduction to Meta-Analysis". Wiley.
        """
        effects = claim.metadata.get("study_effects", [])
        variances = claim.metadata.get("study_variances", [])

        if len(effects) != len(variances):
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message="Mismatched effects and variances arrays",
                claim_id=claim.claim_id,
                check_type="random_effects_pooling",
            )

        k = len(effects)  # Number of studies
        if k < 2:
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                message="Random-effects requires at least 2 studies",
                claim_id=claim.claim_id,
                check_type="random_effects_pooling",
            )

        # Check for non-positive variances
        if any(v <= 0 for v in variances):
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message="All study variances must be positive",
                claim_id=claim.claim_id,
                check_type="random_effects_pooling",
            )

        # Step 1: Calculate fixed-effects weights and pooled estimate
        fe_weights = [1 / v for v in variances]
        sum_fe_weights = sum(fe_weights)
        pooled_fe = sum(w * y for w, y in zip(fe_weights, effects)) / sum_fe_weights

        # Step 2: Calculate Q statistic (measure of heterogeneity)
        Q = sum(w * (y - pooled_fe) ** 2 for w, y in zip(fe_weights, effects))

        # Step 3: Estimate tau-squared using DerSimonian-Laird formula
        C = sum_fe_weights - sum(w**2 for w in fe_weights) / sum_fe_weights
        tau_squared = max(0, (Q - (k - 1)) / C) if C > 0 else 0

        # Step 4: Calculate random-effects weights (adjusted by tau-squared)
        re_weights = [1 / (v + tau_squared) for v in variances]
        sum_re_weights = sum(re_weights)

        # Step 5: Calculate random-effects pooled estimate
        expected_pooled = sum(w * y for w, y in zip(re_weights, effects)) / sum_re_weights

        # Verify against claimed value
        diff = abs(claim.value - expected_pooled)
        rel_tol = max(abs(expected_pooled) * self.tolerance, self.TOLERANCE_RELAXED)

        # Also verify tau_squared if provided
        claimed_tau_squared = claim.tau_squared

        if diff > rel_tol:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Random-effects pooling failed: expected {expected_pooled:.4f}, got {claim.value:.4f}",
                claim_id=claim.claim_id,
                check_type="random_effects_pooling",
                expected=expected_pooled,
                actual=claim.value,
                tolerance=rel_tol,
                details={
                    "tau_squared_estimated": tau_squared,
                    "tau_squared_claimed": claimed_tau_squared,
                    "Q_statistic": Q,
                    "n_studies": k,
                    "difference": diff,
                    "re_weights": re_weights,
                },
            )

        # Optionally verify tau_squared if provided
        tau_sq_result = None
        if claimed_tau_squared is not None:
            tau_diff = abs(tau_squared - claimed_tau_squared)
            tau_tol = max(tau_squared * self.tolerance, self.TOLERANCE_RELAXED)
            if tau_diff > tau_tol:
                tau_sq_result = f"Warning: tau^2 mismatch (estimated={tau_squared:.4f}, claimed={claimed_tau_squared:.4f})"

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Random-effects pooling (DerSimonian-Laird) verified",
            claim_id=claim.claim_id,
            check_type="random_effects_pooling",
            expected=expected_pooled,
            actual=claim.value,
            details={
                "tau_squared": tau_squared,
                "Q_statistic": Q,
                "n_studies": k,
                "tau_squared_warning": tau_sq_result,
            },
        )

    def _verify_prediction_interval(self, claim: NumericClaim) -> VerificationResult:
        """
        Verify prediction interval for meta-analysis.

        The prediction interval (PI) gives the range within which we expect the
        true effect in a new study to fall. It accounts for both within-study
        sampling error and between-study heterogeneity.

        Formula: PI = pooled +/- t(df) * sqrt(tau^2 + SE_pooled^2)
        where:
        - pooled = pooled effect estimate
        - tau^2 = between-study variance
        - SE_pooled = standard error of pooled estimate
        - df = k - 2 (k = number of studies)
        - t(df) = t-distribution critical value

        Validation checks:
        1. PI must contain the pooled estimate
        2. PI must be wider than the confidence interval

        References:
            - Higgins JPT, et al. (2009). "A re-evaluation of random-effects meta-analysis".
              JRSS Series A 172:137-159.
            - IntHout J, et al. (2016). "The Hartung-Knapp-Sidik-Jonkman method for
              random effects meta-analysis is straightforward and considerably outperforms
              the standard DerSimonian-Laird method". BMC Med Res Methodol 16:33.
        """
        # Get required values from claim and metadata
        pooled = claim.metadata.get("pooled_effect")
        tau_squared = claim.tau_squared or claim.metadata.get("tau_squared")
        se_pooled = claim.standard_error or claim.metadata.get("se_pooled")
        n_studies = claim.n_studies or claim.metadata.get("n_studies")
        pi_lower = claim.lower_bound
        pi_upper = claim.upper_bound
        confidence = claim.confidence_level or 0.95

        # Also get CI for comparison if available
        ci_lower = claim.metadata.get("ci_lower")
        ci_upper = claim.metadata.get("ci_upper")

        # Validate required inputs
        missing = []
        if pooled is None:
            missing.append("pooled_effect")
        if tau_squared is None:
            missing.append("tau_squared")
        if se_pooled is None:
            missing.append("se_pooled/standard_error")
        if n_studies is None:
            missing.append("n_studies")
        if pi_lower is None or pi_upper is None:
            missing.append("PI bounds (lower_bound/upper_bound)")

        if (
            pooled is None
            or tau_squared is None
            or se_pooled is None
            or n_studies is None
            or pi_lower is None
            or pi_upper is None
        ):
            return VerificationResult(
                status=VerificationStatus.ERROR,
                message=f"Missing required data for PI verification: {', '.join(missing)}",
                claim_id=claim.claim_id,
                check_type="prediction_interval",
            )

        # Need at least 3 studies for PI (df = k - 2 >= 1)
        if n_studies < 3:
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                message="Prediction interval requires at least 3 studies (df = k-2 >= 1)",
                claim_id=claim.claim_id,
                check_type="prediction_interval",
                details={"n_studies": n_studies},
            )

        # Calculate expected PI
        df = n_studies - 2
        t_crit = _get_critical_value(confidence, df=df, use_t=True)

        # PI width calculation
        pi_se = math.sqrt(tau_squared + se_pooled**2)
        expected_pi_lower = pooled - t_crit * pi_se
        expected_pi_upper = pooled + t_crit * pi_se

        # Validation checks
        errors = []

        # Check 1: PI must contain pooled estimate
        if not (pi_lower <= pooled <= pi_upper):
            errors.append(
                f"PI [{pi_lower:.4f}, {pi_upper:.4f}] does not contain pooled estimate {pooled:.4f}"
            )

        # Check 2: PI bounds should be correctly ordered
        if pi_lower > pi_upper:
            errors.append(f"PI bounds inverted: lower ({pi_lower}) > upper ({pi_upper})")

        # Check 3: Compare with expected PI (with tolerance)
        lower_diff = abs(pi_lower - expected_pi_lower)
        upper_diff = abs(pi_upper - expected_pi_upper)
        rel_tol = max(pi_se * self.tolerance * 2, self.TOLERANCE_RELAXED)

        if lower_diff > rel_tol or upper_diff > rel_tol:
            errors.append(
                f"PI mismatch: expected [{expected_pi_lower:.4f}, {expected_pi_upper:.4f}], "
                f"got [{pi_lower:.4f}, {pi_upper:.4f}]"
            )

        # Check 4: PI should be wider than CI (if CI provided)
        if ci_lower is not None and ci_upper is not None:
            ci_width = ci_upper - ci_lower
            pi_width = pi_upper - pi_lower
            if pi_width < ci_width - self.TOLERANCE_RELAXED:
                errors.append(f"PI width ({pi_width:.4f}) should be >= CI width ({ci_width:.4f})")

        if errors:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message="; ".join(errors),
                claim_id=claim.claim_id,
                check_type="prediction_interval",
                expected=f"[{expected_pi_lower:.4f}, {expected_pi_upper:.4f}]",
                actual=f"[{pi_lower:.4f}, {pi_upper:.4f}]",
                tolerance=rel_tol,
                details={
                    "pooled": pooled,
                    "tau_squared": tau_squared,
                    "se_pooled": se_pooled,
                    "n_studies": n_studies,
                    "df": df,
                    "t_critical": t_crit,
                    "pi_se": pi_se,
                    "errors": errors,
                },
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Prediction interval verified",
            claim_id=claim.claim_id,
            check_type="prediction_interval",
            expected=f"[{expected_pi_lower:.4f}, {expected_pi_upper:.4f}]",
            actual=f"[{pi_lower:.4f}, {pi_upper:.4f}]",
            details={
                "pooled": pooled,
                "tau_squared": tau_squared,
                "se_pooled": se_pooled,
                "n_studies": n_studies,
                "df": df,
                "t_critical": t_crit,
                "pi_se": pi_se,
            },
        )

    def _verify_variance_se_consistency(self, claim: NumericClaim) -> VerificationResult:
        """Verify variance = SE²."""
        variance = claim.variance
        se = claim.standard_error

        if variance is None or se is None:
            raise ValueError("Variance and standard error are required")

        expected_variance = se**2
        diff = abs(variance - expected_variance)

        rel_tol = max(expected_variance * self.tolerance, self.TOLERANCE_NORMAL)

        if diff > rel_tol:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Variance ({variance}) inconsistent with SE² ({expected_variance})",
                claim_id=claim.claim_id,
                check_type="variance_se_consistency",
                expected=expected_variance,
                actual=variance,
                tolerance=rel_tol,
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Variance/SE consistency verified",
            claim_id=claim.claim_id,
            check_type="variance_se_consistency",
        )


class SafeExpressionEvaluator:
    """
    Safe mathematical expression evaluator using AST parsing.

    This replaces eval() with a safe AST-based parser that only allows:
    - Numeric literals (int, float)
    - Basic arithmetic operators: +, -, *, /, **, unary -, unary +
    - Allowed function calls: sqrt, log, exp, abs, sin, cos, tan, pow
    - Variable references (from provided variables dict)

    Rejects any code injection attempts including:
    - Attribute access (obj.attr)
    - Subscript access (obj[key])
    - Comprehensions
    - Lambda expressions
    - Import statements
    - Any other Python constructs
    """

    # Allowed binary operators
    BINARY_OPS: ClassVar[dict[type[ast.operator], Callable[[float, float], float]]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
    }

    # Allowed unary operators
    UNARY_OPS: ClassVar[dict[type[ast.unaryop], Callable[[float], float]]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    # Allowed safe functions
    SAFE_FUNCTIONS: ClassVar[dict[str, Callable[..., float]]] = {
        "sqrt": math.sqrt,
        "log": math.log,
        "exp": math.exp,
        "abs": abs,
        "pow": pow,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
    }

    def __init__(self, variables: dict[str, float] | None = None) -> None:
        """
        Initialize the evaluator with variable bindings.

        Args:
            variables: Dictionary mapping variable names to numeric values
        """
        self.variables = variables or {}

    def evaluate(self, expression: str) -> float:
        """
        Safely evaluate a mathematical expression.

        Args:
            expression: Mathematical expression string

        Returns:
            Numeric result of the expression

        Raises:
            ValueError: If expression contains disallowed constructs
            SyntaxError: If expression is not valid Python syntax
        """
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {e}")

        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> float:
        """Recursively evaluate an AST node."""

        # Numeric literals
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"Only numeric constants allowed, got: {type(node.value).__name__}")

        # Variable references
        if isinstance(node, ast.Name):
            var_name = node.id
            # Check if it's a variable
            if var_name in self.variables:
                return float(self.variables[var_name])
            # Check if it's a safe function being referenced (shouldn't happen in valid expressions)
            if var_name in self.SAFE_FUNCTIONS:
                raise ValueError(f"Function '{var_name}' must be called with arguments")
            raise ValueError(f"Unknown variable: {var_name}")

        # Binary operations
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self.BINARY_OPS:
                raise ValueError(f"Disallowed binary operator: {op_type.__name__}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self.BINARY_OPS[op_type](left, right)

        # Unary operations
        if isinstance(node, ast.UnaryOp):
            unary_type = type(node.op)
            if unary_type not in self.UNARY_OPS:
                raise ValueError(f"Disallowed unary operator: {unary_type.__name__}")
            operand = self._eval_node(node.operand)
            return self.UNARY_OPS[unary_type](operand)

        # Function calls (only allowed functions)
        if isinstance(node, ast.Call):
            # Must be a simple name call (not attribute access)
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function calls allowed (no method calls)")  # noqa: TRY004 -- public syntax-rejection API uses ValueError

            func_name = node.func.id
            if func_name not in self.SAFE_FUNCTIONS:
                raise ValueError(f"Disallowed function: {func_name}")

            # Evaluate arguments
            args = [self._eval_node(arg) for arg in node.args]

            # Reject keyword arguments
            if node.keywords:
                raise ValueError("Keyword arguments not allowed in function calls")

            return self.SAFE_FUNCTIONS[func_name](*args)

        # Parenthesized expressions are handled automatically

        # Reject all other node types (security: prevent code injection)
        disallowed = [
            (ast.Attribute, "attribute access"),
            (ast.Subscript, "subscript access"),
            (ast.Lambda, "lambda expressions"),
            (ast.ListComp, "list comprehensions"),
            (ast.SetComp, "set comprehensions"),
            (ast.DictComp, "dict comprehensions"),
            (ast.GeneratorExp, "generator expressions"),
            (ast.Await, "await expressions"),
            (ast.Yield, "yield expressions"),
            (ast.YieldFrom, "yield from expressions"),
            (ast.Compare, "comparison expressions"),
            (ast.BoolOp, "boolean operations"),
            (ast.IfExp, "conditional expressions"),
            (ast.Dict, "dict literals"),
            (ast.Set, "set literals"),
            (ast.List, "list literals"),
            (ast.Tuple, "tuple literals"),
            (ast.Starred, "starred expressions"),
            (ast.JoinedStr, "f-strings"),
            (ast.FormattedValue, "formatted values"),
            (ast.NamedExpr, "walrus operator"),
        ]

        for node_type, description in disallowed:
            if isinstance(node, node_type):
                raise ValueError(f"Disallowed construct: {description}")  # noqa: TRY004 -- public syntax-rejection API uses ValueError

        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def verify_formula(
    formula: str,
    variables: dict[str, float],
    expected_result: float,
    tolerance: float = 1e-6,
) -> VerificationResult:
    """
    Verify a mathematical formula using safe AST-based evaluation.

    This function uses a secure expression parser that:
    - Parses the formula as an AST (Abstract Syntax Tree)
    - Only allows: numeric literals, variables, arithmetic operators, and safe functions
    - Rejects any code injection attempts (attribute access, imports, etc.)

    Args:
        formula: Mathematical expression (e.g., "a + b * c", "sqrt(x) + log(y)")
        variables: Variable bindings (e.g., {"a": 1.0, "b": 2.0, "c": 3.0})
        expected_result: Expected result
        tolerance: Comparison tolerance

    Supported operations:
        - Arithmetic: +, -, *, /, **, %, //
        - Functions: sqrt, log, exp, abs, sin, cos, tan, pow

    Returns:
        VerificationResult
    """
    # Create safe evaluator with provided variables
    evaluator = SafeExpressionEvaluator(variables)

    try:
        # Safely evaluate formula using AST
        result = evaluator.evaluate(formula)

        diff = abs(result - expected_result)
        if diff <= tolerance:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                message=f"Formula verified: {formula} = {result}",
                claim_id="formula",
                check_type="formula_verification",
                expected=expected_result,
                actual=result,
            )
        else:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Formula mismatch: {formula} = {result}, expected {expected_result}",
                claim_id="formula",
                check_type="formula_verification",
                expected=expected_result,
                actual=result,
                tolerance=tolerance,
            )

    except ValueError as e:
        # Security rejection or invalid expression
        return VerificationResult(
            status=VerificationStatus.ERROR,
            message=f"Formula rejected: {e!s}",
            claim_id="formula",
            check_type="formula_verification",
        )
    except (ArithmeticError, TypeError) as e:
        return VerificationResult(
            status=VerificationStatus.ERROR,
            message=f"Formula evaluation error: {e!s}",
            claim_id="formula",
            check_type="formula_verification",
        )


def verify_all_claims(claims: list[NumericClaim]) -> list[VerificationResult]:
    """
    Run QWED verification on all claims.

    Returns aggregated list of verification results.
    """
    verifier = QWEDVerifier()
    all_results = []

    for claim in claims:
        results = verifier.verify_claim(claim)
        all_results.extend(results)

    return all_results


def get_verification_summary(results: list[VerificationResult]) -> dict[str, Any]:
    """
    Get summary statistics from verification results.
    """
    total = len(results)
    verified = sum(1 for r in results if r.status == VerificationStatus.VERIFIED)
    failed = sum(1 for r in results if r.status == VerificationStatus.FAILED)
    errors = sum(1 for r in results if r.status == VerificationStatus.ERROR)
    skipped = sum(1 for r in results if r.status == VerificationStatus.SKIPPED)

    return {
        "total_checks": total,
        "verified": verified,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "pass_rate": verified / total if total > 0 else 1.0,
        "all_passed": failed == 0 and errors == 0,
    }
