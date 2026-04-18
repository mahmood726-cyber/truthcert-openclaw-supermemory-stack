"""
Tests for end-to-end certification.
"""

import pytest
from pathlib import Path

from certifier.models import (
    NumericClaim,
    ScopeLock,
    ValidationSummary,
    ValidatorResult,
    CertificationProfile,
)
from certifier.bundle import (
    create_bundle,
    load_bundle,
    compute_bundle_id,
)
from certifier.signing import verify_signature
from certifier.constants import Severity, BundleOutcome


class TestBundleCreation:
    """Test bundle creation."""

    def test_create_pass_bundle(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test creating a PASS bundle."""
        # All validators pass
        validation_summary = ValidationSummary(
            results=[
                ValidatorResult(
                    validator_name="schema",
                    passed=True,
                    severity=Severity.INFO,
                    message="Schema valid",
                ),
                ValidatorResult(
                    validator_name="memory_leak",
                    passed=True,
                    severity=Severity.INFO,
                    message="No memory leaks",
                ),
            ],
            all_passed=True,
            has_blocking=False,
            has_warnings=False,
        )

        bundle_path, receipt = create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=["schema", "memory_leak"],
        )

        assert bundle_path.exists()
        assert receipt.get("outcome") == "PASS"
        assert receipt.get("bundle_id")

    def test_create_reject_bundle(self, memory_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test creating a REJECT bundle when memory leak detected."""
        # Memory leak validator fails
        validation_summary = ValidationSummary(
            results=[
                ValidatorResult(
                    validator_name="schema",
                    passed=True,
                    severity=Severity.INFO,
                    message="Schema valid",
                ),
                ValidatorResult(
                    validator_name="memory_leak",
                    passed=False,
                    severity=Severity.BLOCK,
                    message="MEMORY LEAK DETECTED",
                    details={"memory_leaks": [{"claim_id": "memory-claim-001"}]},
                ),
            ],
            all_passed=False,
            has_blocking=True,
            has_warnings=False,
            blocking_count=1,
        )

        bundle_path, result = create_bundle(
            claims=[memory_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=["schema", "memory_leak"],
        )

        assert bundle_path.exists()
        # Receipt may have outcome or manifest does
        bundle_data = load_bundle(bundle_path)
        assert bundle_data["manifest"]["outcome"] == "REJECT"

    def test_bundle_id_deterministic(self, sample_claim, sample_scope_lock):
        """Test that bundle ID computation is deterministic."""
        id1 = compute_bundle_id([sample_claim], sample_scope_lock, "silver")
        id2 = compute_bundle_id([sample_claim], sample_scope_lock, "silver")

        assert id1 == id2
        assert id1.startswith("sha256:")


class TestBundleVerification:
    """Test bundle verification."""

    def test_verify_valid_bundle(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test verifying a valid bundle."""
        validation_summary = ValidationSummary(
            results=[
                ValidatorResult(
                    validator_name="schema",
                    passed=True,
                    severity=Severity.INFO,
                    message="OK",
                ),
            ],
            all_passed=True,
            has_blocking=False,
            has_warnings=False,
        )

        bundle_path, receipt = create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=["schema"],
        )

        # Load and verify
        bundle_data = load_bundle(bundle_path)
        manifest = bundle_data["manifest"]

        # Verify signature
        attest_path = bundle_path / "attest"
        sig_file = attest_path / "signature.ed25519"
        pubkey_file = attest_path / "public_key.txt"

        signature_b64 = sig_file.read_text().strip()
        public_key_b64 = pubkey_file.read_text().strip()

        # Should not raise
        verify_signature(manifest, signature_b64, public_key_b64)

    def test_verify_scope_lock_hash(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test scope lock hash verification."""
        validation_summary = ValidationSummary(
            results=[],
            all_passed=True,
            has_blocking=False,
            has_warnings=False,
        )

        bundle_path, receipt = create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=[],
        )

        bundle_data = load_bundle(bundle_path)
        manifest = bundle_data["manifest"]
        scope_lock_data = bundle_data["scope_lock"]

        # Recompute hash
        loaded_scope = ScopeLock(**scope_lock_data)
        computed_hash = loaded_scope.compute_hash()

        assert computed_hash == manifest["scope_lock_hash"]


class TestEndToEndCertification:
    """Test end-to-end certification flow."""

    def test_valid_claim_produces_pass(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test that valid claim produces PASS bundle."""
        from certifier.validators import ValidatorRegistry

        # Run validators
        pipeline = [
            ValidatorRegistry.get_instance("schema"),
            ValidatorRegistry.get_instance("no_naked_numbers"),
            ValidatorRegistry.get_instance("memory_leak"),
        ]

        results = []
        for validator in pipeline:
            if validator:
                result = validator.run([sample_claim], sample_scope_lock, {})
                results.append(result)

        # All should pass
        blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]
        assert len(blocking) == 0

        # Create bundle
        validation_summary = ValidationSummary(
            results=results,
            all_passed=len(blocking) == 0,
            has_blocking=len(blocking) > 0,
            has_warnings=False,
        )

        bundle_path, receipt = create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=[v.name for v in pipeline if v],
        )

        bundle_data = load_bundle(bundle_path)
        assert bundle_data["manifest"]["outcome"] == "PASS"

    def test_memory_claim_produces_reject(self, memory_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test that memory-citing claim produces REJECT bundle."""
        from certifier.validators import ValidatorRegistry

        # Run memory leak validator
        validator = ValidatorRegistry.get_instance("memory_leak")
        result = validator.run([memory_claim], sample_scope_lock, {})

        # Should fail
        assert not result.passed
        assert result.severity == Severity.BLOCK

        # Create bundle
        validation_summary = ValidationSummary(
            results=[result],
            all_passed=False,
            has_blocking=True,
            has_warnings=False,
            blocking_count=1,
        )

        bundle_path, _ = create_bundle(
            claims=[memory_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=["memory_leak"],
        )

        bundle_data = load_bundle(bundle_path)
        assert bundle_data["manifest"]["outcome"] == "REJECT"


class TestSignatureRoundTrip:
    """Test signature creation and verification round-trip."""

    def test_signature_creation_and_verification(self, signing_keys):
        """Test that signatures can be created and verified."""
        from certifier.signing import sign_manifest, verify_signature

        manifest_data = {
            "bundle_id": "sha256:test123",
            "policy_id": "silver",
            "profile": "SILVER",
            "outcome": "PASS",
            "scope_lock_hash": "sha256:scope123",
            "claim_count": 5,
            "validators": ["schema", "memory_leak"],
        }

        # Sign
        signature_b64, public_key_b64 = sign_manifest(manifest_data)

        # Verify
        result = verify_signature(manifest_data, signature_b64, public_key_b64)
        assert result is True

    def test_tampered_manifest_fails_verification(self, signing_keys):
        """Test that tampered manifest fails signature verification."""
        from certifier.signing import sign_manifest, verify_signature, VerificationError

        manifest_data = {
            "bundle_id": "sha256:test123",
            "policy_id": "silver",
            "profile": "SILVER",
            "outcome": "PASS",
            "scope_lock_hash": "sha256:scope123",
            "claim_count": 5,
            "validators": ["schema", "memory_leak"],
        }

        # Sign
        signature_b64, public_key_b64 = sign_manifest(manifest_data)

        # Tamper with manifest
        manifest_data["outcome"] = "REJECT"

        # Verify should fail
        with pytest.raises(VerificationError):
            verify_signature(manifest_data, signature_b64, public_key_b64)


class TestNewValidatorsIntegration:
    """Test integration of new validators."""

    def test_evidence_allowlist_blocks_file_scheme(self, sample_scope_lock):
        """Test that file:// scheme is blocked."""
        from certifier.validators import EvidenceAllowlistValidator
        from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType

        claim = NumericClaim(
            claim_id="file-scheme",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="file:///etc/passwd",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed
        assert result.severity == Severity.BLOCK

    def test_heterogeneity_validator_detects_invalid_i_squared(self, sample_scope_lock):
        """Test that I² > 100% is detected."""
        from certifier.validators import HeterogeneityValidator
        from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType

        claim = NumericClaim(
            claim_id="invalid-i2",
            claim_type=ClaimType.HETEROGENEITY,
            value=150.0,  # Invalid: I² cannot exceed 100%
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1234/meta.2024",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = HeterogeneityValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed

    def test_effect_size_validator_detects_negative_rr(self, sample_scope_lock):
        """Test that negative risk ratio is detected."""
        from certifier.validators import EffectSizePlausibilityValidator
        from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType

        claim = NumericClaim(
            claim_id="negative-rr",
            claim_type=ClaimType.RISK_RATIO,
            value=-0.5,  # Invalid: RR must be positive
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1234/rct.2024",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EffectSizePlausibilityValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed
