"""
Network Meta-Analysis (NMA) Validator.

Validates statistical properties specific to Network Meta-Analysis:
- SUCRA/P-score bounds (0-100%)
- Mean rank bounds (1 to n_treatments)
- Probability of being best bounds (0-1)
- Inconsistency thresholds (node-splitting, design-by-treatment)
- PSRF convergence criteria (< 1.05 for Bayesian NMA)
- League table transitivity checks

References:
- Salanti G, et al. Graphical methods and numerical summaries. Res Synth Methods. 2011;2(4):202-218.
- Rücker G, Schwarzer G. Ranking treatments in frequentist network meta-analysis. BMC Med Res Methodol. 2015;15:58.
- Dias S, et al. Checking consistency in mixed treatment comparison meta-analysis. Stat Med. 2010;29(7-8):932-944.
"""

import re
from typing import Any, Optional
from dataclasses import dataclass

from ..constants import Severity, CertificationProfile
from ..models import NumericClaim, ScopeLock, ValidatorResult, ValidatorConfig, ClaimType
from .base import Validator, ValidatorRegistry


# NMA-specific thresholds based on published methodology
NMA_THRESHOLDS = {
    # SUCRA/P-score bounds
    "sucra_min": 0.0,
    "sucra_max": 100.0,

    # Probability bounds
    "probability_min": 0.0,
    "probability_max": 1.0,

    # PSRF convergence threshold (Gelman-Rubin)
    "psrf_convergence": 1.05,
    "psrf_warning": 1.1,

    # Inconsistency p-value threshold
    "inconsistency_pvalue": 0.10,  # Conservative threshold

    # Effective sample size minimum
    "min_ess": 100,
    "recommended_ess": 1000,
}


@ValidatorRegistry.register
class NMAValidator(Validator):
    """
    Validates Network Meta-Analysis specific claims.

    This validator ensures NMA outputs conform to statistical constraints
    and methodology standards (PRISMA-NMA extension).
    """

    name = "nma"
    description = "Validates Network Meta-Analysis statistical claims"
    default_severity = Severity.WARN

    # NMA claim types
    NMA_CLAIM_TYPES = {
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
    }

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}
        self.thresholds = {**NMA_THRESHOLDS, **params.get("thresholds", {})}
        self.strict_convergence = params.get("strict_convergence", False)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate NMA claims."""
        errors = []
        warnings = []
        validated_count = 0

        # Filter to NMA claims
        nma_claims = [c for c in claims if c.claim_type in self.NMA_CLAIM_TYPES]

        if not nma_claims:
            return ValidatorResult(
                validator_name=self.name,
                passed=True,
                severity=Severity.INFO,
                message="No NMA claims to validate",
                details={"nma_claims_count": 0},
            )

        for claim in nma_claims:
            validated_count += 1
            claim_errors, claim_warnings = self._validate_nma_claim(claim)
            errors.extend(claim_errors)
            warnings.extend(claim_warnings)

        # Check for league table transitivity if multiple relative effects
        relative_effects = [c for c in nma_claims if c.claim_type == ClaimType.NMA_RELATIVE_EFFECT]
        if len(relative_effects) >= 3:
            transitivity_warnings = self._check_transitivity(relative_effects)
            warnings.extend(transitivity_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} NMA claims"
                if passed
                else f"NMA validation failed: {len(errors)} errors"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
                "thresholds_used": self.thresholds,
            },
        )

    def _validate_nma_claim(self, claim: NumericClaim) -> tuple[list[dict], list[dict]]:
        """Validate a single NMA claim."""
        errors = []
        warnings = []

        value = claim.value
        claim_id = claim.claim_id
        claim_type = claim.claim_type

        # SUCRA validation (0-100%)
        if claim_type == ClaimType.NMA_SUCRA:
            if value < self.thresholds["sucra_min"] or value > self.thresholds["sucra_max"]:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"SUCRA must be between 0-100%, got {value}%",
                    "value": value,
                })

        # P-score validation (0-100% or 0-1 depending on convention)
        elif claim_type == ClaimType.NMA_P_SCORE:
            # P-score can be 0-1 or 0-100%, normalize to 0-100%
            normalized = value if value <= 1 else value
            if normalized < 0 or normalized > 100:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"P-score must be between 0-100% (or 0-1), got {value}",
                    "value": value,
                })

        # Mean rank validation
        elif claim_type == ClaimType.NMA_MEAN_RANK:
            # Mean rank must be >= 1
            if value < 1:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"Mean rank must be >= 1, got {value}",
                    "value": value,
                })
            # Check against n_treatments if available
            n_treatments = claim.metadata.get("n_treatments")
            if n_treatments and value > n_treatments:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"Mean rank ({value}) exceeds n_treatments ({n_treatments})",
                    "value": value,
                })

        # Probability of being best validation (0-1)
        elif claim_type == ClaimType.NMA_BEST_PROBABILITY:
            if value < self.thresholds["probability_min"] or value > self.thresholds["probability_max"]:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"Probability must be between 0-1, got {value}",
                    "value": value,
                })

        # PSRF convergence validation (Bayesian NMA)
        elif claim_type == ClaimType.NMA_PSRF:
            if value >= self.thresholds["psrf_warning"]:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"PSRF ({value}) indicates poor convergence (should be < 1.05)",
                    "value": value,
                    "threshold": self.thresholds["psrf_convergence"],
                })
            elif value >= self.thresholds["psrf_convergence"]:
                warnings.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"PSRF ({value}) marginally acceptable, consider longer chains",
                    "value": value,
                })

        # Effective sample size validation
        elif claim_type == ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE:
            if value < self.thresholds["min_ess"]:
                errors.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"ESS ({value}) below minimum ({self.thresholds['min_ess']})",
                    "value": value,
                })
            elif value < self.thresholds["recommended_ess"]:
                warnings.append({
                    "claim_id": claim_id,
                    "claim_type": claim_type.value,
                    "issue": f"ESS ({value}) below recommended ({self.thresholds['recommended_ess']})",
                    "value": value,
                })

        # Inconsistency p-value validation
        elif claim_type in (ClaimType.NMA_INCONSISTENCY, ClaimType.NMA_GLOBAL_INCONSISTENCY):
            if 0 <= value <= 1:  # It's a p-value
                if value < self.thresholds["inconsistency_pvalue"]:
                    warnings.append({
                        "claim_id": claim_id,
                        "claim_type": claim_type.value,
                        "issue": f"Significant inconsistency detected (p={value})",
                        "value": value,
                        "threshold": self.thresholds["inconsistency_pvalue"],
                        "note": "Review network geometry and potential effect modifiers",
                    })

        return errors, warnings

    def _check_transitivity(self, relative_effects: list[NumericClaim]) -> list[dict]:
        """
        Check transitivity assumption in network.

        For claims A vs B, B vs C, and A vs C, check if:
        log(A vs C) ≈ log(A vs B) + log(B vs C) for ratio measures
        """
        warnings = []

        # Extract comparison pairs from metadata
        comparisons = {}
        for claim in relative_effects:
            treatment_a = claim.metadata.get("treatment_a")
            treatment_b = claim.metadata.get("treatment_b")
            if treatment_a and treatment_b:
                key = (treatment_a, treatment_b)
                comparisons[key] = claim.value

        # Check triangular consistency for any complete triangles
        treatments = set()
        for (a, b) in comparisons.keys():
            treatments.add(a)
            treatments.add(b)

        treatments = list(treatments)
        for i, a in enumerate(treatments):
            for j, b in enumerate(treatments[i+1:], i+1):
                for c in treatments[j+1:]:
                    # Check if we have all three comparisons
                    ab = comparisons.get((a, b)) or comparisons.get((b, a))
                    bc = comparisons.get((b, c)) or comparisons.get((c, b))
                    ac = comparisons.get((a, c)) or comparisons.get((c, a))

                    if ab and bc and ac:
                        # For ratio measures, check multiplicative consistency
                        # ac ≈ ab * bc (or ac ≈ ab / bc depending on direction)
                        # This is a simplified check - full inconsistency requires variance
                        import math
                        if ab > 0 and bc > 0 and ac > 0:
                            expected_ac = ab * bc
                            ratio = ac / expected_ac if expected_ac != 0 else float('inf')

                            # Flag if ratio differs by more than 50%
                            if ratio < 0.5 or ratio > 2.0:
                                warnings.append({
                                    "issue": "Potential transitivity violation",
                                    "triangle": [a, b, c],
                                    "observed_ratio": ratio,
                                    "note": "Consider node-splitting analysis",
                                })

        return warnings


@ValidatorRegistry.register
class PRISMANMAValidator(Validator):
    """
    Validates PRISMA-NMA extension checklist compliance.

    Checks that NMA-specific reporting requirements are documented.
    Reference: Hutton B, et al. The PRISMA extension statement for NMA. Ann Intern Med. 2015;162(11):777-784.

    Full 16-item PRISMA-NMA extension checklist:
    S1: Network geometry described
    S2: Transitivity assumption assessed
    S3: Statistical methods for NMA
    S4: Inconsistency assessment methods
    S5: Ranking methods described
    S6: Methods for exploring heterogeneity
    S7: Methods for exploring inconsistency
    S8: Risk of bias assessment
    S9: Funding sources
    S10: Network diagram presentation
    S11: Summary of network characteristics
    S12: Risk of bias across studies
    S13: Results of syntheses
    S14: Exploration of heterogeneity
    S15: Network meta-analysis results
    S16: Certainty assessment
    """

    name = "prisma_nma"
    description = "Validates PRISMA-NMA reporting checklist (full 16 items)"
    default_severity = Severity.WARN

    # PRISMA-NMA full 16 required items
    REQUIRED_METADATA_KEYS = {
        # Methods items (S1-S9)
        "network_geometry_described",           # S1: Describe the network geometry
        "transitivity_assumption_assessed",     # S2: Assess transitivity assumption
        "statistical_methods_nma",              # S3: Describe statistical methods used for NMA
        "inconsistency_assessed",               # S4: Describe methods for assessing inconsistency
        "ranking_methods_described",            # S5: Describe methods for ranking treatments
        "heterogeneity_exploration_methods",    # S6: Describe methods for exploring heterogeneity
        "inconsistency_exploration_methods",    # S7: Describe methods for exploring inconsistency
        "risk_of_bias_assessment",              # S8: Describe risk of bias assessment methods
        "funding_sources_reported",             # S9: Report funding sources and role of funders
        # Results items (S10-S16)
        "network_diagram_presented",            # S10: Present network diagram
        "network_characteristics_summarized",   # S11: Summarize network characteristics
        "risk_of_bias_across_studies",          # S12: Present risk of bias across studies
        "results_of_syntheses",                 # S13: Present results of all syntheses
        "heterogeneity_exploration_results",    # S14: Present exploration of heterogeneity
        "nma_results_presented",                # S15: Present NMA results (league tables, forest plots)
        "certainty_assessment",                 # S16: Present certainty assessment (GRADE)
    }

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate PRISMA-NMA compliance."""
        warnings = []

        # Check scope_lock metadata for PRISMA-NMA items
        prisma_metadata = scope_lock.metadata.get("prisma_nma", {})

        missing_items = []
        for item in self.REQUIRED_METADATA_KEYS:
            if not prisma_metadata.get(item):
                missing_items.append(item)

        if missing_items:
            warnings.append({
                "issue": "Missing PRISMA-NMA checklist items",
                "missing_items": missing_items,
                "note": "Document these items in scope_lock.metadata.prisma_nma",
            })

        passed = len(warnings) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.WARN if not passed else Severity.INFO,
            message=(
                "PRISMA-NMA checklist complete"
                if passed
                else f"PRISMA-NMA checklist incomplete: {len(missing_items)} missing items"
            ),
            details={
                "warnings": warnings,
                "required_items": list(self.REQUIRED_METADATA_KEYS),
                "documented_items": [k for k in self.REQUIRED_METADATA_KEYS if prisma_metadata.get(k)],
            },
        )
