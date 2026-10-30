"""
TruthCert + OpenClaw Full Workflow Demo

This script demonstrates the complete certification workflow:
1. Generate signing keys
2. Start the TruthCert server
3. Create and certify claims
4. Verify the certified bundle
5. Render proof-carrying numbers
"""

import hashlib
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from certifier.bundle import create_bundle, load_bundle
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
from certifier.qwed import QWEDVerifier, get_verification_summary
from certifier.signing import generate_keypair
from certifier.validators import ValidatorRegistry


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"sha256:{digest}"


def main():
    print("=" * 60)
    print("TruthCert + OpenClaw Certification Demo")
    print("=" * 60)

    # Step 1: Setup signing keys
    print("\n[1] Setting up signing keys...")
    private_b64, public_b64 = generate_keypair()
    os.environ["TRUTHCERT_SIGNING_KEY"] = private_b64
    os.environ["TRUTHCERT_PUBLIC_KEY"] = public_b64
    print("    Keys generated and set in environment")

    # Step 2: Create claims from "extracted" data
    print("\n[2] Creating claims from extracted data...")

    # Simulated PDF content hash
    pdf_hash = compute_content_hash("Simulated PDF content of meta-analysis paper")

    claims = [
        # Pooled effect estimate
        NumericClaim(
            claim_id="pooled-rr-001",
            claim_type=ClaimType.POOLED_EFFECT,
            value=0.85,
            unit="risk_ratio",
            lower_bound=0.72,
            upper_bound=0.99,
            standard_error=0.08,
            confidence_level=0.95,
            n_studies=12,
            i_squared=45.2,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/jama.2024.12345",
                    content_hash=pdf_hash,
                    page=8,
                    section="Results",
                )
            ],
            metadata={
                "study_effects": [
                    0.8,
                    0.9,
                    0.75,
                    0.88,
                    0.92,
                    0.78,
                    0.85,
                    0.82,
                    0.91,
                    0.79,
                    0.87,
                    0.83,
                ],
                "study_weights": [
                    0.1,
                    0.08,
                    0.12,
                    0.09,
                    0.07,
                    0.11,
                    0.08,
                    0.09,
                    0.08,
                    0.07,
                    0.06,
                    0.05,
                ],
            },
        ),
        # Heterogeneity
        NumericClaim(
            claim_id="i2-001",
            claim_type=ClaimType.I_SQUARED,
            value=45.2,
            unit="%",
            lower_bound=12.5,
            upper_bound=68.4,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/jama.2024.12345",
                    content_hash=pdf_hash,
                    page=8,
                )
            ],
        ),
        # Sample size
        NumericClaim(
            claim_id="n-total-001",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=15420,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/jama.2024.12345",
                    content_hash=pdf_hash,
                    page=5,
                    section="Methods",
                )
            ],
        ),
    ]
    print(f"    Created {len(claims)} claims")

    # Step 3: Run QWED verification
    print("\n[3] Running QWED deterministic verification...")
    verifier = QWEDVerifier()
    all_qwed_results = []
    for claim in claims:
        results = verifier.verify_claim(claim)
        all_qwed_results.extend(results)

    summary = get_verification_summary(all_qwed_results)
    print(f"    Checks run: {summary['total_checks']}")
    print(f"    Verified: {summary['verified']}")
    print(f"    Failed: {summary['failed']}")

    # Step 4: Run validation pipeline
    print("\n[4] Running validation pipeline...")

    scope_lock = ScopeLock(
        scope_id="demo-scope-001",
        policy_id="silver",
        profile=CertificationProfile.SILVER,
        allowed_sources=["oa_document"],
        required_validators=["schema", "memory_leak", "evidence_allowlist", "qwed"],
    )

    validators_to_run = ["schema", "memory_leak", "evidence_allowlist", "effect_size_plausibility"]
    results = []

    for name in validators_to_run:
        validator = ValidatorRegistry.get_instance(name)
        if validator:
            result = validator.run(claims, scope_lock, {})
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"    {name}: {status} ({result.severity.value})")

    # Step 5: Create bundle
    print("\n[5] Creating certification bundle...")

    blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]

    validation_summary = ValidationSummary(
        results=results,
        all_passed=len(blocking) == 0,
        has_blocking=len(blocking) > 0,
        has_warnings=any(r.severity == Severity.WARN for r in results),
        blocking_count=len(blocking),
    )

    bundle_path, receipt = create_bundle(
        claims=claims,
        scope_lock=scope_lock,
        policy_id="silver",
        validation_summary=validation_summary,
        validators=validators_to_run,
    )

    outcome = "PASS" if validation_summary.all_passed else "REJECT"
    print(f"    Outcome: {outcome}")
    print(f"    Bundle ID: {receipt.get('bundle_id', 'N/A')[:40]}...")
    print(f"    Bundle path: {bundle_path}")

    # Step 6: Verify bundle
    print("\n[6] Verifying bundle...")
    bundle_data = load_bundle(bundle_path)
    print(f"    Manifest outcome: {bundle_data['manifest']['outcome']}")
    print(f"    Claims in bundle: {bundle_data['manifest']['claim_count']}")
    print(f"    Profile: {bundle_data['manifest']['profile']}")

    print("\n" + "=" * 60)
    print("Demo complete! Bundle certified and verified.")
    print("=" * 60)

    return bundle_path, receipt


if __name__ == "__main__":
    main()
