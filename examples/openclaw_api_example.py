"""
OpenClaw API Integration Example

Shows how to use the TruthCertGlue class to interact
with a running TruthCert server.

Prerequisites:
1. Start the TruthCert server:
   python -m certifier.main

2. Run this script:
   python examples/openclaw_api_example.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway.openclaw.glue import TruthCertGlue


def main():
    print("=" * 50)
    print("OpenClaw API Integration Demo")
    print("=" * 50)

    # Initialize glue layer
    glue = TruthCertGlue(base_url="http://localhost:8000")

    # Check health
    print("\n[1] Checking server health...")
    if glue.health_check():
        print("    Server is healthy!")
    else:
        print("    Server not responding. Start it with:")
        print("    python -m certifier.main")
        return

    # Prepare claims
    print("\n[2] Preparing claims...")
    claims = [
        {
            "claim_id": "api-rr-001",
            "claim_type": "risk_ratio",
            "value": 0.85,
            "unit": "RR",
            "lower_bound": 0.72,
            "upper_bound": 0.99,
            "standard_error": 0.08,
            "evidence": [{
                "source_type": "oa_document",
                "uri": "doi:10.1001/jama.2024.test",
                "content_hash": "sha256:" + "a" * 64
            }]
        },
        {
            "claim_id": "api-i2-001",
            "claim_type": "i_squared",
            "value": 45.2,
            "unit": "%",
            "lower_bound": 12.5,
            "upper_bound": 68.4,
            "evidence": [{
                "source_type": "oa_document",
                "uri": "doi:10.1001/jama.2024.test",
                "content_hash": "sha256:" + "a" * 64
            }]
        }
    ]
    print(f"    Prepared {len(claims)} claims")

    # Certify
    print("\n[3] Submitting for certification...")
    result = glue.certify_claims(
        claims=claims,
        policy_id="silver",
        metadata={"source": "api_demo"}
    )

    print(f"    Outcome: {result.outcome}")
    if result.outcome == "PASS":
        print(f"    Bundle ID: {result.bundle_id[:50]}...")

        # Verify
        print("\n[4] Verifying bundle...")
        verification = glue.verify_bundle(result.bundle_id)
        print(f"    Valid: {verification.get('valid')}")
        print(f"    Signature OK: {verification.get('signature_valid')}")
    else:
        print(f"    Errors: {result.errors}")

    # Memory demo (NOT evidence!)
    print("\n[5] Memory operations (for planning only)...")
    print("    WARNING: Memory is NEVER evidence for certification!")

    glue.remember(
        text="Completed meta-analysis certification via API",
        tags=["demo", "api-test"],
        memory_type="note"
    )
    print("    Stored note to memory")

    memories = glue.recall_memory("meta-analysis")
    print(f"    Memory warning: {memories.get('warning', 'None')}")

    print("\n" + "=" * 50)
    print("Demo complete!")
    print("=" * 50)

    glue.close()


if __name__ == "__main__":
    main()
