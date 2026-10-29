"""Synthetic TruthCert signed-payload integrity and legacy refusal regressions.

A legacy manifest signs a bundle ID derived from selected claim fields only.
Its valid signature cannot authenticate CI bounds, sample sizes or provenance.
New v2 manifests bind the exact claims.jsonl bytes; legacy stays readable but
cannot receive an authoritative CLI verification PASS.
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from certifier.bundle import create_bundle
from certifier.constants import ENV_BUNDLE_DIR, ENV_SIGNING_KEY
from certifier.models import (
    ClaimType, EvidenceLocator, EvidenceType, NumericClaim, ScopeLock,
    ValidationSummary, CertificationProfile,
)
from certifier.signing import generate_keypair, sign_manifest, verify_signature
from cli.tc import cli


@pytest.fixture
def signed_bundle(tmp_path, monkeypatch):
    private_key, _public_key = generate_keypair()
    monkeypatch.setenv(ENV_SIGNING_KEY, private_key)
    monkeypatch.setenv(ENV_BUNDLE_DIR, str(tmp_path))
    claim = NumericClaim(
        claim_id="synthetic-effect-001",
        claim_type=ClaimType.EFFECT_SIZE,
        value=0.45,
        lower_bound=0.25,
        upper_bound=0.65,
        sample_size=120,
        provenance={"synthetic": "controlled"},
        evidence=[
            EvidenceLocator(
                source_type=EvidenceType.FIXTURE,
                uri="synthetic://source-001",
                content_hash="sha256:" + "a" * 64,
            ),
        ],
    )
    scope = ScopeLock(
        scope_id="synthetic-scope",
        policy_id="bronze",
        profile=CertificationProfile.BRONZE,
        allowed_sources=["fixture"],
    )
    summary = ValidationSummary(
        results=[], all_passed=True, has_blocking=False, has_warnings=False,
    )
    bundle_path, _receipt = create_bundle(
        claims=[claim], scope_lock=scope, policy_id="bronze",
        validation_summary=summary, validators=[], sign=True,
    )
    return bundle_path


def _verify(path):
    return CliRunner().invoke(cli, ["verify", str(path)])


def test_v2_signs_full_claim_payload_and_verifies(signed_bundle):
    manifest = json.loads((signed_bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "tc-bundle-v2"
    assert manifest["claims_sha256"].startswith("sha256:")
    result = _verify(signed_bundle)
    assert result.exit_code == 0, result.output
    assert "Verification PASSED" in result.output


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("lower_bound", -100.0),
        ("sample_size", 99999),
        ("provenance", {"synthetic": "changed"}),
    ],
)
def test_signed_manifest_rejects_changes_to_previously_unbound_fields(
    signed_bundle, key, value,
):
    claims_file = signed_bundle / "claims.jsonl"
    claim = json.loads(claims_file.read_text(encoding="utf-8").strip())
    claim[key] = value
    claims_file.write_text(json.dumps(claim) + "\n", encoding="utf-8")
    result = _verify(signed_bundle)
    assert result.exit_code != 0
    assert "Signed claims payload digest mismatch" in result.output
    assert "Verification PASSED" not in result.output


def test_missing_signed_claims_file_is_refused(signed_bundle):
    (signed_bundle / "claims.jsonl").unlink()
    result = _verify(signed_bundle)
    assert result.exit_code != 0
    assert "Missing or unreadable claims.jsonl" in result.output


def test_re_signed_wrong_bundle_identity_and_scope_policy_are_refused(signed_bundle):
    manifest_path = signed_bundle / "manifest.json"
    sig_path = signed_bundle / "attest" / "signature.ed25519"
    pub_path = signed_bundle / "attest" / "public_key.txt"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_id"] = "sha256:" + "0" * 64
    signature, public_key = sign_manifest(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sig_path.write_text(signature, encoding="utf-8")
    pub_path.write_text(public_key, encoding="utf-8")
    result = _verify(signed_bundle)
    assert result.exit_code != 0
    assert "Signed bundle_id disagrees with claims and scope" in result.output

    from certifier.bundle import compute_bundle_id
    from certifier.models import NumericClaim, ScopeLock
    original_claim = NumericClaim.model_validate(
        json.loads((signed_bundle / "claims.jsonl").read_text(encoding="utf-8").strip())
    )
    scope = ScopeLock.model_validate(
        json.loads((signed_bundle / "scope_lock.json").read_text(encoding="utf-8"))
    )
    manifest["bundle_id"] = compute_bundle_id([original_claim], scope, "bronze")
    manifest["policy_id"] = "silver"
    signature, _ = sign_manifest(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sig_path.write_text(signature, encoding="utf-8")
    result = _verify(signed_bundle)
    assert result.exit_code != 0
    assert "Signed policy/profile does not match scope lock" in result.output


def test_legacy_signature_remains_valid_but_is_noncertifying(signed_bundle):
    manifest_path = signed_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("claims_sha256")
    manifest["version"] = "tc-bundle-v1"
    signature, public_key = sign_manifest(manifest)
    assert verify_signature(manifest, signature, public_key)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (signed_bundle / "attest" / "signature.ed25519").write_text(signature, encoding="utf-8")
    (signed_bundle / "attest" / "public_key.txt").write_text(public_key, encoding="utf-8")
    result = _verify(signed_bundle)
    assert result.exit_code != 0
    assert "NONCERTIFYING: legacy manifest" in result.output
