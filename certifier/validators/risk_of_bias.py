"""
Risk of Bias Assessment Validators.

Implements standard risk of bias assessment tools for systematic reviews:

1. ROB2Validator - Cochrane Risk of Bias 2 for randomized controlled trials
2. ROBINSIValidator - Risk of Bias In Non-randomised Studies of Interventions
3. QUADAS2Validator - Quality Assessment of Diagnostic Accuracy Studies
4. PROBASTValidator - Prediction model Risk Of Bias ASsessment Tool

References:
- ROB 2: Sterne JAC, et al. BMJ. 2019;366:l4898
- ROBINS-I: Sterne JA, et al. BMJ. 2016;355:i4919
- QUADAS-2: Whiting PF, et al. Ann Intern Med. 2011;155(8):529-536
- PROBAST: Wolff RF, et al. Ann Intern Med. 2019;170(1):51-58
"""

from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from ..constants import Severity, CertificationProfile
from ..models import NumericClaim, ScopeLock, ValidatorResult, ValidatorConfig
from .base import Validator, ValidatorRegistry


# =============================================================================
# Common Risk of Bias Enums
# =============================================================================


class ROB2Judgment(str, Enum):
    """ROB 2 judgment levels for RCTs."""
    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"


class ROBINSIJudgment(str, Enum):
    """ROBINS-I judgment levels for non-randomized studies."""
    LOW = "low"
    MODERATE = "moderate"
    SERIOUS = "serious"
    CRITICAL = "critical"
    NO_INFORMATION = "no_information"


class QUADAS2Judgment(str, Enum):
    """QUADAS-2 judgment levels for diagnostic accuracy studies."""
    LOW = "low"
    HIGH = "high"
    UNCLEAR = "unclear"


class PROBASTJudgment(str, Enum):
    """PROBAST judgment levels for prediction model studies."""
    LOW = "low"
    HIGH = "high"
    UNCLEAR = "unclear"


# =============================================================================
# ROB 2 Domain Definitions
# =============================================================================


ROB2_DOMAINS = {
    "randomization": {
        "number": 1,
        "name": "Randomization process",
        "description": "Bias arising from the randomization process",
        "signaling_questions": [
            "Was the allocation sequence random?",
            "Was the allocation sequence concealed until participants were enrolled and assigned to interventions?",
            "Did baseline differences between intervention groups suggest a problem with the randomization process?",
        ],
    },
    "deviations": {
        "number": 2,
        "name": "Deviations from intended interventions",
        "description": "Bias due to deviations from intended interventions",
        "signaling_questions": [
            "Were participants aware of their assigned intervention during the trial?",
            "Were carers and people delivering the interventions aware of participants' assigned intervention during the trial?",
            "Were there deviations from the intended intervention that arose because of the trial context?",
            "Were these deviations likely to have affected the outcome?",
            "Were these deviations from intended intervention balanced between groups?",
        ],
    },
    "missing_data": {
        "number": 3,
        "name": "Missing outcome data",
        "description": "Bias due to missing outcome data",
        "signaling_questions": [
            "Were data for this outcome available for all, or nearly all, participants randomized?",
            "Is there evidence that the result was not biased by missing outcome data?",
            "Could missingness in the outcome depend on its true value?",
            "Is it likely that missingness in the outcome depended on its true value?",
        ],
    },
    "measurement": {
        "number": 4,
        "name": "Measurement of the outcome",
        "description": "Bias in measurement of the outcome",
        "signaling_questions": [
            "Was the method of measuring the outcome inappropriate?",
            "Could measurement or ascertainment of the outcome have differed between intervention groups?",
            "Were outcome assessors aware of the intervention received by study participants?",
            "Could assessment of the outcome have been influenced by knowledge of intervention received?",
            "Is it likely that assessment of the outcome was influenced by knowledge of intervention received?",
        ],
    },
    "selection": {
        "number": 5,
        "name": "Selection of the reported result",
        "description": "Bias in selection of the reported result",
        "signaling_questions": [
            "Were the data that produced this result analysed in accordance with a pre-specified analysis plan that was finalized before unblinded outcome data were available for analysis?",
            "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible outcome measurements within the outcome domain?",
            "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible analyses of the data?",
        ],
    },
}


# =============================================================================
# ROBINS-I Domain Definitions
# =============================================================================


ROBINSI_DOMAINS = {
    "confounding": {
        "number": 1,
        "name": "Confounding",
        "description": "Bias due to confounding",
        "signaling_questions": [
            "Is there potential for confounding of the effect of intervention in this study?",
            "Was the analysis based on splitting participants' follow up time according to intervention received?",
            "Were intervention discontinuations or switches likely to be related to factors that are prognostic for the outcome?",
            "Did the authors use an appropriate analysis method that controlled for all the important confounding domains?",
            "Were confounding domains that were controlled for measured validly and reliably?",
            "Did the authors control for any post-intervention variables that could have been affected by the intervention?",
        ],
    },
    "selection": {
        "number": 2,
        "name": "Selection of participants",
        "description": "Bias in selection of participants into the study",
        "signaling_questions": [
            "Was selection of participants into the study (or into the analysis) based on participant characteristics observed after the start of intervention?",
            "Were the post-intervention variables that influenced selection likely to be associated with intervention?",
            "Were the post-intervention variables that influenced selection likely to be influenced by the outcome or a cause of the outcome?",
        ],
    },
    "classification": {
        "number": 3,
        "name": "Classification of interventions",
        "description": "Bias in classification of interventions",
        "signaling_questions": [
            "Were intervention groups clearly defined?",
            "Was the information used to define intervention groups recorded at the start of the intervention?",
            "Could classification of intervention status have been affected by knowledge of the outcome or risk of the outcome?",
        ],
    },
    "deviations": {
        "number": 4,
        "name": "Deviations from intended interventions",
        "description": "Bias due to deviations from intended interventions",
        "signaling_questions": [
            "Were there deviations from the intended intervention beyond what would be expected in usual practice?",
            "Were these deviations from intended intervention unbalanced between groups and likely to have affected the outcome?",
            "Were important co-interventions balanced across intervention groups?",
            "Was the intervention implemented successfully for most participants?",
        ],
    },
    "missing_data": {
        "number": 5,
        "name": "Missing data",
        "description": "Bias due to missing data",
        "signaling_questions": [
            "Were outcome data available for all, or nearly all, participants?",
            "Were participants excluded due to missing data on intervention status?",
            "Were participants excluded due to missing data on other variables needed for the analysis?",
            "Is it likely that missingness in the outcome was associated with its true value?",
        ],
    },
    "measurement": {
        "number": 6,
        "name": "Measurement of outcomes",
        "description": "Bias in measurement of outcomes",
        "signaling_questions": [
            "Could the outcome measure have been influenced by knowledge of the intervention received?",
            "Were outcome assessors aware of the intervention received by study participants?",
            "Were the methods of outcome assessment comparable across intervention groups?",
            "Were any systematic errors in measurement of the outcome related to intervention received?",
        ],
    },
    "reported_result": {
        "number": 7,
        "name": "Selection of the reported result",
        "description": "Bias in selection of the reported result",
        "signaling_questions": [
            "Is the reported effect estimate likely to be selected, on the basis of the results, from multiple outcome measurements?",
            "Is the reported effect estimate likely to be selected, on the basis of the results, from multiple analyses of the intervention-outcome relationship?",
            "Is the reported effect estimate likely to be selected, on the basis of the results, from different subgroups?",
        ],
    },
}


# =============================================================================
# QUADAS-2 Domain Definitions
# =============================================================================


QUADAS2_DOMAINS = {
    "patient_selection": {
        "number": 1,
        "name": "Patient Selection",
        "description": "Risk of bias and applicability concerns related to patient selection",
        "risk_of_bias_questions": [
            "Was a consecutive or random sample of patients enrolled?",
            "Was a case-control design avoided?",
            "Did the study avoid inappropriate exclusions?",
        ],
        "applicability_question": "Are there concerns that the included patients do not match the review question?",
        "has_applicability": True,
    },
    "index_test": {
        "number": 2,
        "name": "Index Test",
        "description": "Risk of bias and applicability concerns related to the index test",
        "risk_of_bias_questions": [
            "Were the index test results interpreted without knowledge of the results of the reference standard?",
            "If a threshold was used, was it pre-specified?",
        ],
        "applicability_question": "Are there concerns that the index test, its conduct, or interpretation differ from the review question?",
        "has_applicability": True,
    },
    "reference_standard": {
        "number": 3,
        "name": "Reference Standard",
        "description": "Risk of bias and applicability concerns related to the reference standard",
        "risk_of_bias_questions": [
            "Is the reference standard likely to correctly classify the target condition?",
            "Were the reference standard results interpreted without knowledge of the results of the index test?",
        ],
        "applicability_question": "Are there concerns that the target condition as defined by the reference standard does not match the review question?",
        "has_applicability": True,
    },
    "flow_timing": {
        "number": 4,
        "name": "Flow and Timing",
        "description": "Risk of bias related to patient flow and timing of tests",
        "risk_of_bias_questions": [
            "Was there an appropriate interval between index test and reference standard?",
            "Did all patients receive the same reference standard?",
            "Were all patients included in the analysis?",
        ],
        "applicability_question": None,
        "has_applicability": False,
    },
}


# =============================================================================
# PROBAST Domain Definitions
# =============================================================================


PROBAST_DOMAINS = {
    "participants": {
        "number": 1,
        "name": "Participants",
        "description": "Risk of bias related to participant selection",
        "signaling_questions": [
            "Were appropriate data sources used?",
            "Were all inclusions and exclusions of participants appropriate?",
        ],
        "has_applicability": True,
        "applicability_question": "Are there concerns that the data source is not representative of the target population?",
    },
    "predictors": {
        "number": 2,
        "name": "Predictors",
        "description": "Risk of bias related to predictors",
        "signaling_questions": [
            "Were predictors defined and assessed in a similar way for all participants?",
            "Were predictor assessments made without knowledge of outcome data?",
            "Are all predictors available at the time the model is intended to be used?",
        ],
        "has_applicability": True,
        "applicability_question": "Are there concerns that the definition, assessment, or timing of predictors in the model do not match the review question?",
    },
    "outcome": {
        "number": 3,
        "name": "Outcome",
        "description": "Risk of bias related to outcome",
        "signaling_questions": [
            "Was the outcome defined and determined in a similar way for all participants?",
            "Was the outcome determined without knowledge of predictor information?",
            "Was the time interval between predictor assessment and outcome determination appropriate?",
        ],
        "has_applicability": True,
        "applicability_question": "Are there concerns that the outcome, its definition, timing, or determination do not match the review question?",
    },
    "analysis": {
        "number": 4,
        "name": "Analysis",
        "description": "Risk of bias related to analysis",
        "signaling_questions": [
            "Were there a reasonable number of participants with the outcome?",
            "Were continuous and categorical predictors handled appropriately?",
            "Were all enrolled participants included in the analysis?",
            "Were participants with missing data handled appropriately?",
            "Was selection of predictors based on univariable analysis avoided?",
            "Were complexities in the data accounted for appropriately?",
            "Were relevant model performance measures evaluated appropriately?",
            "Was model overfitting, underfitting and optimism in model performance accounted for?",
            "Do predictors and their assigned weights in the final model correspond to the reported multivariable analysis?",
        ],
        "has_applicability": False,
        "applicability_question": None,
    },
}


# =============================================================================
# ROB 2 Validator
# =============================================================================


@dataclass
class ROB2Assessment:
    """Assessment data for a single study using ROB 2."""
    study_id: str
    domain_judgments: dict[str, ROB2Judgment] = field(default_factory=dict)
    domain_support: dict[str, str] = field(default_factory=dict)
    overall_judgment: Optional[ROB2Judgment] = None
    overall_support: str = ""


@ValidatorRegistry.register
class ROB2Validator(Validator):
    """
    Cochrane Risk of Bias 2 (ROB 2) validator for randomized controlled trials.

    Validates that risk of bias assessments are complete and consistent
    according to the ROB 2 tool structure.

    Reference:
    Sterne JAC, et al. RoB 2: a revised tool for assessing risk of bias
    in randomised trials. BMJ. 2019;366:l4898
    """

    name = "rob2"
    description = "Validates ROB 2 risk of bias assessments for RCTs"
    default_severity = Severity.WARN

    DOMAIN_KEYS = ["randomization", "deviations", "missing_data", "measurement", "selection"]

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}
        self.strict_mode = params.get("strict_mode", False)
        self.require_support = params.get("require_support", True)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate ROB 2 assessments."""
        errors = []
        warnings = []

        # Get ROB 2 assessments from scope_lock metadata
        rob2_data = scope_lock.metadata.get("rob2_assessments", {})

        if not rob2_data:
            # Check if ROB 2 is required for this profile
            if scope_lock.profile in (CertificationProfile.SILVER, CertificationProfile.GOLD):
                warnings.append({
                    "issue": "No ROB 2 assessments provided",
                    "recommendation": "Include risk of bias assessments for RCTs",
                })

            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.WARN if warnings else Severity.INFO,
                message="No ROB 2 assessments to validate",
                details={"warnings": warnings},
            )

        # Validate each study's assessment
        studies_assessed = 0
        complete_assessments = 0

        for study_id, assessment in rob2_data.items():
            studies_assessed += 1
            study_errors, study_warnings, is_complete = self._validate_study_assessment(
                study_id, assessment
            )
            errors.extend(study_errors)
            warnings.extend(study_warnings)
            if is_complete:
                complete_assessments += 1

        # Check overall consistency
        consistency_warnings = self._check_overall_consistency(rob2_data)
        warnings.extend(consistency_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"ROB 2: {complete_assessments}/{studies_assessed} complete assessments"
                if passed
                else f"ROB 2 validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "studies_assessed": studies_assessed,
                "complete_assessments": complete_assessments,
                "domains": list(ROB2_DOMAINS.keys()),
            },
        )

    def _validate_study_assessment(
        self, study_id: str, assessment: dict
    ) -> tuple[list[dict], list[dict], bool]:
        """Validate a single study's ROB 2 assessment."""
        errors = []
        warnings = []
        is_complete = True

        domain_judgments = assessment.get("domain_judgments", {})
        domain_support = assessment.get("domain_support", {})
        overall = assessment.get("overall_judgment")

        # Check all domains are assessed
        for domain_key in self.DOMAIN_KEYS:
            domain_info = ROB2_DOMAINS.get(domain_key, {})

            if domain_key not in domain_judgments:
                is_complete = False
                if self.strict_mode:
                    errors.append({
                        "study_id": study_id,
                        "issue": f"Missing domain assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
                else:
                    warnings.append({
                        "study_id": study_id,
                        "issue": f"Missing domain assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
            else:
                # Validate judgment value
                judgment = domain_judgments[domain_key]
                valid_judgments = [j.value for j in ROB2Judgment]
                if judgment not in valid_judgments:
                    errors.append({
                        "study_id": study_id,
                        "domain": domain_key,
                        "issue": f"Invalid judgment '{judgment}'",
                        "valid_values": valid_judgments,
                    })

            # Check for supporting text
            if self.require_support and domain_key not in domain_support:
                warnings.append({
                    "study_id": study_id,
                    "domain": domain_key,
                    "issue": "Missing supporting text for judgment",
                })

        # Validate overall judgment
        if overall is None:
            is_complete = False
            if self.strict_mode:
                errors.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
            else:
                warnings.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
        else:
            valid_judgments = [j.value for j in ROB2Judgment]
            if overall not in valid_judgments:
                errors.append({
                    "study_id": study_id,
                    "issue": f"Invalid overall judgment '{overall}'",
                    "valid_values": valid_judgments,
                })

            # Check overall is consistent with domain judgments
            self._check_overall_domain_consistency(
                study_id, overall, domain_judgments, warnings
            )

        return errors, warnings, is_complete

    def _check_overall_domain_consistency(
        self,
        study_id: str,
        overall: str,
        domain_judgments: dict,
        warnings: list,
    ):
        """Check that overall judgment is consistent with domain judgments."""
        judgments = list(domain_judgments.values())

        if not judgments:
            return

        # ROB 2 algorithm:
        # - Low: all domains low
        # - Some concerns: at least one some_concerns, no high
        # - High: at least one high

        has_high = ROB2Judgment.HIGH.value in judgments
        has_some_concerns = ROB2Judgment.SOME_CONCERNS.value in judgments
        all_low = all(j == ROB2Judgment.LOW.value for j in judgments)

        expected_overall = None
        if has_high:
            expected_overall = ROB2Judgment.HIGH.value
        elif has_some_concerns:
            expected_overall = ROB2Judgment.SOME_CONCERNS.value
        elif all_low:
            expected_overall = ROB2Judgment.LOW.value

        if expected_overall and overall != expected_overall:
            warnings.append({
                "study_id": study_id,
                "issue": "Overall judgment may be inconsistent with domain judgments",
                "overall": overall,
                "expected": expected_overall,
                "domain_judgments": domain_judgments,
            })

    def _check_overall_consistency(self, rob2_data: dict) -> list[dict]:
        """Check consistency across all study assessments."""
        warnings = []

        # Count judgment distributions
        overall_counts = {"low": 0, "some_concerns": 0, "high": 0}
        for assessment in rob2_data.values():
            overall = assessment.get("overall_judgment")
            if overall in overall_counts:
                overall_counts[overall] += 1

        total = sum(overall_counts.values())
        if total > 0:
            high_proportion = overall_counts["high"] / total
            if high_proportion > 0.8:
                warnings.append({
                    "issue": "Very high proportion of studies at high risk of bias",
                    "high_risk_proportion": round(high_proportion, 2),
                    "recommendation": "Consider impact on certainty of evidence",
                })

        return warnings


# =============================================================================
# ROBINS-I Validator
# =============================================================================


@dataclass
class ROBINSIAssessment:
    """Assessment data for a single study using ROBINS-I."""
    study_id: str
    domain_judgments: dict[str, ROBINSIJudgment] = field(default_factory=dict)
    domain_support: dict[str, str] = field(default_factory=dict)
    overall_judgment: Optional[ROBINSIJudgment] = None
    overall_support: str = ""


@ValidatorRegistry.register
class ROBINSIValidator(Validator):
    """
    ROBINS-I (Risk Of Bias In Non-randomised Studies - of Interventions) validator.

    Validates risk of bias assessments for non-randomized studies of interventions.

    Reference:
    Sterne JA, et al. ROBINS-I: a tool for assessing risk of bias in
    non-randomised studies of interventions. BMJ. 2016;355:i4919
    """

    name = "robins_i"
    description = "Validates ROBINS-I risk of bias assessments for non-randomized studies"
    default_severity = Severity.WARN

    DOMAIN_KEYS = [
        "confounding", "selection", "classification", "deviations",
        "missing_data", "measurement", "reported_result"
    ]

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}
        self.strict_mode = params.get("strict_mode", False)
        self.require_support = params.get("require_support", True)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate ROBINS-I assessments."""
        errors = []
        warnings = []

        # Get ROBINS-I assessments from scope_lock metadata
        robinsi_data = scope_lock.metadata.get("robinsi_assessments", {})

        if not robinsi_data:
            # ROBINS-I is only needed for non-randomized studies
            has_nrs = scope_lock.metadata.get("has_nonrandomized_studies", False)
            if has_nrs and scope_lock.profile in (CertificationProfile.SILVER, CertificationProfile.GOLD):
                warnings.append({
                    "issue": "Non-randomized studies present but no ROBINS-I assessments",
                    "recommendation": "Include ROBINS-I assessments for non-randomized studies",
                })

            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.WARN if warnings else Severity.INFO,
                message="No ROBINS-I assessments to validate",
                details={"warnings": warnings},
            )

        # Validate each study's assessment
        studies_assessed = 0
        complete_assessments = 0

        for study_id, assessment in robinsi_data.items():
            studies_assessed += 1
            study_errors, study_warnings, is_complete = self._validate_study_assessment(
                study_id, assessment
            )
            errors.extend(study_errors)
            warnings.extend(study_warnings)
            if is_complete:
                complete_assessments += 1

        # Check overall consistency
        consistency_warnings = self._check_overall_consistency(robinsi_data)
        warnings.extend(consistency_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"ROBINS-I: {complete_assessments}/{studies_assessed} complete assessments"
                if passed
                else f"ROBINS-I validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "studies_assessed": studies_assessed,
                "complete_assessments": complete_assessments,
                "domains": list(ROBINSI_DOMAINS.keys()),
            },
        )

    def _validate_study_assessment(
        self, study_id: str, assessment: dict
    ) -> tuple[list[dict], list[dict], bool]:
        """Validate a single study's ROBINS-I assessment."""
        errors = []
        warnings = []
        is_complete = True

        domain_judgments = assessment.get("domain_judgments", {})
        domain_support = assessment.get("domain_support", {})
        overall = assessment.get("overall_judgment")

        valid_judgments = [j.value for j in ROBINSIJudgment]

        # Check all domains are assessed
        for domain_key in self.DOMAIN_KEYS:
            domain_info = ROBINSI_DOMAINS.get(domain_key, {})

            if domain_key not in domain_judgments:
                is_complete = False
                if self.strict_mode:
                    errors.append({
                        "study_id": study_id,
                        "issue": f"Missing domain assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
                else:
                    warnings.append({
                        "study_id": study_id,
                        "issue": f"Missing domain assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
            else:
                # Validate judgment value
                judgment = domain_judgments[domain_key]
                if judgment not in valid_judgments:
                    errors.append({
                        "study_id": study_id,
                        "domain": domain_key,
                        "issue": f"Invalid judgment '{judgment}'",
                        "valid_values": valid_judgments,
                    })

            # Check for supporting text
            if self.require_support and domain_key not in domain_support:
                warnings.append({
                    "study_id": study_id,
                    "domain": domain_key,
                    "issue": "Missing supporting text for judgment",
                })

        # Validate overall judgment
        if overall is None:
            is_complete = False
            if self.strict_mode:
                errors.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
            else:
                warnings.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
        else:
            if overall not in valid_judgments:
                errors.append({
                    "study_id": study_id,
                    "issue": f"Invalid overall judgment '{overall}'",
                    "valid_values": valid_judgments,
                })

            # Check overall is consistent with domain judgments
            self._check_overall_domain_consistency(
                study_id, overall, domain_judgments, warnings
            )

        return errors, warnings, is_complete

    def _check_overall_domain_consistency(
        self,
        study_id: str,
        overall: str,
        domain_judgments: dict,
        warnings: list,
    ):
        """Check that overall judgment is consistent with domain judgments."""
        judgments = list(domain_judgments.values())

        if not judgments:
            return

        # ROBINS-I algorithm (hierarchical):
        # - Low: all domains low
        # - Moderate: highest domain is moderate
        # - Serious: at least one serious, no critical
        # - Critical: at least one critical
        # - No information: if any domain has no information and would affect overall

        has_critical = ROBINSIJudgment.CRITICAL.value in judgments
        has_serious = ROBINSIJudgment.SERIOUS.value in judgments
        has_moderate = ROBINSIJudgment.MODERATE.value in judgments
        has_no_info = ROBINSIJudgment.NO_INFORMATION.value in judgments
        all_low = all(j == ROBINSIJudgment.LOW.value for j in judgments)

        expected_overall = None
        if has_critical:
            expected_overall = ROBINSIJudgment.CRITICAL.value
        elif has_serious:
            expected_overall = ROBINSIJudgment.SERIOUS.value
        elif has_moderate:
            expected_overall = ROBINSIJudgment.MODERATE.value
        elif all_low:
            expected_overall = ROBINSIJudgment.LOW.value
        elif has_no_info:
            expected_overall = ROBINSIJudgment.NO_INFORMATION.value

        if expected_overall and overall != expected_overall:
            warnings.append({
                "study_id": study_id,
                "issue": "Overall judgment may be inconsistent with domain judgments",
                "overall": overall,
                "expected": expected_overall,
                "domain_judgments": domain_judgments,
            })

    def _check_overall_consistency(self, robinsi_data: dict) -> list[dict]:
        """Check consistency across all study assessments."""
        warnings = []

        # Count judgment distributions
        overall_counts = {j.value: 0 for j in ROBINSIJudgment}
        for assessment in robinsi_data.values():
            overall = assessment.get("overall_judgment")
            if overall in overall_counts:
                overall_counts[overall] += 1

        total = sum(overall_counts.values())
        if total > 0:
            critical_serious = (overall_counts["critical"] + overall_counts["serious"]) / total
            if critical_serious > 0.7:
                warnings.append({
                    "issue": "High proportion of studies at serious/critical risk of bias",
                    "critical_serious_proportion": round(critical_serious, 2),
                    "recommendation": "Consider including only moderate/low risk studies or adjusting conclusions",
                })

        return warnings


# =============================================================================
# QUADAS-2 Validator
# =============================================================================


@dataclass
class QUADAS2Assessment:
    """Assessment data for a single study using QUADAS-2."""
    study_id: str
    domain_risk_of_bias: dict[str, QUADAS2Judgment] = field(default_factory=dict)
    domain_applicability: dict[str, QUADAS2Judgment] = field(default_factory=dict)
    domain_support: dict[str, str] = field(default_factory=dict)


@ValidatorRegistry.register
class QUADAS2Validator(Validator):
    """
    QUADAS-2 (Quality Assessment of Diagnostic Accuracy Studies) validator.

    Validates risk of bias and applicability assessments for diagnostic accuracy studies.
    Each domain has both risk of bias and applicability concerns (except Flow and Timing).

    Reference:
    Whiting PF, et al. QUADAS-2: a revised tool for the quality assessment
    of diagnostic accuracy studies. Ann Intern Med. 2011;155(8):529-536
    """

    name = "quadas2"
    description = "Validates QUADAS-2 assessments for diagnostic accuracy studies"
    default_severity = Severity.WARN

    DOMAIN_KEYS = ["patient_selection", "index_test", "reference_standard", "flow_timing"]

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}
        self.strict_mode = params.get("strict_mode", False)
        self.require_support = params.get("require_support", True)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate QUADAS-2 assessments."""
        errors = []
        warnings = []

        # Get QUADAS-2 assessments from scope_lock metadata
        quadas2_data = scope_lock.metadata.get("quadas2_assessments", {})

        if not quadas2_data:
            # QUADAS-2 is only needed for diagnostic accuracy studies
            is_dta_review = scope_lock.metadata.get("is_diagnostic_accuracy_review", False)
            if is_dta_review and scope_lock.profile in (CertificationProfile.SILVER, CertificationProfile.GOLD):
                warnings.append({
                    "issue": "Diagnostic accuracy review but no QUADAS-2 assessments",
                    "recommendation": "Include QUADAS-2 assessments for diagnostic accuracy studies",
                })

            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.WARN if warnings else Severity.INFO,
                message="No QUADAS-2 assessments to validate",
                details={"warnings": warnings},
            )

        # Validate each study's assessment
        studies_assessed = 0
        complete_assessments = 0

        for study_id, assessment in quadas2_data.items():
            studies_assessed += 1
            study_errors, study_warnings, is_complete = self._validate_study_assessment(
                study_id, assessment
            )
            errors.extend(study_errors)
            warnings.extend(study_warnings)
            if is_complete:
                complete_assessments += 1

        # Aggregate risk of bias summary
        summary = self._compute_summary(quadas2_data)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"QUADAS-2: {complete_assessments}/{studies_assessed} complete assessments"
                if passed
                else f"QUADAS-2 validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "studies_assessed": studies_assessed,
                "complete_assessments": complete_assessments,
                "domains": list(QUADAS2_DOMAINS.keys()),
                "summary": summary,
            },
        )

    def _validate_study_assessment(
        self, study_id: str, assessment: dict
    ) -> tuple[list[dict], list[dict], bool]:
        """Validate a single study's QUADAS-2 assessment."""
        errors = []
        warnings = []
        is_complete = True

        risk_of_bias = assessment.get("domain_risk_of_bias", {})
        applicability = assessment.get("domain_applicability", {})
        domain_support = assessment.get("domain_support", {})

        valid_judgments = [j.value for j in QUADAS2Judgment]

        # Check all domains are assessed
        for domain_key in self.DOMAIN_KEYS:
            domain_info = QUADAS2_DOMAINS.get(domain_key, {})

            # Check risk of bias
            if domain_key not in risk_of_bias:
                is_complete = False
                if self.strict_mode:
                    errors.append({
                        "study_id": study_id,
                        "issue": f"Missing risk of bias assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                        "assessment_type": "risk_of_bias",
                    })
                else:
                    warnings.append({
                        "study_id": study_id,
                        "issue": f"Missing risk of bias assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
            else:
                judgment = risk_of_bias[domain_key]
                if judgment not in valid_judgments:
                    errors.append({
                        "study_id": study_id,
                        "domain": domain_key,
                        "assessment_type": "risk_of_bias",
                        "issue": f"Invalid judgment '{judgment}'",
                        "valid_values": valid_judgments,
                    })

            # Check applicability (except for flow_timing which has no applicability)
            if domain_info.get("has_applicability", True):
                if domain_key not in applicability:
                    is_complete = False
                    if self.strict_mode:
                        errors.append({
                            "study_id": study_id,
                            "issue": f"Missing applicability concern: {domain_info.get('name', domain_key)}",
                            "domain": domain_key,
                            "assessment_type": "applicability",
                        })
                    else:
                        warnings.append({
                            "study_id": study_id,
                            "issue": f"Missing applicability concern: {domain_info.get('name', domain_key)}",
                            "domain": domain_key,
                        })
                else:
                    judgment = applicability[domain_key]
                    if judgment not in valid_judgments:
                        errors.append({
                            "study_id": study_id,
                            "domain": domain_key,
                            "assessment_type": "applicability",
                            "issue": f"Invalid judgment '{judgment}'",
                            "valid_values": valid_judgments,
                        })

            # Check for supporting text
            if self.require_support and domain_key not in domain_support:
                warnings.append({
                    "study_id": study_id,
                    "domain": domain_key,
                    "issue": "Missing supporting text for judgment",
                })

        return errors, warnings, is_complete

    def _compute_summary(self, quadas2_data: dict) -> dict:
        """Compute summary statistics across all studies."""
        summary = {
            "risk_of_bias": {domain: {"low": 0, "high": 0, "unclear": 0} for domain in self.DOMAIN_KEYS},
            "applicability": {domain: {"low": 0, "high": 0, "unclear": 0}
                            for domain in self.DOMAIN_KEYS if QUADAS2_DOMAINS.get(domain, {}).get("has_applicability", True)},
        }

        for assessment in quadas2_data.values():
            # Risk of bias
            for domain, judgment in assessment.get("domain_risk_of_bias", {}).items():
                if domain in summary["risk_of_bias"] and judgment in summary["risk_of_bias"][domain]:
                    summary["risk_of_bias"][domain][judgment] += 1

            # Applicability
            for domain, judgment in assessment.get("domain_applicability", {}).items():
                if domain in summary["applicability"] and judgment in summary["applicability"][domain]:
                    summary["applicability"][domain][judgment] += 1

        return summary


# =============================================================================
# PROBAST Validator
# =============================================================================


@dataclass
class PROBASTAssessment:
    """Assessment data for a single study using PROBAST."""
    study_id: str
    domain_risk_of_bias: dict[str, PROBASTJudgment] = field(default_factory=dict)
    domain_applicability: dict[str, PROBASTJudgment] = field(default_factory=dict)
    domain_support: dict[str, str] = field(default_factory=dict)
    overall_risk_of_bias: Optional[PROBASTJudgment] = None
    overall_applicability: Optional[PROBASTJudgment] = None


@ValidatorRegistry.register
class PROBASTValidator(Validator):
    """
    PROBAST (Prediction model Risk Of Bias ASsessment Tool) validator.

    Validates risk of bias assessments for prediction model studies.
    Four domains: Participants, Predictors, Outcome, Analysis.
    Analysis domain has no applicability concern.

    Reference:
    Wolff RF, et al. PROBAST: A Tool to Assess the Risk of Bias and
    Applicability of Prediction Model Studies. Ann Intern Med. 2019;170(1):51-58
    """

    name = "probast"
    description = "Validates PROBAST assessments for prediction model studies"
    default_severity = Severity.WARN

    DOMAIN_KEYS = ["participants", "predictors", "outcome", "analysis"]
    APPLICABILITY_DOMAINS = ["participants", "predictors", "outcome"]  # Analysis has no applicability

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}
        self.strict_mode = params.get("strict_mode", False)
        self.require_support = params.get("require_support", True)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate PROBAST assessments."""
        errors = []
        warnings = []

        # Get PROBAST assessments from scope_lock metadata
        probast_data = scope_lock.metadata.get("probast_assessments", {})

        if not probast_data:
            # PROBAST is only needed for prediction model studies
            is_prediction_review = scope_lock.metadata.get("is_prediction_model_review", False)
            if is_prediction_review and scope_lock.profile in (CertificationProfile.SILVER, CertificationProfile.GOLD):
                warnings.append({
                    "issue": "Prediction model review but no PROBAST assessments",
                    "recommendation": "Include PROBAST assessments for prediction model studies",
                })

            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.WARN if warnings else Severity.INFO,
                message="No PROBAST assessments to validate",
                details={"warnings": warnings},
            )

        # Validate each study's assessment
        studies_assessed = 0
        complete_assessments = 0

        for study_id, assessment in probast_data.items():
            studies_assessed += 1
            study_errors, study_warnings, is_complete = self._validate_study_assessment(
                study_id, assessment
            )
            errors.extend(study_errors)
            warnings.extend(study_warnings)
            if is_complete:
                complete_assessments += 1

        # Compute summary
        summary = self._compute_summary(probast_data)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"PROBAST: {complete_assessments}/{studies_assessed} complete assessments"
                if passed
                else f"PROBAST validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "studies_assessed": studies_assessed,
                "complete_assessments": complete_assessments,
                "domains": list(PROBAST_DOMAINS.keys()),
                "summary": summary,
            },
        )

    def _validate_study_assessment(
        self, study_id: str, assessment: dict
    ) -> tuple[list[dict], list[dict], bool]:
        """Validate a single study's PROBAST assessment."""
        errors = []
        warnings = []
        is_complete = True

        risk_of_bias = assessment.get("domain_risk_of_bias", {})
        applicability = assessment.get("domain_applicability", {})
        domain_support = assessment.get("domain_support", {})
        overall_rob = assessment.get("overall_risk_of_bias")
        overall_app = assessment.get("overall_applicability")

        valid_judgments = [j.value for j in PROBASTJudgment]

        # Check all domains are assessed
        for domain_key in self.DOMAIN_KEYS:
            domain_info = PROBAST_DOMAINS.get(domain_key, {})

            # Check risk of bias
            if domain_key not in risk_of_bias:
                is_complete = False
                if self.strict_mode:
                    errors.append({
                        "study_id": study_id,
                        "issue": f"Missing risk of bias assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                        "assessment_type": "risk_of_bias",
                    })
                else:
                    warnings.append({
                        "study_id": study_id,
                        "issue": f"Missing risk of bias assessment: {domain_info.get('name', domain_key)}",
                        "domain": domain_key,
                    })
            else:
                judgment = risk_of_bias[domain_key]
                if judgment not in valid_judgments:
                    errors.append({
                        "study_id": study_id,
                        "domain": domain_key,
                        "assessment_type": "risk_of_bias",
                        "issue": f"Invalid judgment '{judgment}'",
                        "valid_values": valid_judgments,
                    })

            # Check applicability (except for analysis domain)
            if domain_key in self.APPLICABILITY_DOMAINS:
                if domain_key not in applicability:
                    is_complete = False
                    if self.strict_mode:
                        errors.append({
                            "study_id": study_id,
                            "issue": f"Missing applicability concern: {domain_info.get('name', domain_key)}",
                            "domain": domain_key,
                            "assessment_type": "applicability",
                        })
                    else:
                        warnings.append({
                            "study_id": study_id,
                            "issue": f"Missing applicability concern: {domain_info.get('name', domain_key)}",
                            "domain": domain_key,
                        })
                else:
                    judgment = applicability[domain_key]
                    if judgment not in valid_judgments:
                        errors.append({
                            "study_id": study_id,
                            "domain": domain_key,
                            "assessment_type": "applicability",
                            "issue": f"Invalid judgment '{judgment}'",
                            "valid_values": valid_judgments,
                        })

            # Check for supporting text
            if self.require_support and domain_key not in domain_support:
                warnings.append({
                    "study_id": study_id,
                    "domain": domain_key,
                    "issue": "Missing supporting text for judgment",
                })

        # Validate overall judgments
        if overall_rob is None:
            is_complete = False
            if self.strict_mode:
                errors.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
            else:
                warnings.append({
                    "study_id": study_id,
                    "issue": "Missing overall risk of bias judgment",
                })
        else:
            if overall_rob not in valid_judgments:
                errors.append({
                    "study_id": study_id,
                    "issue": f"Invalid overall risk of bias judgment '{overall_rob}'",
                    "valid_values": valid_judgments,
                })
            # Check consistency
            self._check_overall_consistency(study_id, overall_rob, risk_of_bias, warnings, "risk_of_bias")

        if overall_app is None:
            is_complete = False
            if self.strict_mode:
                errors.append({
                    "study_id": study_id,
                    "issue": "Missing overall applicability judgment",
                })
            else:
                warnings.append({
                    "study_id": study_id,
                    "issue": "Missing overall applicability judgment",
                })
        else:
            if overall_app not in valid_judgments:
                errors.append({
                    "study_id": study_id,
                    "issue": f"Invalid overall applicability judgment '{overall_app}'",
                    "valid_values": valid_judgments,
                })
            # Check consistency
            self._check_overall_consistency(study_id, overall_app, applicability, warnings, "applicability")

        return errors, warnings, is_complete

    def _check_overall_consistency(
        self,
        study_id: str,
        overall: str,
        domain_judgments: dict,
        warnings: list,
        assessment_type: str,
    ):
        """Check that overall judgment is consistent with domain judgments."""
        judgments = list(domain_judgments.values())

        if not judgments:
            return

        # PROBAST algorithm:
        # - High risk: any domain high
        # - Low risk: all domains low
        # - Unclear: at least one unclear, no high

        has_high = PROBASTJudgment.HIGH.value in judgments
        has_unclear = PROBASTJudgment.UNCLEAR.value in judgments
        all_low = all(j == PROBASTJudgment.LOW.value for j in judgments)

        expected_overall = None
        if has_high:
            expected_overall = PROBASTJudgment.HIGH.value
        elif all_low:
            expected_overall = PROBASTJudgment.LOW.value
        elif has_unclear:
            expected_overall = PROBASTJudgment.UNCLEAR.value

        if expected_overall and overall != expected_overall:
            warnings.append({
                "study_id": study_id,
                "issue": f"Overall {assessment_type} judgment may be inconsistent with domain judgments",
                "overall": overall,
                "expected": expected_overall,
                "domain_judgments": domain_judgments,
            })

    def _compute_summary(self, probast_data: dict) -> dict:
        """Compute summary statistics across all studies."""
        summary = {
            "risk_of_bias": {domain: {"low": 0, "high": 0, "unclear": 0} for domain in self.DOMAIN_KEYS},
            "applicability": {domain: {"low": 0, "high": 0, "unclear": 0} for domain in self.APPLICABILITY_DOMAINS},
            "overall_risk_of_bias": {"low": 0, "high": 0, "unclear": 0},
            "overall_applicability": {"low": 0, "high": 0, "unclear": 0},
        }

        for assessment in probast_data.values():
            # Domain risk of bias
            for domain, judgment in assessment.get("domain_risk_of_bias", {}).items():
                if domain in summary["risk_of_bias"] and judgment in summary["risk_of_bias"][domain]:
                    summary["risk_of_bias"][domain][judgment] += 1

            # Domain applicability
            for domain, judgment in assessment.get("domain_applicability", {}).items():
                if domain in summary["applicability"] and judgment in summary["applicability"][domain]:
                    summary["applicability"][domain][judgment] += 1

            # Overall
            overall_rob = assessment.get("overall_risk_of_bias")
            if overall_rob in summary["overall_risk_of_bias"]:
                summary["overall_risk_of_bias"][overall_rob] += 1

            overall_app = assessment.get("overall_applicability")
            if overall_app in summary["overall_applicability"]:
                summary["overall_applicability"][overall_app] += 1

        return summary


# =============================================================================
# Helper Functions
# =============================================================================


def get_rob2_template() -> dict:
    """Get a template for ROB 2 assessment data."""
    return {
        "domain_judgments": {domain: None for domain in ROB2_DOMAINS.keys()},
        "domain_support": {domain: "" for domain in ROB2_DOMAINS.keys()},
        "overall_judgment": None,
        "overall_support": "",
    }


def get_robinsi_template() -> dict:
    """Get a template for ROBINS-I assessment data."""
    return {
        "domain_judgments": {domain: None for domain in ROBINSI_DOMAINS.keys()},
        "domain_support": {domain: "" for domain in ROBINSI_DOMAINS.keys()},
        "overall_judgment": None,
        "overall_support": "",
    }


def get_quadas2_template() -> dict:
    """Get a template for QUADAS-2 assessment data."""
    domains_with_applicability = [k for k, v in QUADAS2_DOMAINS.items() if v.get("has_applicability", True)]
    return {
        "domain_risk_of_bias": {domain: None for domain in QUADAS2_DOMAINS.keys()},
        "domain_applicability": {domain: None for domain in domains_with_applicability},
        "domain_support": {domain: "" for domain in QUADAS2_DOMAINS.keys()},
    }


def get_probast_template() -> dict:
    """Get a template for PROBAST assessment data."""
    applicability_domains = [k for k, v in PROBAST_DOMAINS.items() if v.get("has_applicability", True)]
    return {
        "domain_risk_of_bias": {domain: None for domain in PROBAST_DOMAINS.keys()},
        "domain_applicability": {domain: None for domain in applicability_domains},
        "domain_support": {domain: "" for domain in PROBAST_DOMAINS.keys()},
        "overall_risk_of_bias": None,
        "overall_applicability": None,
    }


def generate_rob_summary_table(
    assessments: dict,
    tool: str = "rob2",
) -> str:
    """
    Generate a text-based summary table of risk of bias assessments.

    Args:
        assessments: Dictionary of study assessments
        tool: One of "rob2", "robins_i", "quadas2", "probast"

    Returns:
        Formatted string table
    """
    if tool == "rob2":
        domains = list(ROB2_DOMAINS.keys())
        header = "ROB 2 Summary"
    elif tool == "robins_i":
        domains = list(ROBINSI_DOMAINS.keys())
        header = "ROBINS-I Summary"
    elif tool == "quadas2":
        domains = list(QUADAS2_DOMAINS.keys())
        header = "QUADAS-2 Summary"
    elif tool == "probast":
        domains = list(PROBAST_DOMAINS.keys())
        header = "PROBAST Summary"
    else:
        raise ValueError(f"Unknown tool: {tool}")

    lines = [
        header,
        "=" * 60,
        "",
    ]

    # Header row
    domain_abbrevs = [d[:3].upper() for d in domains]
    header_row = f"{'Study':<20} | " + " | ".join(f"{a:<3}" for a in domain_abbrevs) + " | Overall"
    lines.append(header_row)
    lines.append("-" * len(header_row))

    # Data rows
    for study_id, assessment in assessments.items():
        judgments = assessment.get("domain_judgments", assessment.get("domain_risk_of_bias", {}))
        overall = assessment.get("overall_judgment", assessment.get("overall_risk_of_bias", "?"))

        # Symbol mapping
        def symbol(j):
            if j is None:
                return "?"
            j_lower = j.lower() if isinstance(j, str) else str(j)
            if j_lower == "low":
                return "+"
            elif j_lower in ("high", "critical", "serious"):
                return "-"
            elif j_lower in ("some_concerns", "moderate"):
                return "?"
            elif j_lower == "unclear":
                return "?"
            elif j_lower == "no_information":
                return "NI"
            return "?"

        domain_symbols = [symbol(judgments.get(d)) for d in domains]
        overall_symbol = symbol(overall)

        row = f"{study_id[:20]:<20} | " + " | ".join(f"{s:<3}" for s in domain_symbols) + f" | {overall_symbol}"
        lines.append(row)

    lines.append("")
    lines.append("Legend: + = Low risk, - = High risk, ? = Some concerns/Unclear, NI = No information")

    return "\n".join(lines)
