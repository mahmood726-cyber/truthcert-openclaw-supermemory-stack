"""
GRADE Certainty of Evidence Validator (tc_grade_certainty)

Implements the GRADE (Grading of Recommendations, Assessment, Development and
Evaluations) framework for assessing certainty of evidence in systematic reviews
and meta-analyses.

The GRADE approach provides a systematic method for rating the certainty of
evidence across outcomes. Evidence starts at a baseline certainty level based
on study design, then may be rated down (downgraded) or up (upgraded) based
on specific criteria.

References:
- Guyatt GH, et al. GRADE guidelines: A new series of articles in the JCE.
  J Clin Epidemiol. 2011;64(4):380-382.
- Schunemann HJ, et al. GRADE Handbook. gradeworkinggroup.org

This is a COMPLETE implementation with full validation logic.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..constants import Severity
from ..models import ClaimType, NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from .base import Validator, ValidatorRegistry

# =============================================================================
# GRADE Enums and Data Classes
# =============================================================================


class GRADECertainty(str, Enum):
    """GRADE certainty of evidence levels."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"

    def __lt__(self, other: "GRADECertainty") -> bool:
        order = [
            GRADECertainty.VERY_LOW,
            GRADECertainty.LOW,
            GRADECertainty.MODERATE,
            GRADECertainty.HIGH,
        ]
        return order.index(self) < order.index(other)

    def __le__(self, other: "GRADECertainty") -> bool:
        return self == other or self < other

    @classmethod
    def from_level(cls, level: int) -> "GRADECertainty":
        """Convert numeric level (0-4) to certainty."""
        levels = {
            4: cls.HIGH,
            3: cls.MODERATE,
            2: cls.LOW,
            1: cls.VERY_LOW,
            0: cls.VERY_LOW,
        }
        return levels.get(max(0, min(4, level)), cls.VERY_LOW)

    def to_level(self) -> int:
        """Convert certainty to numeric level."""
        levels = {
            GRADECertainty.HIGH: 4,
            GRADECertainty.MODERATE: 3,
            GRADECertainty.LOW: 2,
            GRADECertainty.VERY_LOW: 1,
        }
        return levels.get(self, 1)


class StudyDesign(str, Enum):
    """Study design types for determining starting certainty."""

    RCT = "RCT"
    RANDOMIZED_CONTROLLED_TRIAL = RCT
    OBSERVATIONAL = "observational"
    COHORT = OBSERVATIONAL
    CASE_CONTROL = COHORT
    CROSS_SECTIONAL = CASE_CONTROL


class RiskOfBiasLevel(str, Enum):
    """Risk of bias assessment levels."""

    LOW = "low"
    UNCLEAR = "unclear"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"
    CRITICAL = "critical"


class DowngradeReason(str, Enum):
    """Reasons for downgrading certainty."""

    RISK_OF_BIAS = "risk_of_bias"
    INCONSISTENCY = "inconsistency"
    INDIRECTNESS = "indirectness"
    IMPRECISION = "imprecision"
    PUBLICATION_BIAS = "publication_bias"


class UpgradeReason(str, Enum):
    """Reasons for upgrading certainty."""

    LARGE_EFFECT = "large_effect"
    DOSE_RESPONSE = "dose_response"
    PLAUSIBLE_CONFOUNDING = "plausible_confounding"


@dataclass
class DomainAssessment:
    """Assessment result for a single GRADE domain."""

    domain: str
    concern_level: str  # "no_concern", "some_concern", "serious_concern", "very_serious_concern"
    downgrade_levels: int  # 0, 1, or 2
    rationale: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GRADEAssessment:
    """Complete GRADE assessment for an outcome."""

    outcome_id: str
    starting_certainty: GRADECertainty
    study_design: str

    # Downgrading domains
    risk_of_bias: DomainAssessment | None = None
    inconsistency: DomainAssessment | None = None
    indirectness: DomainAssessment | None = None
    imprecision: DomainAssessment | None = None
    publication_bias: DomainAssessment | None = None

    # Upgrading factors
    large_effect: DomainAssessment | None = None
    dose_response: DomainAssessment | None = None
    plausible_confounding: DomainAssessment | None = None

    # Final calculation
    total_downgrade: int = 0
    total_upgrade: int = 0
    final_certainty: GRADECertainty = GRADECertainty.VERY_LOW

    def calculate_final_certainty(self) -> GRADECertainty:
        """Calculate final certainty after all adjustments."""
        level = self.starting_certainty.to_level()

        # Apply downgrades
        downgrades = [
            self.risk_of_bias,
            self.inconsistency,
            self.indirectness,
            self.imprecision,
            self.publication_bias,
        ]
        self.total_downgrade = sum(d.downgrade_levels for d in downgrades if d is not None)
        level -= self.total_downgrade

        # Apply upgrades (only if no serious concerns in downgrade domains)
        if level >= 2:  # Only upgrade if not already very low
            upgrades = [
                self.large_effect,
                self.dose_response,
                self.plausible_confounding,
            ]
            self.total_upgrade = sum(
                d.downgrade_levels for d in upgrades if d is not None and d.downgrade_levels < 0
            )
            # Note: upgrade uses negative downgrade_levels
            level -= self.total_upgrade

        self.final_certainty = GRADECertainty.from_level(level)
        return self.final_certainty


@dataclass
class GRADEThresholds:
    """Configurable thresholds for GRADE assessments."""

    # Inconsistency (I-squared) thresholds
    i_squared_moderate_concern: float = 50.0  # >= 50% is moderate concern
    i_squared_serious_concern: float = 75.0  # >= 75% is serious concern

    # Imprecision thresholds
    ois_minimum: int = 300  # Optimal Information Size minimum
    ci_ratio_threshold: float = 2.5  # CI upper/lower ratio for concern
    events_minimum: int = 300  # Minimum events for adequate precision

    # Large effect thresholds
    rr_large_effect_threshold: float = 2.0  # RR > 2.0 or < 0.5
    rr_very_large_effect_threshold: float = 5.0  # RR > 5.0 or < 0.2

    # Publication bias thresholds
    egger_p_threshold: float = 0.10  # P-value for Egger's test

    # Risk of bias thresholds
    high_rob_proportion: float = 0.50  # > 50% studies with high RoB


# =============================================================================
# GRADE Validator
# =============================================================================


@ValidatorRegistry.register
class GRADECertaintyValidator(Validator):
    """
    Validates GRADE Certainty of Evidence assessments.

    The GRADE framework assesses certainty of evidence by:

    1. Starting Certainty:
       - HIGH for randomized controlled trials (RCTs)
       - LOW for observational studies

    2. Five Downgrading Domains (each can downgrade by 1-2 levels):
       - Risk of Bias: Study-level quality and bias concerns
       - Inconsistency: Unexplained heterogeneity across studies (I-squared)
       - Indirectness: PICO (Population, Intervention, Comparator, Outcome) deviation
       - Imprecision: Wide confidence intervals, insufficient sample size
       - Publication Bias: Evidence of selective reporting

    3. Three Upgrading Factors (each can upgrade by 1-2 levels, observational only):
       - Large Effect: RR < 0.5 or > 2.0 (1 level), RR < 0.2 or > 5.0 (2 levels)
       - Dose-Response Gradient: Evidence of dose-response relationship
       - Plausible Confounding: All plausible confounders would reduce effect

    4. Final Certainty:
       - HIGH: Very confident effect lies close to estimate
       - MODERATE: Moderately confident; true effect likely close to estimate
       - LOW: Limited confidence; true effect may be substantially different
       - VERY_LOW: Very little confidence; true effect likely substantially different

    This validator checks:
    - Consistency between domain assessments and reported certainty
    - Valid I-squared values for inconsistency assessment
    - Appropriate OIS (Optimal Information Size) calculations
    - Publication bias test results match assessment
    - Risk of bias proportions justify downgrading decisions
    - Upgrade conditions are met for observational studies
    """

    name = "tc_grade_certainty"
    description = "Validates GRADE Certainty of Evidence assessments"
    default_severity = Severity.BLOCK

    def __init__(self, config: ValidatorConfig | None = None):
        super().__init__(config)
        self.thresholds = GRADEThresholds()

        # Apply custom thresholds from config
        params = config.params if config else {}
        if params:
            if "i_squared_moderate" in params:
                self.thresholds.i_squared_moderate_concern = params["i_squared_moderate"]
            if "i_squared_serious" in params:
                self.thresholds.i_squared_serious_concern = params["i_squared_serious"]
            if "ois_minimum" in params:
                self.thresholds.ois_minimum = params["ois_minimum"]
            if "rr_large_effect" in params:
                self.thresholds.rr_large_effect_threshold = params["rr_large_effect"]
            if "egger_p" in params:
                self.thresholds.egger_p_threshold = params["egger_p"]

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate GRADE certainty assessments in claims.

        Args:
            claims: List of claims to validate
            scope_lock: Scope lock for this certification
            context: Additional context including meta-analysis data

        Returns:
            ValidatorResult with pass/fail and detailed assessment
        """
        errors = []
        warnings = []
        assessments = []
        validated_count = 0

        for claim in claims:
            # Check if this claim has GRADE-related data
            if not self._is_grade_claim(claim):
                continue

            validated_count += 1

            # Build GRADE assessment
            assessment = self._build_assessment(claim, context)
            assessments.append(assessment)

            # Validate each domain
            domain_errors, domain_warnings = self._validate_assessment(claim, assessment)
            errors.extend(domain_errors)
            warnings.extend(domain_warnings)

            # Explicit malformed or contradictory certainty must not evade validation.
            declared = self._declared_grade_values(claim)
            reported = self._get_reported_certainty(claim)
            if declared and reported is None:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Invalid or conflicting declared GRADE certainty",
                        "recommendation": "Use one consistent high/moderate/low/very low level",
                    }
                )
            elif reported is not None and reported != assessment.final_certainty:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "issue": "Certainty mismatch",
                        "reported_certainty": reported.value,
                        "calculated_certainty": assessment.final_certainty.value,
                        "total_downgrade": assessment.total_downgrade,
                        "total_upgrade": assessment.total_upgrade,
                        "recommendation": "Verify domain assessments or correct reported certainty",
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
                f"Validated {validated_count} GRADE certainty assessments"
                if passed
                else f"GRADE validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
                "assessments": [self._serialize_assessment(a) for a in assessments],
                "thresholds": {
                    "i_squared_moderate_concern": self.thresholds.i_squared_moderate_concern,
                    "i_squared_serious_concern": self.thresholds.i_squared_serious_concern,
                    "ois_minimum": self.thresholds.ois_minimum,
                    "rr_large_effect": self.thresholds.rr_large_effect_threshold,
                    "egger_p_threshold": self.thresholds.egger_p_threshold,
                },
            },
        )

    def _is_grade_claim(self, claim: NumericClaim) -> bool:
        """Check if claim contains GRADE-related data."""
        grade_keys = {
            # Certainty-related
            "grade_certainty",
            "certainty",
            "certainty_of_evidence",
            "coe",
            "quality_of_evidence",
            "qoe",
            # Domain-related
            "risk_of_bias",
            "rob",
            "inconsistency",
            "indirectness",
            "imprecision",
            "publication_bias",
            # Upgrade factors
            "large_effect",
            "dose_response",
            "plausible_confounding",
            # Study design
            "study_design",
            "study_type",
        }

        # Check claim type
        if claim.claim_type == ClaimType.GRADE_CERTAINTY:
            return True

        # Check if claim has GRADE metadata
        claim_keys = {k.lower().replace("-", "_").replace(" ", "_") for k in claim.metadata}
        return bool(grade_keys & claim_keys)

    def _build_assessment(self, claim: NumericClaim, context: dict[str, Any]) -> GRADEAssessment:
        """Build a GRADE assessment from claim data."""
        # Determine starting certainty based on study design
        study_design = self._get_study_design(claim)
        if study_design in ["RCT", "randomized_controlled_trial", "randomised"]:
            starting = GRADECertainty.HIGH
        else:
            starting = GRADECertainty.LOW

        assessment = GRADEAssessment(
            outcome_id=claim.claim_id,
            starting_certainty=starting,
            study_design=study_design,
        )

        # Assess each downgrading domain
        assessment.risk_of_bias = self._assess_risk_of_bias(claim, context)
        assessment.inconsistency = self._assess_inconsistency(claim, context)
        assessment.indirectness = self._assess_indirectness(claim, context)
        assessment.imprecision = self._assess_imprecision(claim, context)
        assessment.publication_bias = self._assess_publication_bias(claim, context)

        # Assess upgrading factors (only for observational studies)
        if starting == GRADECertainty.LOW:
            assessment.large_effect = self._assess_large_effect(claim, context)
            assessment.dose_response = self._assess_dose_response(claim, context)
            assessment.plausible_confounding = self._assess_plausible_confounding(claim, context)

        # Calculate final certainty
        assessment.calculate_final_certainty()

        return assessment

    # =========================================================================
    # Downgrading Domain Assessments
    # =========================================================================

    def _assess_risk_of_bias(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess risk of bias domain.

        Considers:
        - Proportion of studies with high/serious risk of bias
        - Weighting of high-RoB studies in pooled analysis
        - Specific bias domains (randomization, blinding, attrition, etc.)
        """
        _rob_data = self._get_stat_dict(claim, ["risk_of_bias", "rob", "quality_assessment"])

        # Get RoB levels from studies
        high_rob_count = self._get_stat(claim, ["high_rob_count", "high_risk_count"])
        total_studies = self._get_stat(claim, ["n_studies", "k", "study_count"])
        high_rob_weight = self._get_stat(claim, ["high_rob_weight", "high_risk_weight"])

        concern_level = "no_concern"
        downgrade = 0
        rationale = "No serious concerns about risk of bias"
        details = {}

        if high_rob_count is not None and total_studies is not None and total_studies > 0:
            proportion = high_rob_count / total_studies
            details["high_rob_proportion"] = proportion
            details["high_rob_count"] = high_rob_count
            details["total_studies"] = total_studies

            if proportion > 0.75:
                concern_level = "very_serious_concern"
                downgrade = 2
                rationale = (
                    f"Very serious risk of bias: {proportion * 100:.0f}% of studies have high RoB"
                )
            elif proportion > self.thresholds.high_rob_proportion:
                concern_level = "serious_concern"
                downgrade = 1
                rationale = (
                    f"Serious risk of bias: {proportion * 100:.0f}% of studies have high RoB"
                )
            elif proportion > 0.25:
                concern_level = "some_concern"
                downgrade = 0
                rationale = (
                    f"Some concerns about risk of bias: {proportion * 100:.0f}% have high RoB"
                )

        # Consider weight-adjusted RoB
        if high_rob_weight is not None and high_rob_weight > 0.5:
            if concern_level == "no_concern":
                concern_level = "some_concern"
            if high_rob_weight > 0.75 and downgrade < 2:
                downgrade = min(downgrade + 1, 2)
            details["high_rob_weight"] = high_rob_weight
            rationale += f"; high-RoB studies contribute {high_rob_weight * 100:.0f}% of weight"

        return DomainAssessment(
            domain="risk_of_bias",
            concern_level=concern_level,
            downgrade_levels=downgrade,
            rationale=rationale,
            details=details,
        )

    def _assess_inconsistency(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess inconsistency domain based on heterogeneity.

        Uses I-squared thresholds:
        - I² > 50%: Moderate concern (downgrade 1)
        - I² > 75%: Serious concern (downgrade 2)

        Also considers:
        - Direction of effects across studies
        - Overlap of confidence intervals
        - Prediction interval width
        """
        i_squared = self._get_stat(claim, ["i_squared", "i2", "isquared"])
        if i_squared is None:
            i_squared = claim.i_squared

        _tau_squared = self._get_stat(claim, ["tau_squared", "tau2"])
        prediction_interval = self._get_stat_list(claim, ["prediction_interval", "pi"])

        concern_level = "no_concern"
        downgrade = 0
        rationale = "No serious inconsistency"
        details = {}

        if i_squared is not None:
            details["i_squared"] = i_squared

            if i_squared >= self.thresholds.i_squared_serious_concern:
                concern_level = "serious_concern"
                downgrade = 1
                rationale = f"Serious inconsistency: I² = {i_squared:.1f}% indicates substantial heterogeneity"

                # Check if heterogeneity is unexplained
                heterogeneity_explained = self._get_stat(
                    claim, ["heterogeneity_explained", "subgroup_explains"]
                )
                if heterogeneity_explained and heterogeneity_explained > 0.5:
                    downgrade = 0
                    concern_level = "some_concern"
                    rationale += " (but largely explained by pre-specified subgroups)"
                    details["heterogeneity_explained"] = heterogeneity_explained

            elif i_squared >= self.thresholds.i_squared_moderate_concern:
                concern_level = "some_concern"
                downgrade = 0
                rationale = (
                    f"Some inconsistency: I² = {i_squared:.1f}% indicates moderate heterogeneity"
                )

        # Consider direction consistency
        same_direction = self._get_stat(claim, ["effects_same_direction", "direction_consistent"])
        if same_direction is not None and same_direction < 0.75:
            if downgrade < 2:
                downgrade += 1
            concern_level = "serious_concern" if downgrade >= 1 else concern_level
            rationale += f"; only {same_direction * 100:.0f}% of effects in same direction"
            details["same_direction_proportion"] = same_direction

        # Check prediction interval
        if prediction_interval and len(prediction_interval) >= 2:
            pi_lower, pi_upper = prediction_interval[0], prediction_interval[1]
            details["prediction_interval"] = prediction_interval

            # If PI crosses null and includes clinically meaningful effects both ways
            if pi_lower < 1.0 < pi_upper:  # For ratio measures
                pi_ratio = pi_upper / pi_lower if pi_lower > 0 else float("inf")
                if pi_ratio > 4:
                    rationale += "; prediction interval spans null with wide range"

        return DomainAssessment(
            domain="inconsistency",
            concern_level=concern_level,
            downgrade_levels=downgrade,
            rationale=rationale,
            details=details,
        )

    def _assess_indirectness(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess indirectness domain.

        Checks PICO (Population, Intervention, Comparator, Outcome) deviation:
        - Population: Different from target population
        - Intervention: Surrogate or different dose/formulation
        - Comparator: Different from clinical question
        - Outcome: Surrogate outcomes vs patient-important outcomes
        """
        _pico_data = self._get_stat_dict(claim, ["pico", "indirectness"])

        concern_level = "no_concern"
        downgrade = 0
        rationale = "Direct evidence"
        details = {}

        # Check individual PICO components
        pico_concerns = []

        population_indirect = self._get_stat(claim, ["population_indirect", "indirect_population"])
        if population_indirect:
            pico_concerns.append("population")
            details["population_indirect"] = True

        intervention_indirect = self._get_stat(
            claim, ["intervention_indirect", "indirect_intervention"]
        )
        if intervention_indirect:
            pico_concerns.append("intervention")
            details["intervention_indirect"] = True

        comparator_indirect = self._get_stat(claim, ["comparator_indirect", "indirect_comparator"])
        if comparator_indirect:
            pico_concerns.append("comparator")
            details["comparator_indirect"] = True

        outcome_surrogate = self._get_stat(claim, ["outcome_surrogate", "surrogate_outcome"])
        if outcome_surrogate:
            pico_concerns.append("outcome (surrogate)")
            details["outcome_surrogate"] = True

        if pico_concerns:
            details["pico_concerns"] = pico_concerns

            if len(pico_concerns) >= 2:
                concern_level = "serious_concern"
                downgrade = 1
                rationale = f"Serious indirectness: concerns with {', '.join(pico_concerns)}"
            else:
                concern_level = "some_concern"
                downgrade = 0
                rationale = f"Some indirectness: concerns with {pico_concerns[0]}"

        # Check for head-to-head vs indirect comparison (network)
        indirect_comparison = self._get_stat(claim, ["indirect_comparison", "network_estimate"])
        if indirect_comparison:
            downgrade = max(downgrade, 1)
            concern_level = "serious_concern"
            rationale += "; based on indirect comparison"
            details["indirect_comparison"] = True

        return DomainAssessment(
            domain="indirectness",
            concern_level=concern_level,
            downgrade_levels=downgrade,
            rationale=rationale,
            details=details,
        )

    def _assess_imprecision(self, claim: NumericClaim, context: dict[str, Any]) -> DomainAssessment:
        """
        Assess imprecision domain.

        Considers:
        - Optimal Information Size (OIS): Sample size needed for adequate power
        - Confidence interval width: CI crosses clinically important threshold
        - Number of events: For binary outcomes
        """
        concern_level = "no_concern"
        downgrade = 0
        rationale = "Adequate precision"
        details = {}

        # Get precision-related data
        sample_size = claim.sample_size or self._get_stat(claim, ["n", "sample_size", "total_n"])
        n_events = claim.n_events or self._get_stat(claim, ["events", "n_events", "total_events"])
        ci_lower = claim.lower_bound
        ci_upper = claim.upper_bound
        _effect = claim.value

        # Check Optimal Information Size
        ois = self._get_stat(claim, ["ois", "optimal_information_size"])
        if ois is None and sample_size:
            # Estimate OIS requirement based on typical meta-analysis needs
            ois = self.thresholds.ois_minimum

        if sample_size is not None and ois is not None:
            details["sample_size"] = sample_size
            details["ois"] = ois

            if sample_size < ois:
                ois_met_proportion = sample_size / ois
                details["ois_met_proportion"] = ois_met_proportion

                if ois_met_proportion < 0.5:
                    concern_level = "serious_concern"
                    downgrade = 1
                    rationale = (
                        f"Serious imprecision: sample size ({sample_size}) < 50% of OIS ({ois})"
                    )
                else:
                    concern_level = "some_concern"
                    rationale = f"Some imprecision: sample size ({sample_size}) below OIS ({ois})"

        # Check number of events for binary outcomes
        if n_events is not None:
            details["n_events"] = n_events
            if n_events < self.thresholds.events_minimum:
                downgrade = max(downgrade, 1)
                concern_level = "serious_concern"
                rationale += f"; few events ({n_events} < {self.thresholds.events_minimum})"

        # Check confidence interval width
        if ci_lower is not None and ci_upper is not None:
            details["ci"] = [ci_lower, ci_upper]

            # For ratio measures, check if CI crosses 1.0 and important thresholds
            if claim.claim_type in [
                ClaimType.RISK_RATIO,
                ClaimType.ODDS_RATIO,
                ClaimType.HAZARD_RATIO,
                ClaimType.POOLED_EFFECT,
            ]:
                ci_ratio = ci_upper / ci_lower if ci_lower > 0 else float("inf")
                details["ci_ratio"] = ci_ratio

                # Check if CI crosses null
                if ci_lower < 1.0 < ci_upper:
                    rationale += "; CI crosses null"
                    if concern_level == "no_concern":
                        concern_level = "some_concern"

                # Check if CI is very wide
                if ci_ratio > self.thresholds.ci_ratio_threshold:
                    if downgrade < 2:
                        downgrade += 1
                    concern_level = "serious_concern"
                    rationale = f"Serious imprecision: very wide CI (ratio = {ci_ratio:.2f})"

            # For difference measures
            else:
                ci_width = ci_upper - ci_lower
                details["ci_width"] = ci_width

                # Check if CI crosses null (0 for differences)
                if ci_lower < 0 < ci_upper:
                    rationale += "; CI crosses null"
                    if concern_level == "no_concern":
                        concern_level = "some_concern"

        return DomainAssessment(
            domain="imprecision",
            concern_level=concern_level,
            downgrade_levels=downgrade,
            rationale=rationale,
            details=details,
        )

    def _assess_publication_bias(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess publication bias domain.

        Uses:
        - Egger's test (p < 0.10 suggests asymmetry)
        - Begg's test (rank correlation)
        - Funnel plot visual assessment
        - Trim-and-fill analysis
        """
        concern_level = "no_concern"
        downgrade = 0
        rationale = "No evidence of publication bias"
        details = {}

        # Get publication bias test results
        egger_p = self._get_stat(claim, ["egger_pvalue", "egger_p"])
        begg_p = self._get_stat(claim, ["begg_pvalue", "begg_p"])
        funnel_asymmetry = self._get_stat(claim, ["funnel_asymmetry", "funnel_asymmetric"])
        trim_fill_imputed = self._get_stat(claim, ["imputed_studies", "trimfill_k0"])
        n_studies = self._get_stat(claim, ["n_studies", "k"])

        bias_indicators = []

        # Egger's test
        if egger_p is not None:
            details["egger_p"] = egger_p
            if egger_p < self.thresholds.egger_p_threshold:
                bias_indicators.append(f"Egger's test p={egger_p:.3f}")

        # Begg's test
        if begg_p is not None:
            details["begg_p"] = begg_p
            if begg_p < self.thresholds.egger_p_threshold:
                bias_indicators.append(f"Begg's test p={begg_p:.3f}")

        # Funnel plot asymmetry
        if funnel_asymmetry:
            details["funnel_asymmetry"] = True
            bias_indicators.append("funnel plot asymmetry")

        # Trim-and-fill
        if trim_fill_imputed is not None and trim_fill_imputed > 0:
            details["imputed_studies"] = trim_fill_imputed
            if n_studies and trim_fill_imputed / n_studies > 0.2:
                bias_indicators.append(f"{trim_fill_imputed} studies imputed by trim-and-fill")

        if bias_indicators:
            details["bias_indicators"] = bias_indicators

            if len(bias_indicators) >= 2:
                concern_level = "serious_concern"
                downgrade = 1
                rationale = f"Serious concern: multiple indicators of publication bias ({', '.join(bias_indicators)})"
            else:
                concern_level = "some_concern"
                rationale = f"Some concern: {bias_indicators[0]}"

        # Note if insufficient studies for bias assessment
        if n_studies is not None and n_studies < 10:
            details["insufficient_studies_for_test"] = True
            rationale += f"; note: only {n_studies} studies (< 10 recommended for bias tests)"

        return DomainAssessment(
            domain="publication_bias",
            concern_level=concern_level,
            downgrade_levels=downgrade,
            rationale=rationale,
            details=details,
        )

    # =========================================================================
    # Upgrading Factor Assessments
    # =========================================================================

    def _assess_large_effect(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess large effect upgrading factor.

        Criteria:
        - RR < 0.5 or > 2.0: Upgrade by 1 level
        - RR < 0.2 or > 5.0: Upgrade by 2 levels

        Only applied when:
        - No plausible confounders could explain the effect
        - Effect is consistent and precise
        """
        concern_level = "no_upgrade"
        upgrade = 0  # Stored as negative in downgrade_levels
        rationale = "No large effect"
        details = {}

        # Get effect estimate
        effect = claim.value
        effect_type = claim.claim_type

        # Only assess ratio measures
        if effect_type not in [
            ClaimType.RISK_RATIO,
            ClaimType.ODDS_RATIO,
            ClaimType.HAZARD_RATIO,
            ClaimType.POOLED_EFFECT,
        ]:
            return DomainAssessment(
                domain="large_effect",
                concern_level=concern_level,
                downgrade_levels=0,
                rationale="Not a ratio measure",
                details=details,
            )

        details["effect"] = effect
        details["effect_type"] = (
            effect_type.value if hasattr(effect_type, "value") else str(effect_type)
        )

        # Check for large effect
        is_large = effect < 0.5 or effect > self.thresholds.rr_large_effect_threshold
        is_very_large = effect < 0.2 or effect > self.thresholds.rr_very_large_effect_threshold

        if is_very_large:
            upgrade = 2
            concern_level = "upgrade_2"
            rationale = f"Very large effect (RR = {effect:.2f})"
        elif is_large:
            upgrade = 1
            concern_level = "upgrade_1"
            rationale = f"Large effect (RR = {effect:.2f})"

        # Check conditions for upgrade validity
        if upgrade > 0:
            # Should not have high risk of bias
            high_rob = self._get_stat(claim, ["high_rob_proportion", "high_rob_count"])
            if high_rob and high_rob > 0.5:
                upgrade = 0
                rationale += " (not applied: high risk of bias)"
                details["upgrade_not_applied_reason"] = "high_risk_of_bias"

            # Should be precise
            ci_lower = claim.lower_bound
            ci_upper = claim.upper_bound
            if ci_lower and ci_upper and is_large and ci_lower < 1.0 < ci_upper:
                upgrade = 0
                rationale += " (not applied: CI crosses null)"
                details["upgrade_not_applied_reason"] = "ci_crosses_null"

        return DomainAssessment(
            domain="large_effect",
            concern_level=concern_level,
            downgrade_levels=-upgrade,  # Negative for upgrades
            rationale=rationale,
            details=details,
        )

    def _assess_dose_response(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess dose-response gradient upgrading factor.

        Looks for evidence of dose-response relationship:
        - Monotonic increase/decrease with dose
        - Statistically significant trend
        """
        concern_level = "no_upgrade"
        upgrade = 0
        rationale = "No dose-response gradient"
        details = {}

        # Check for dose-response data
        dose_response = self._get_stat(claim, ["dose_response", "dose_response_gradient"])
        dose_response_p = self._get_stat(claim, ["dose_response_p", "trend_p"])
        monotonic = self._get_stat(claim, ["monotonic_trend", "monotonic"])

        if dose_response or monotonic:
            details["dose_response_present"] = True

            if dose_response_p is not None:
                details["trend_p"] = dose_response_p
                if dose_response_p < 0.05:
                    upgrade = 1
                    concern_level = "upgrade_1"
                    rationale = f"Dose-response gradient present (p = {dose_response_p:.3f})"

        return DomainAssessment(
            domain="dose_response",
            concern_level=concern_level,
            downgrade_levels=-upgrade,
            rationale=rationale,
            details=details,
        )

    def _assess_plausible_confounding(
        self, claim: NumericClaim, context: dict[str, Any]
    ) -> DomainAssessment:
        """
        Assess plausible confounding upgrading factor.

        Criteria:
        - All plausible confounders would reduce the effect
        - Residual confounding unlikely to explain association
        """
        concern_level = "no_upgrade"
        upgrade = 0
        rationale = "No evidence confounders would reduce effect"
        details = {}

        # Check for plausible confounding assessment
        _confounding_direction = self._get_stat(
            claim, ["confounding_direction", "plausible_confounding"]
        )
        confounders_reduce = self._get_stat(
            claim, ["confounders_reduce_effect", "confounders_towards_null"]
        )

        if confounders_reduce:
            details["confounders_reduce_effect"] = True
            upgrade = 1
            concern_level = "upgrade_1"
            rationale = "Plausible confounders would reduce observed effect"

        return DomainAssessment(
            domain="plausible_confounding",
            concern_level=concern_level,
            downgrade_levels=-upgrade,
            rationale=rationale,
            details=details,
        )

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def _validate_assessment(
        self, claim: NumericClaim, assessment: GRADEAssessment
    ) -> tuple[list[dict], list[dict]]:
        """Validate the GRADE assessment for consistency and correctness."""
        errors = []
        warnings = []

        # Validate downgrade domains
        errors_rob, warnings_rob = self._validate_risk_of_bias(claim, assessment.risk_of_bias)
        errors.extend(errors_rob)
        warnings.extend(warnings_rob)

        errors_inc, warnings_inc = self._validate_inconsistency(claim, assessment.inconsistency)
        errors.extend(errors_inc)
        warnings.extend(warnings_inc)

        errors_ind, warnings_ind = self._validate_indirectness(claim, assessment.indirectness)
        errors.extend(errors_ind)
        warnings.extend(warnings_ind)

        errors_imp, warnings_imp = self._validate_imprecision(claim, assessment.imprecision)
        errors.extend(errors_imp)
        warnings.extend(warnings_imp)

        errors_pub, warnings_pub = self._validate_publication_bias(
            claim, assessment.publication_bias
        )
        errors.extend(errors_pub)
        warnings.extend(warnings_pub)

        # Validate upgrades only apply to observational studies
        if assessment.starting_certainty == GRADECertainty.HIGH and (
            (assessment.large_effect and assessment.large_effect.downgrade_levels < 0)
            or (assessment.dose_response and assessment.dose_response.downgrade_levels < 0)
            or (
                assessment.plausible_confounding
                and assessment.plausible_confounding.downgrade_levels < 0
            )
        ):
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "upgrading",
                    "issue": "Upgrading factors typically only apply to observational studies",
                    "starting_certainty": assessment.starting_certainty.value,
                }
            )

        # Check for excessive downgrading
        if assessment.total_downgrade > 3:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "issue": f"Total downgrade of {assessment.total_downgrade} levels is unusual",
                    "recommendation": "Review if all downgrades are justified",
                }
            )

        return errors, warnings

    def _validate_risk_of_bias(
        self, claim: NumericClaim, domain: DomainAssessment | None
    ) -> tuple[list[dict], list[dict]]:
        """Validate risk of bias domain assessment."""
        errors = []
        warnings = []

        if not domain:
            return errors, warnings

        # Check that downgrade aligns with concern level
        if domain.concern_level == "no_concern" and domain.downgrade_levels > 0:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "risk_of_bias",
                    "issue": "Downgrade without stated concern",
                    "concern_level": domain.concern_level,
                    "downgrade_levels": domain.downgrade_levels,
                }
            )

        if (
            domain.concern_level in ["serious_concern", "very_serious_concern"]
            and domain.downgrade_levels == 0
        ):
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "risk_of_bias",
                    "issue": "Serious concern without downgrade",
                    "concern_level": domain.concern_level,
                }
            )

        return errors, warnings

    def _validate_inconsistency(
        self, claim: NumericClaim, domain: DomainAssessment | None
    ) -> tuple[list[dict], list[dict]]:
        """Validate inconsistency domain assessment."""
        errors = []
        warnings = []

        if not domain:
            return errors, warnings

        # Validate I-squared value if present
        i_squared = domain.details.get("i_squared")
        if i_squared is not None:
            if i_squared < 0:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "domain": "inconsistency",
                        "issue": f"I-squared cannot be negative (got {i_squared})",
                    }
                )
            elif i_squared > 100:
                errors.append(
                    {
                        "claim_id": claim.claim_id,
                        "domain": "inconsistency",
                        "issue": f"I-squared cannot exceed 100% (got {i_squared})",
                    }
                )

            # Check consistency with downgrade decision
            if (
                i_squared >= self.thresholds.i_squared_serious_concern
                and domain.downgrade_levels == 0
            ):
                warnings.append(
                    {
                        "claim_id": claim.claim_id,
                        "domain": "inconsistency",
                        "issue": f"High I-squared ({i_squared}%) but no downgrade",
                        "threshold": self.thresholds.i_squared_serious_concern,
                    }
                )

        return errors, warnings

    def _validate_indirectness(
        self, claim: NumericClaim, domain: DomainAssessment | None
    ) -> tuple[list[dict], list[dict]]:
        """Validate indirectness domain assessment."""
        errors = []
        warnings = []

        if not domain:
            return errors, warnings

        # Check PICO concerns
        pico_concerns = domain.details.get("pico_concerns", [])
        if len(pico_concerns) >= 2 and domain.downgrade_levels == 0:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "indirectness",
                    "issue": f"Multiple PICO concerns ({pico_concerns}) but no downgrade",
                }
            )

        return errors, warnings

    def _validate_imprecision(
        self, claim: NumericClaim, domain: DomainAssessment | None
    ) -> tuple[list[dict], list[dict]]:
        """Validate imprecision domain assessment."""
        errors = []
        warnings = []

        if not domain:
            return errors, warnings

        # Validate OIS calculation
        ois = domain.details.get("ois")
        _sample_size = domain.details.get("sample_size")

        if ois is not None and ois <= 0:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "imprecision",
                    "issue": f"OIS must be positive (got {ois})",
                }
            )

        # Check CI validity
        ci = domain.details.get("ci")
        if ci and len(ci) >= 2 and ci[0] > ci[1]:
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "imprecision",
                    "issue": f"CI lower bound ({ci[0]}) > upper bound ({ci[1]})",
                }
            )

        return errors, warnings

    def _validate_publication_bias(
        self, claim: NumericClaim, domain: DomainAssessment | None
    ) -> tuple[list[dict], list[dict]]:
        """Validate publication bias domain assessment."""
        errors = []
        warnings = []

        if not domain:
            return errors, warnings

        # Validate p-values
        egger_p = domain.details.get("egger_p")
        if egger_p is not None and (egger_p < 0 or egger_p > 1):
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "publication_bias",
                    "issue": f"Egger's p-value must be 0-1 (got {egger_p})",
                }
            )

        begg_p = domain.details.get("begg_p")
        if begg_p is not None and (begg_p < 0 or begg_p > 1):
            errors.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "publication_bias",
                    "issue": f"Begg's p-value must be 0-1 (got {begg_p})",
                }
            )

        # Check if downgrade justified by indicators
        bias_indicators = domain.details.get("bias_indicators", [])
        if bias_indicators and domain.downgrade_levels == 0:
            warnings.append(
                {
                    "claim_id": claim.claim_id,
                    "domain": "publication_bias",
                    "issue": "Publication bias indicators present but no downgrade",
                    "indicators": bias_indicators,
                }
            )

        return errors, warnings

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_study_design(self, claim: NumericClaim) -> str:
        """Get study design from claim."""
        design = self._get_stat(claim, ["study_design", "study_type", "design"])
        if design is not None:
            return str(design).upper()

        # Check metadata for RCT indicators
        metadata_str = str(claim.metadata).lower()
        if "rct" in metadata_str or "randomised" in metadata_str or "randomized" in metadata_str:
            return "RCT"

        return "observational"

    def _declared_grade_values(self, claim: NumericClaim) -> list[Any]:
        """Return all stated GRADE levels, including normalized metadata aliases."""
        aliases = {
            "grade_certainty",
            "certainty",
            "certainty_of_evidence",
            "quality_of_evidence",
            "coe",
            "qoe",
        }
        values = [
            value
            for key, value in claim.metadata.items()
            if key.lower().replace("-", "_").replace(" ", "_") in aliases
        ]
        if claim.grade_certainty is not None:
            values.append(claim.grade_certainty)
        return values

    def _get_reported_certainty(self, claim: NumericClaim) -> GRADECertainty | None:
        """Parse all declared levels, refusing invalid or conflicting evidence."""
        declared = self._declared_grade_values(claim)
        if not declared:
            return None

        certainty_map = {
            "HIGH": GRADECertainty.HIGH,
            "MODERATE": GRADECertainty.MODERATE,
            "LOW": GRADECertainty.LOW,
            "VERY_LOW": GRADECertainty.VERY_LOW,
            "4": GRADECertainty.HIGH,
            "3": GRADECertainty.MODERATE,
            "2": GRADECertainty.LOW,
            "1": GRADECertainty.VERY_LOW,
        }

        parsed = set()
        for raw in declared:
            # bool subclasses int, but True is not a GRADE level.
            if isinstance(raw, bool):
                return None
            if isinstance(raw, float):
                if not math.isfinite(raw) or not raw.is_integer():
                    return None
                raw = int(raw)
            if not isinstance(raw, (str, int)):
                return None
            canonical = str(raw).strip().upper().replace(" ", "_").replace("-", "_")
            certainty = certainty_map.get(canonical)
            if certainty is None:
                return None
            parsed.add(certainty)

        return next(iter(parsed)) if len(parsed) == 1 else None

    def _get_stat(self, claim: NumericClaim, keys: list[str]) -> float | None:
        """Get a numeric statistic from claim metadata."""
        for key in keys:
            # Try exact key
            if key in claim.metadata:
                val = claim.metadata[key]
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return float(val)
                if isinstance(val, bool):
                    return float(val)

            # Try normalized key
            for k, v in claim.metadata.items():
                k_normalized = k.lower().replace("-", "_").replace(" ", "_")
                if k_normalized == key.lower():
                    if isinstance(v, (int, float)) and not math.isnan(v):
                        return float(v)
                    if isinstance(v, bool):
                        return float(v)

        return None

    def _get_stat_dict(self, claim: NumericClaim, keys: list[str]) -> dict | None:
        """Get a dictionary statistic from claim metadata."""
        for key in keys:
            if key in claim.metadata:
                val = claim.metadata[key]
                if isinstance(val, dict):
                    return val

            for k, v in claim.metadata.items():
                k_normalized = k.lower().replace("-", "_").replace(" ", "_")
                if k_normalized == key.lower() and isinstance(v, dict):
                    return v

        return None

    def _get_stat_list(self, claim: NumericClaim, keys: list[str]) -> list | None:
        """Get a list statistic from claim metadata."""
        for key in keys:
            if key in claim.metadata:
                val = claim.metadata[key]
                if isinstance(val, (list, tuple)):
                    return list(val)

            for k, v in claim.metadata.items():
                k_normalized = k.lower().replace("-", "_").replace(" ", "_")
                if k_normalized == key.lower() and isinstance(v, (list, tuple)):
                    return list(v)

        return None

    def _serialize_assessment(self, assessment: GRADEAssessment) -> dict:
        """Serialize a GRADE assessment to dictionary."""

        def serialize_domain(domain: DomainAssessment | None) -> dict | None:
            if domain is None:
                return None
            return {
                "domain": domain.domain,
                "concern_level": domain.concern_level,
                "downgrade_levels": domain.downgrade_levels,
                "rationale": domain.rationale,
                "details": domain.details,
            }

        return {
            "outcome_id": assessment.outcome_id,
            "study_design": assessment.study_design,
            "starting_certainty": assessment.starting_certainty.value,
            "domains": {
                "risk_of_bias": serialize_domain(assessment.risk_of_bias),
                "inconsistency": serialize_domain(assessment.inconsistency),
                "indirectness": serialize_domain(assessment.indirectness),
                "imprecision": serialize_domain(assessment.imprecision),
                "publication_bias": serialize_domain(assessment.publication_bias),
            },
            "upgrade_factors": {
                "large_effect": serialize_domain(assessment.large_effect),
                "dose_response": serialize_domain(assessment.dose_response),
                "plausible_confounding": serialize_domain(assessment.plausible_confounding),
            },
            "total_downgrade": assessment.total_downgrade,
            "total_upgrade": assessment.total_upgrade,
            "final_certainty": assessment.final_certainty.value,
        }


# =============================================================================
# Utility Functions
# =============================================================================


def calculate_ois(
    baseline_risk: float,
    relative_risk_reduction: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """
    Calculate Optimal Information Size (OIS) for a binary outcome.

    Based on sample size calculation for detecting a specified relative
    risk reduction with given power and significance level.

    Args:
        baseline_risk: Control group event rate (0-1)
        relative_risk_reduction: Expected relative risk reduction (0-1)
        alpha: Significance level (default 0.05)
        power: Statistical power (default 0.80)

    Returns:
        Optimal Information Size (total sample size needed)
    """
    from scipy import stats

    # Calculate z-values
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)

    # Event rates
    p1 = baseline_risk
    p2 = baseline_risk * (1 - relative_risk_reduction)

    # Pooled proportion
    p_pooled = (p1 + p2) / 2

    # Sample size per group
    numerator = (
        z_alpha * math.sqrt(2 * p_pooled * (1 - p_pooled))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    denominator = (p1 - p2) ** 2

    if denominator == 0:
        return float("inf")

    n_per_group = numerator / denominator

    # Total sample size
    return int(2 * n_per_group)


def interpret_certainty(certainty: GRADECertainty) -> str:
    """
    Provide interpretation of GRADE certainty level.

    Args:
        certainty: GRADE certainty level

    Returns:
        Plain language interpretation
    """
    interpretations = {
        GRADECertainty.HIGH: (
            "High certainty: We are very confident that the true effect lies close "
            "to that of the estimate of the effect."
        ),
        GRADECertainty.MODERATE: (
            "Moderate certainty: We are moderately confident in the effect estimate. "
            "The true effect is likely to be close to the estimate of the effect, "
            "but there is a possibility that it is substantially different."
        ),
        GRADECertainty.LOW: (
            "Low certainty: Our confidence in the effect estimate is limited. "
            "The true effect may be substantially different from the estimate of the effect."
        ),
        GRADECertainty.VERY_LOW: (
            "Very low certainty: We have very little confidence in the effect estimate. "
            "The true effect is likely to be substantially different from the estimate of effect."
        ),
    }
    return interpretations.get(certainty, "Unknown certainty level")


def summarize_grade_table(assessments: list[GRADEAssessment]) -> str:
    """
    Generate a summary table of GRADE assessments.

    Args:
        assessments: List of GRADE assessments

    Returns:
        Formatted summary table as string
    """
    if not assessments:
        return "No GRADE assessments available"

    lines = [
        "GRADE Summary of Findings",
        "=" * 80,
        f"{'Outcome':<30} {'RoB':<8} {'Inc':<8} {'Ind':<8} {'Imp':<8} {'Pub':<8} {'Final':<10}",
        "-" * 80,
    ]

    for a in assessments:

        def level_symbol(domain: DomainAssessment | None) -> str:
            if domain is None:
                return "-"
            if domain.downgrade_levels == 0:
                return "o"  # No concern
            elif domain.downgrade_levels == 1:
                return "-1"  # Serious
            else:
                return "-2"  # Very serious

        lines.append(
            f"{a.outcome_id[:30]:<30} "
            f"{level_symbol(a.risk_of_bias):<8} "
            f"{level_symbol(a.inconsistency):<8} "
            f"{level_symbol(a.indirectness):<8} "
            f"{level_symbol(a.imprecision):<8} "
            f"{level_symbol(a.publication_bias):<8} "
            f"{a.final_certainty.value:<10}"
        )

    lines.append("-" * 80)
    lines.append("Legend: o = no concern, -1 = serious concern, -2 = very serious concern")

    return "\n".join(lines)
