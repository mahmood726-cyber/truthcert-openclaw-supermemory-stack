"""
PRISMA 2020 Checklist Validator.

Validates compliance with PRISMA 2020 (Preferred Reporting Items for
Systematic Reviews and Meta-Analyses) reporting guidelines.

Reference:
Page MJ, et al. The PRISMA 2020 statement: an updated guideline for
reporting systematic reviews. BMJ. 2021;372:n71.
"""

from typing import Any

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from .base import Validator, ValidatorRegistry

# PRISMA 2020 Checklist Items (27 items + abstract)
PRISMA_2020_ITEMS: dict[str, Any] = {
    # Title
    "title": {
        "number": 1,
        "description": "Identify the report as a systematic review",
        "required": True,
    },
    # Abstract
    "abstract_structured": {
        "number": 2,
        "description": "Structured summary including background, objectives, methods, results, conclusions",
        "required": True,
    },
    # Introduction
    "rationale": {
        "number": 3,
        "description": "Describe the rationale for the review",
        "required": True,
    },
    "objectives": {
        "number": 4,
        "description": "Provide explicit statement of objectives using PICO",
        "required": True,
    },
    # Methods
    "eligibility_criteria": {
        "number": 5,
        "description": "Specify inclusion and exclusion criteria",
        "required": True,
    },
    "information_sources": {
        "number": 6,
        "description": "Specify all databases and sources searched",
        "required": True,
    },
    "search_strategy": {
        "number": 7,
        "description": "Present full search strategy for at least one database",
        "required": True,
    },
    "selection_process": {
        "number": 8,
        "description": "Specify method for study selection",
        "required": True,
    },
    "data_collection_process": {
        "number": 9,
        "description": "Describe data extraction process",
        "required": True,
    },
    "data_items": {
        "number": 10,
        "description": "List and define outcome measures and other variables",
        "required": True,
    },
    "study_risk_of_bias": {
        "number": 11,
        "description": "Describe methods for assessing risk of bias",
        "required": True,
    },
    "effect_measures": {
        "number": 12,
        "description": "Specify effect measures used (RR, OR, MD, etc.)",
        "required": True,
    },
    "synthesis_methods": {
        "number": 13,
        "description": "Describe synthesis methods including meta-analysis",
        "required": True,
        "subfields": [
            "heterogeneity_assessed",
            "model_type",  # Fixed/Random
            "sensitivity_analyses",
            "subgroup_analyses",
        ],
    },
    "reporting_bias_assessment": {
        "number": 14,
        "description": "Describe methods for assessing publication bias",
        "required": True,
    },
    "certainty_assessment": {
        "number": 15,
        "description": "Describe methods for assessing certainty (GRADE)",
        "required": True,
    },
    # Results
    "study_selection": {
        "number": 16,
        "description": "Report studies screened, assessed, included (PRISMA flow)",
        "required": True,
        "subfields": [
            "records_identified",
            "records_screened",
            "records_excluded",
            "studies_included",
        ],
    },
    "study_characteristics": {
        "number": 17,
        "description": "Cite studies and present characteristics",
        "required": True,
    },
    "risk_of_bias_in_studies": {
        "number": 18,
        "description": "Present risk of bias assessments",
        "required": True,
    },
    "results_of_individual_studies": {
        "number": 19,
        "description": "Present effect estimates for each study",
        "required": True,
    },
    "results_of_syntheses": {
        "number": 20,
        "description": "Present results of syntheses including heterogeneity",
        "required": True,
        "subfields": [
            "pooled_estimate",
            "confidence_interval",
            "heterogeneity_statistics",  # I², τ², Q
            "prediction_interval",
        ],
    },
    "reporting_biases": {
        "number": 21,
        "description": "Present results of publication bias assessment",
        "required": True,
    },
    "certainty_of_evidence": {
        "number": 22,
        "description": "Present certainty of evidence for each outcome",
        "required": True,
    },
    # Discussion
    "discussion_summary": {
        "number": 23,
        "description": "Provide general interpretation of results",
        "required": True,
    },
    "limitations": {
        "number": 24,
        "description": "Discuss limitations at study and review levels",
        "required": True,
    },
    "conclusions": {
        "number": 25,
        "description": "Provide conclusions and implications",
        "required": True,
    },
    # Other
    "registration": {
        "number": 26,
        "description": "Provide registration information (PROSPERO)",
        "required": False,
    },
    "support": {
        "number": 27,
        "description": "Describe sources of support",
        "required": False,
    },
    "competing_interests": {
        "number": 28,
        "description": "Declare competing interests",
        "required": True,
    },
}

# Required items for each profile
PROFILE_REQUIRED_ITEMS = {
    CertificationProfile.BRONZE: [
        "objectives",
        "eligibility_criteria",
        "synthesis_methods",
        "results_of_syntheses",
    ],
    CertificationProfile.SILVER: [
        "objectives",
        "eligibility_criteria",
        "information_sources",
        "search_strategy",
        "study_risk_of_bias",
        "effect_measures",
        "synthesis_methods",
        "study_selection",
        "results_of_syntheses",
        "certainty_of_evidence",
    ],
    CertificationProfile.GOLD: [k for k, v in PRISMA_2020_ITEMS.items() if v["required"]],
}


@ValidatorRegistry.register
class PRISMAChecklistValidator(Validator):
    """
    Validates PRISMA 2020 checklist compliance.

    Profile-specific requirements:
    - BRONZE: Core methods and results items
    - SILVER: Methods, results, and quality assessment items
    - GOLD: All required PRISMA 2020 items
    """

    name = "prisma_2020"
    description = "Validates PRISMA 2020 reporting checklist compliance"
    default_severity = Severity.WARN

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        super().__init__(config)
        params = config.params if config else {}
        self.strict_mode = params.get("strict_mode", False)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate PRISMA 2020 compliance."""
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        profile = scope_lock.profile
        required_items = PROFILE_REQUIRED_ITEMS.get(profile, [])

        # Get PRISMA metadata from scope_lock
        prisma_data = scope_lock.metadata.get("prisma_2020", {})

        # Check required items
        missing_required = []
        incomplete_items = []
        documented_items = []

        for item_key in required_items:
            item_info = PRISMA_2020_ITEMS.get(item_key, {})
            item_data = prisma_data.get(item_key)

            if not item_data:
                missing_required.append(
                    {
                        "item": item_key,
                        "number": item_info.get("number"),
                        "description": item_info.get("description"),
                    }
                )
            else:
                documented_items.append(item_key)

                # Check subfields if defined
                subfields = item_info.get("subfields", [])
                missing_subfields = []
                for subfield in subfields:
                    if not item_data.get(subfield):
                        missing_subfields.append(subfield)

                if missing_subfields:
                    incomplete_items.append(
                        {
                            "item": item_key,
                            "missing_subfields": missing_subfields,
                        }
                    )

        # Generate appropriate error/warning messages
        if missing_required:
            if self.strict_mode:
                errors.append(
                    {
                        "issue": "Missing required PRISMA 2020 items",
                        "missing_items": missing_required,
                        "profile": profile.value,
                    }
                )
            else:
                warnings.append(
                    {
                        "issue": "Missing recommended PRISMA 2020 items",
                        "missing_items": missing_required,
                        "profile": profile.value,
                        "note": "Enable strict_mode to enforce as errors",
                    }
                )

        if incomplete_items:
            warnings.append(
                {
                    "issue": "Incomplete PRISMA 2020 items",
                    "incomplete_items": incomplete_items,
                    "note": "Consider documenting subfields for completeness",
                }
            )

        # Check for PRISMA flow diagram data
        flow_data = prisma_data.get("study_selection", {})
        if not flow_data and profile in (CertificationProfile.SILVER, CertificationProfile.GOLD):
            warnings.append(
                {
                    "issue": "PRISMA flow diagram data not documented",
                    "required_fields": [
                        "records_identified",
                        "records_screened",
                        "records_excluded",
                        "studies_included",
                    ],
                }
            )

        # Calculate compliance score
        total_required = len(required_items)
        documented_count = len(documented_items)
        compliance_score = (documented_count / total_required * 100) if total_required > 0 else 100

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK
            if not passed
            else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"PRISMA 2020 compliance: {compliance_score:.0f}% ({documented_count}/{total_required} items)"
                if passed
                else f"PRISMA 2020 compliance failed: {len(missing_required)} missing items"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "profile": profile.value,
                "compliance_score": compliance_score,
                "documented_items": documented_items,
                "missing_items": [m["item"] for m in missing_required],
                "total_required": total_required,
            },
        )


def get_prisma_template(
    profile: CertificationProfile = CertificationProfile.SILVER,
) -> dict[str, Any]:
    """
    Get a template for PRISMA 2020 metadata.

    Returns a dict with all required fields for the given profile.
    """
    required_items = PROFILE_REQUIRED_ITEMS.get(profile, [])

    template = {}
    for item_key in required_items:
        item_info = PRISMA_2020_ITEMS.get(item_key, {})

        # Create nested structure for items with subfields
        if "subfields" in item_info:
            template[item_key] = {
                "_documented": False,
                "_description": item_info.get("description"),
            }
            for subfield in item_info["subfields"]:
                template[item_key][subfield] = None
        else:
            template[item_key] = {
                "_documented": False,
                "_description": item_info.get("description"),
            }

    return template


def generate_prisma_checklist_report(
    prisma_data: dict[str, Any],
    profile: CertificationProfile = CertificationProfile.SILVER,
) -> str:
    """
    Generate a human-readable PRISMA 2020 checklist report.
    """
    required_items = PROFILE_REQUIRED_ITEMS.get(profile, [])

    lines = [
        "PRISMA 2020 Checklist Report",
        "=" * 40,
        f"Profile: {profile.value}",
        "",
    ]

    documented = 0
    total = len(required_items)

    for item_key in required_items:
        item_info = PRISMA_2020_ITEMS.get(item_key, {})
        item_data = prisma_data.get(item_key)

        number = item_info.get("number", "?")
        description = item_info.get("description", item_key)

        if item_data:
            status = "✓"
            documented += 1
        else:
            status = "✗"

        lines.append(f"[{status}] {number}. {description}")

        # Show subfields if applicable
        subfields = item_info.get("subfields", [])
        if subfields and item_data:
            for subfield in subfields:
                sub_status = "✓" if item_data.get(subfield) else "○"
                lines.append(f"    [{sub_status}] {subfield}")

    lines.append("")
    lines.append(f"Compliance: {documented}/{total} ({documented / total * 100:.0f}%)")

    return "\n".join(lines)
