"""
Network Meta-Analysis (NMA) Certification Example

Demonstrates certification of NMA-specific claims:
- SUCRA scores (0-100%)
- P-scores (0-1)
- Mean ranks (1 to n_treatments)
- Relative effects
- PSRF convergence diagnostics
- Effective sample size (ESS)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from certifier.bundle import create_bundle
from certifier.constants import Severity
from certifier.models import (
    CertificationProfile,
    ClaimType,
    EvidenceLocator,
    EvidenceType,
    NumericClaim,
    ScopeLock,
    ValidationSummary,
)
from certifier.signing import generate_keypair
from certifier.validators import NMAValidator, PRISMANMAValidator, ValidatorRegistry


def main():
    print("=" * 50)
    print("NMA Certification Demo")
    print("=" * 50)

    # Setup signing keys
    print("\n[1] Setting up...")
    private_b64, public_b64 = generate_keypair()
    os.environ["TRUTHCERT_SIGNING_KEY"] = private_b64
    os.environ["TRUTHCERT_PUBLIC_KEY"] = public_b64

    # Create evidence locator
    evidence = [
        EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="doi:10.1002/nma.2024.001",
            content_hash="sha256:" + "b" * 64,
            page=12,
            section="Results - Network Meta-Analysis",
        )
    ]

    # Create NMA claims
    print("\n[2] Creating NMA claims...")

    claims = [
        # SUCRA scores for each treatment
        NumericClaim(
            claim_id="sucra-drug-a",
            claim_type=ClaimType.NMA_SUCRA,
            value=85.5,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Drug A", "n_treatments": 5},
        ),
        NumericClaim(
            claim_id="sucra-drug-b",
            claim_type=ClaimType.NMA_SUCRA,
            value=62.3,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Drug B", "n_treatments": 5},
        ),
        NumericClaim(
            claim_id="sucra-drug-c",
            claim_type=ClaimType.NMA_SUCRA,
            value=45.1,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Drug C", "n_treatments": 5},
        ),
        NumericClaim(
            claim_id="sucra-placebo",
            claim_type=ClaimType.NMA_SUCRA,
            value=15.8,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Placebo", "n_treatments": 5},
        ),
        # P-scores
        NumericClaim(
            claim_id="pscore-drug-a",
            claim_type=ClaimType.NMA_P_SCORE,
            value=0.88,
            evidence=evidence,
            metadata={"treatment": "Drug A"},
        ),
        # Mean ranks
        NumericClaim(
            claim_id="mean-rank-a",
            claim_type=ClaimType.NMA_MEAN_RANK,
            value=1.5,
            evidence=evidence,
            metadata={"treatment": "Drug A", "n_treatments": 5},
        ),
        # Bayesian convergence diagnostics
        NumericClaim(
            claim_id="psrf-001",
            claim_type=ClaimType.NMA_PSRF,
            value=1.02,  # Good convergence (< 1.05)
            evidence=evidence,
            metadata={"parameter": "d[2]"},
        ),
        # Effective sample size
        NumericClaim(
            claim_id="ess-001",
            claim_type=ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
            value=5000,  # Good ESS (> 1000)
            evidence=evidence,
        ),
        # Relative effect (Drug A vs Placebo)
        NumericClaim(
            claim_id="nma-effect-a-placebo",
            claim_type=ClaimType.NMA_RELATIVE_EFFECT,
            value=0.65,
            unit="OR",
            lower_bound=0.48,
            upper_bound=0.88,
            evidence=evidence,
            metadata={
                "comparison": "Drug A vs Placebo",
                "effect_measure": "odds_ratio",
            },
        ),
    ]

    print(f"    Created {len(claims)} NMA claims")

    # Create scope with PRISMA-NMA metadata
    print("\n[3] Setting up PRISMA-NMA scope...")

    scope = ScopeLock(
        scope_id="nma-demo",
        policy_id="gold",
        profile=CertificationProfile.GOLD,
        allowed_sources=["oa_document"],
        metadata={
            "prisma_nma": {
                "network_geometry_described": True,
                "transitivity_assumption_assessed": True,
                "statistical_methods_nma": "Bayesian NMA with vague priors",
                "inconsistency_assessed": "Node-splitting method",
                "ranking_methods_described": "SUCRA and P-scores",
            }
        },
    )

    # Run NMA-specific validator
    print("\n[4] Running NMA validator...")
    nma_validator = NMAValidator()
    nma_result = nma_validator.run(claims, scope, {})

    status = "PASS" if nma_result.passed else "FAIL"
    print(f"    NMA Validation: {status}")
    print(f"    Validated: {nma_result.details.get('validated_count', 0)} claims")

    if nma_result.details.get("warnings"):
        for warn in nma_result.details["warnings"][:3]:
            print(f"    Warning: {warn.get('claim_id')}: {warn.get('issue')}")

    # Run PRISMA-NMA validator
    print("\n[5] Running PRISMA-NMA checklist validator...")
    prisma_validator = PRISMANMAValidator()
    prisma_result = prisma_validator.run(claims, scope, {})

    status = "PASS" if prisma_result.passed else "FAIL"
    print(f"    PRISMA-NMA: {status}")

    # Run full pipeline
    print("\n[6] Running full validation pipeline...")
    validators = ["schema", "memory_leak", "evidence_allowlist", "nma", "qwed"]
    results = []

    for name in validators:
        v = ValidatorRegistry.get_instance(name)
        if v:
            r = v.run(claims, scope, {})
            results.append(r)
            status = "PASS" if r.passed else "FAIL"
            print(f"    {name}: {status}")

    # Create bundle
    print("\n[7] Creating certification bundle...")

    blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]

    summary = ValidationSummary(
        results=results,
        all_passed=len(blocking) == 0,
        has_blocking=len(blocking) > 0,
        has_warnings=any(r.severity == Severity.WARN for r in results),
        blocking_count=len(blocking),
    )

    bundle_path, receipt = create_bundle(claims, scope, "gold", summary, validators)

    outcome = "PASS" if summary.all_passed else "REJECT"

    print("\n[8] Results:")
    print(f"    Outcome: {outcome}")
    print(f"    Bundle ID: {receipt.get('bundle_id', 'N/A')[:50]}...")
    print("    Profile: GOLD")
    print(f"    Bundle path: {bundle_path}")

    print("\n" + "=" * 50)
    print("NMA certification complete!")
    print("=" * 50)

    return bundle_path, receipt


if __name__ == "__main__":
    main()
