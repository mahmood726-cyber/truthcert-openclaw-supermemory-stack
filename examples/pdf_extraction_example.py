"""
PDF Extraction + TruthCert Certification Example

This script demonstrates how to:
1. Extract numbers from a PDF (simulated)
2. Convert extractions to NumericClaims
3. Run through certification pipeline
4. Get certified bundle
"""

import sys
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from certifier.signing import generate_keypair
from certifier.models import (
    NumericClaim, ClaimType, EvidenceLocator, EvidenceType,
    ScopeLock, CertificationProfile, ValidationSummary
)
from certifier.validators import ValidatorRegistry
from certifier.bundle import create_bundle
from certifier.constants import Severity


@dataclass
class ExtractedNumber:
    """Represents a number extracted from a PDF."""
    value: float
    claim_type: str
    unit: Optional[str] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    standard_error: Optional[float] = None
    page: int = 1
    section: str = ""
    context: str = ""


def extract_from_pdf(pdf_path: str):
    """
    Simulate extraction from PDF.

    In a real implementation, this would:
    1. Use an LLM to extract numbers from the PDF
    2. Compute content hash of the PDF
    3. Return structured extractions with page/section info
    """
    # Compute hash of path (in reality, hash the actual PDF content)
    content_hash = f"sha256:{hashlib.sha256(pdf_path.encode()).hexdigest()}"

    # Simulated extractions - in reality these would come from LLM
    extractions = [
        ExtractedNumber(
            value=0.73,
            claim_type="risk_ratio",
            unit="RR",
            lower_bound=0.58,
            upper_bound=0.92,
            standard_error=0.12,
            page=7,
            section="Results",
            context="The pooled risk ratio was 0.73 (95% CI: 0.58-0.92)"
        ),
        ExtractedNumber(
            value=52.3,
            claim_type="i_squared",
            unit="%",
            lower_bound=18.5,
            upper_bound=72.1,
            page=8,
            section="Heterogeneity",
            context="I² = 52.3% (95% CI: 18.5-72.1%)"
        ),
        ExtractedNumber(
            value=8542,
            claim_type="sample_size",
            page=5,
            section="Methods",
            context="Total participants: 8,542"
        ),
    ]
    return extractions, content_hash


def certify_claims(claims, policy_id="silver"):
    """Run claims through certification pipeline."""
    # Generate keys
    private_b64, public_b64 = generate_keypair()
    os.environ["TRUTHCERT_SIGNING_KEY"] = private_b64
    os.environ["TRUTHCERT_PUBLIC_KEY"] = public_b64

    # Create scope lock
    scope = ScopeLock(
        scope_id="extraction-demo",
        policy_id=policy_id,
        profile=CertificationProfile.SILVER,
        allowed_sources=["oa_document"],
    )

    # Run validators
    validators = ["schema", "memory_leak", "evidence_allowlist", "math_consistency"]
    results = []

    for name in validators:
        v = ValidatorRegistry.get_instance(name)
        if v:
            result = v.run(claims, scope, {})
            results.append(result)

    # Check for blocking errors
    blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]

    summary = ValidationSummary(
        results=results,
        all_passed=len(blocking) == 0,
        has_blocking=len(blocking) > 0,
        has_warnings=any(r.severity == Severity.WARN for r in results),
        blocking_count=len(blocking),
    )

    # Create bundle
    bundle_path, receipt = create_bundle(claims, scope, policy_id, summary, validators)

    return "PASS" if summary.all_passed else "REJECT", receipt, bundle_path


def main():
    print("=" * 60)
    print("PDF Extraction + TruthCert Certification Demo")
    print("=" * 60)

    # Step 1: Extract from PDF
    print("\n[1] Extracting numbers from PDF...")
    extractions, content_hash = extract_from_pdf("sample_meta_analysis.pdf")
    print(f"    Extracted {len(extractions)} numbers")

    for ext in extractions:
        print(f"    - {ext.claim_type}: {ext.value} (page {ext.page})")

    # Step 2: Convert to claims
    print("\n[2] Converting to NumericClaims...")

    type_map = {
        "risk_ratio": ClaimType.RISK_RATIO,
        "odds_ratio": ClaimType.ODDS_RATIO,
        "hazard_ratio": ClaimType.HAZARD_RATIO,
        "i_squared": ClaimType.I_SQUARED,
        "sample_size": ClaimType.SAMPLE_SIZE,
        "pooled_effect": ClaimType.POOLED_EFFECT,
    }

    claims = []
    for i, ext in enumerate(extractions):
        claim = NumericClaim(
            claim_id=f"ext-{i:03d}",
            claim_type=type_map.get(ext.claim_type, ClaimType.CUSTOM),
            value=ext.value,
            unit=ext.unit,
            lower_bound=ext.lower_bound,
            upper_bound=ext.upper_bound,
            standard_error=ext.standard_error,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1234/example.2024",
                    content_hash=content_hash,
                    page=ext.page,
                    section=ext.section,
                )
            ],
            metadata={"extraction_context": ext.context} if ext.context else {},
        )
        claims.append(claim)

    print(f"    Created {len(claims)} claims")

    # Step 3: Certify
    print("\n[3] Running certification pipeline...")
    outcome, receipt, bundle_path = certify_claims(claims)

    print(f"\n[4] Results:")
    print(f"    Outcome: {outcome}")
    print(f"    Bundle ID: {receipt.get('bundle_id', 'N/A')[:50]}...")
    print(f"    Bundle path: {bundle_path}")

    print("\n" + "=" * 60)
    print("Extraction and certification complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
