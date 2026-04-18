"""
Domain Extension Packs for TruthCert.

Domain packs provide specialized validation for specific research domains.
Based on the Burhan specification's 12 domain extension pack architecture.

Available domain packs:
1. meta-analysis: Standard pairwise meta-analysis
2. nma: Network meta-analysis
3. dta: Diagnostic test accuracy
4. ipdma: Individual participant data meta-analysis
5. prognosis: Prognostic factor studies
6. prediction: Prediction model studies
7. qualitative: Qualitative evidence synthesis
8. economic: Health economic analysis
9. epidemiology: Observational epidemiology
10. rct: Randomized controlled trials
11. cohort: Cohort studies
12. case-control: Case-control studies
"""

from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from .models import ClaimType, ValidatorConfig, CertificationProfile
from .constants import Severity


class DomainPack(str, Enum):
    """Available domain extension packs."""
    META_ANALYSIS = "meta-analysis"
    NMA = "nma"
    DTA = "dta"
    IPDMA = "ipdma"
    PROGNOSIS = "prognosis"
    PREDICTION = "prediction"
    QUALITATIVE = "qualitative"
    ECONOMIC = "economic"
    EPIDEMIOLOGY = "epidemiology"
    RCT = "rct"
    COHORT = "cohort"
    CASE_CONTROL = "case-control"


@dataclass
class DomainPackSpec:
    """Specification for a domain extension pack."""
    name: str
    display_name: str
    description: str
    version: str
    claim_types: list[ClaimType]
    validators: list[str]
    reporting_checklist: str  # e.g., "PRISMA", "PRISMA-DTA", "PROBAST"
    required_metadata_keys: list[str]
    optional_metadata_keys: list[str] = field(default_factory=list)
    profile_requirements: dict[CertificationProfile, list[str]] = field(default_factory=dict)


# Domain pack specifications
DOMAIN_PACKS: dict[DomainPack, DomainPackSpec] = {
    DomainPack.META_ANALYSIS: DomainPackSpec(
        name="meta-analysis",
        display_name="Pairwise Meta-Analysis",
        description="Standard pairwise meta-analysis of intervention effects",
        version="1.0.0",
        claim_types=[
            ClaimType.POOLED_EFFECT,
            ClaimType.I_SQUARED,
            ClaimType.TAU_SQUARED,
            ClaimType.COCHRAN_Q,
            ClaimType.PREDICTION_INTERVAL,
            ClaimType.EGGER_INTERCEPT,
            ClaimType.FAIL_SAFE_N,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "heterogeneity",
            "publication_bias",
            "effect_size_plausibility",
            "prisma_2020",
        ],
        reporting_checklist="PRISMA 2020",
        required_metadata_keys=[
            "effect_measure",
            "model_type",
            "heterogeneity_method",
            "publication_bias_method",
        ],
        optional_metadata_keys=[
            "sensitivity_analyses",
            "subgroup_analyses",
            "meta_regression",
        ],
    ),

    DomainPack.NMA: DomainPackSpec(
        name="nma",
        display_name="Network Meta-Analysis",
        description="Network meta-analysis for indirect treatment comparisons",
        version="1.0.0",
        claim_types=[
            ClaimType.POOLED_EFFECT,
            ClaimType.NMA_SUCRA,
            ClaimType.NMA_P_SCORE,
            ClaimType.NMA_MEAN_RANK,
            ClaimType.NMA_BEST_PROBABILITY,
            ClaimType.NMA_RELATIVE_EFFECT,
            ClaimType.NMA_LEAGUE_TABLE,
            ClaimType.NMA_INCONSISTENCY,
            ClaimType.NMA_GLOBAL_INCONSISTENCY,
            ClaimType.NMA_PSRF,
            ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "nma",
            "prisma_nma",
        ],
        reporting_checklist="PRISMA-NMA Extension",
        required_metadata_keys=[
            "network_geometry",
            "transitivity_assessment",
            "inconsistency_method",
            "ranking_method",
            "model_type",  # Bayesian/Frequentist
        ],
        optional_metadata_keys=[
            "convergence_diagnostics",
            "node_splitting_results",
            "comparison_adjusted_funnel",
        ],
    ),

    DomainPack.DTA: DomainPackSpec(
        name="dta",
        display_name="Diagnostic Test Accuracy",
        description="Meta-analysis of diagnostic test accuracy studies",
        version="1.0.0",
        claim_types=[
            ClaimType.SENSITIVITY,
            ClaimType.SPECIFICITY,
            ClaimType.POSITIVE_PREDICTIVE_VALUE,
            ClaimType.NEGATIVE_PREDICTIVE_VALUE,
            ClaimType.LIKELIHOOD_RATIO_POSITIVE,
            ClaimType.LIKELIHOOD_RATIO_NEGATIVE,
            ClaimType.AUC_ROC,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "dta_bounds",  # Sensitivity/specificity in [0,1]
            "prisma_dta",
        ],
        reporting_checklist="PRISMA-DTA Extension",
        required_metadata_keys=[
            "index_test",
            "reference_standard",
            "target_condition",
            "setting",
            "model_type",  # Bivariate, HSROC
        ],
        optional_metadata_keys=[
            "threshold_analysis",
            "covariate_effects",
            "quality_assessment",  # QUADAS-2
        ],
    ),

    DomainPack.IPDMA: DomainPackSpec(
        name="ipdma",
        display_name="Individual Participant Data Meta-Analysis",
        description="Meta-analysis using individual participant data",
        version="1.0.0",
        claim_types=[
            ClaimType.POOLED_EFFECT,
            ClaimType.I_SQUARED,
            ClaimType.HAZARD_RATIO,
            ClaimType.RISK_RATIO,
            ClaimType.ODDS_RATIO,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "ipdma_consistency",
            "prisma_ipd",
        ],
        reporting_checklist="PRISMA-IPD Extension",
        required_metadata_keys=[
            "data_availability",
            "harmonization_method",
            "analysis_approach",  # one-stage, two-stage
        ],
        optional_metadata_keys=[
            "missing_data_handling",
            "interaction_analyses",
        ],
    ),

    DomainPack.PROGNOSIS: DomainPackSpec(
        name="prognosis",
        display_name="Prognostic Factor Studies",
        description="Systematic reviews of prognostic factors",
        version="1.0.0",
        claim_types=[
            ClaimType.HAZARD_RATIO,
            ClaimType.ODDS_RATIO,
            ClaimType.RISK_RATIO,
            ClaimType.POOLED_EFFECT,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "prisma_prognosis",
        ],
        reporting_checklist="PRISMA-Prognosis",
        required_metadata_keys=[
            "prognostic_factor",
            "outcome_definition",
            "time_horizon",
            "adjustment_factors",
        ],
    ),

    DomainPack.PREDICTION: DomainPackSpec(
        name="prediction",
        display_name="Prediction Model Studies",
        description="Systematic reviews of prediction models",
        version="1.0.0",
        claim_types=[
            ClaimType.AUC_ROC,
            ClaimType.CALIBRATION,
            ClaimType.SENSITIVITY,
            ClaimType.SPECIFICITY,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "probast",  # Prediction model risk of bias
        ],
        reporting_checklist="PROBAST/CHARMS",
        required_metadata_keys=[
            "model_type",
            "predictors",
            "outcome",
            "validation_type",  # internal, external
            "calibration_assessment",
        ],
    ),

    DomainPack.RCT: DomainPackSpec(
        name="rct",
        display_name="Randomized Controlled Trials",
        description="Individual RCT extraction and certification",
        version="1.0.0",
        claim_types=[
            ClaimType.EFFECT_SIZE,
            ClaimType.RISK_RATIO,
            ClaimType.ODDS_RATIO,
            ClaimType.HAZARD_RATIO,
            ClaimType.MEAN_DIFFERENCE,
            ClaimType.NUMBER_NEEDED_TO_TREAT,
            ClaimType.SAMPLE_SIZE,
        ],
        validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "effect_size_plausibility",
            "consort",  # CONSORT checklist
        ],
        reporting_checklist="CONSORT",
        required_metadata_keys=[
            "randomization_method",
            "blinding",
            "intention_to_treat",
            "allocation_concealment",
        ],
    ),
}


def get_domain_pack(pack: DomainPack) -> DomainPackSpec:
    """Get specification for a domain pack."""
    return DOMAIN_PACKS.get(pack)


def get_validators_for_domain(pack: DomainPack) -> list[str]:
    """Get list of validators for a domain pack."""
    spec = get_domain_pack(pack)
    return spec.validators if spec else []


def get_claim_types_for_domain(pack: DomainPack) -> list[ClaimType]:
    """Get list of claim types valid for a domain pack."""
    spec = get_domain_pack(pack)
    return spec.claim_types if spec else []


def create_validator_configs_for_domain(
    pack: DomainPack,
    profile: CertificationProfile = CertificationProfile.SILVER,
) -> list[ValidatorConfig]:
    """
    Create validator configurations for a domain pack.

    Args:
        pack: Domain pack to configure
        profile: Certification profile

    Returns:
        List of ValidatorConfig objects
    """
    spec = get_domain_pack(pack)
    if not spec:
        return []

    configs = []
    for validator_name in spec.validators:
        # Determine severity based on validator type
        if validator_name in ("memory_leak", "evidence_allowlist", "idn_homograph"):
            severity = Severity.BLOCK
        elif "prisma" in validator_name or "checklist" in validator_name:
            severity = Severity.WARN if profile == CertificationProfile.BRONZE else Severity.BLOCK
        else:
            severity = Severity.WARN

        configs.append(ValidatorConfig(
            name=validator_name,
            enabled=True,
            severity=severity,
            params={"domain_pack": pack.value},
        ))

    return configs


def validate_domain_metadata(
    pack: DomainPack,
    metadata: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """
    Validate that required metadata keys are present.

    Returns:
        Tuple of (missing_required, missing_optional)
    """
    spec = get_domain_pack(pack)
    if not spec:
        return [], []

    missing_required = [
        key for key in spec.required_metadata_keys
        if key not in metadata or metadata[key] is None
    ]

    missing_optional = [
        key for key in spec.optional_metadata_keys
        if key not in metadata or metadata[key] is None
    ]

    return missing_required, missing_optional


def get_reporting_checklist(pack: DomainPack) -> str:
    """Get the recommended reporting checklist for a domain pack."""
    spec = get_domain_pack(pack)
    return spec.reporting_checklist if spec else "PRISMA 2020"


def list_available_packs() -> list[dict]:
    """List all available domain packs with their descriptions."""
    return [
        {
            "name": pack.value,
            "display_name": spec.display_name,
            "description": spec.description,
            "version": spec.version,
            "checklist": spec.reporting_checklist,
            "validator_count": len(spec.validators),
            "claim_type_count": len(spec.claim_types),
        }
        for pack, spec in DOMAIN_PACKS.items()
    ]
