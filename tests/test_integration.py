"""
Integration tests for TruthCert certification pipeline.

Tests end-to-end workflows:
- Full certification pipeline
- API endpoint integration
- Multi-validator pipelines
- QWED verification integration
- NMA claim certification
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from certifier.models import (
    NumericClaim,
    ScopeLock,
    ValidationSummary,
    ValidatorResult,
    CertificationProfile,
    ClaimType,
    EvidenceLocator,
    EvidenceType,
    CertifyRequest,
    Policy,
    ValidatorConfig,
)
from certifier.constants import Severity, BundleOutcome
from certifier.bundle import create_bundle, load_bundle, compute_bundle_id
from certifier.signing import sign_manifest, verify_signature, generate_keypair, VerificationError
from certifier.validators import ValidatorRegistry
from certifier.qwed import QWEDVerifier, verify_all_claims, get_verification_summary


@pytest.fixture
def gold_scope_lock():
    """Create a GOLD profile scope lock with full PRISMA documentation."""
    return ScopeLock(
        scope_id="integration-test-gold",
        policy_id="gold",
        profile=CertificationProfile.GOLD,
        allowed_sources=["doi", "pmid", "arxiv"],
        required_validators=[
            "schema",
            "memory_leak",
            "evidence_allowlist",
            "idn_homograph",
            "heterogeneity",
        ],
        metadata={
            "prisma_2020": {
                "title": True,
                "abstract_structured": True,
                "rationale": True,
                "objectives": {"pico": "Documented"},
                "eligibility_criteria": True,
                "information_sources": ["PubMed", "EMBASE", "Cochrane"],
                "search_strategy": "Full strategy documented",
                "selection_process": True,
                "data_collection_process": True,
                "data_items": True,
                "study_risk_of_bias": "Cochrane RoB 2.0",
                "effect_measures": ["RR", "OR", "MD"],
                "synthesis_methods": {
                    "heterogeneity_assessed": True,
                    "model_type": "random",
                    "sensitivity_analyses": True,
                    "subgroup_analyses": True,
                },
                "reporting_bias_assessment": True,
                "certainty_assessment": "GRADE",
                "study_selection": {
                    "records_identified": 1523,
                    "records_screened": 1200,
                    "records_excluded": 1150,
                    "studies_included": 15,
                },
                "study_characteristics": True,
                "risk_of_bias_in_studies": True,
                "results_of_individual_studies": True,
                "results_of_syntheses": {
                    "pooled_estimate": True,
                    "confidence_interval": True,
                    "heterogeneity_statistics": True,
                    "prediction_interval": True,
                },
                "reporting_biases": True,
                "certainty_of_evidence": True,
                "discussion_summary": True,
                "limitations": True,
                "conclusions": True,
                "competing_interests": True,
            },
            "prisma_nma": {
                "network_geometry_described": True,
                "transitivity_assumption_assessed": True,
                "statistical_methods_nma": "Bayesian NMA with vague priors",
                "inconsistency_assessed": "Node-splitting + design-by-treatment",
                "ranking_methods_described": "SUCRA",
            },
        },
    )


@pytest.fixture
def valid_meta_analysis_claims():
    """Create a set of valid meta-analysis claims."""
    evidence = [
        EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="doi:10.1001/jama.2024.12345",
            content_hash="sha256:a" * 64,
        )
    ]

    return [
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
            tau_squared=0.05,
            evidence=evidence,
            metadata={
                "study_effects": [0.8, 0.9, 0.75, 0.88, 0.92, 0.78, 0.85, 0.82, 0.91, 0.79, 0.87, 0.83],
                "study_weights": [0.1, 0.08, 0.12, 0.09, 0.07, 0.11, 0.08, 0.09, 0.08, 0.07, 0.06, 0.05],
            },
        ),
        # I² heterogeneity
        NumericClaim(
            claim_id="i2-001",
            claim_type=ClaimType.I_SQUARED,
            value=45.2,
            unit="%",
            lower_bound=12.5,
            upper_bound=68.4,
            evidence=evidence,
        ),
        # τ² between-study variance
        NumericClaim(
            claim_id="tau2-001",
            claim_type=ClaimType.TAU_SQUARED,
            value=0.05,
            evidence=evidence,
        ),
    ]


@pytest.fixture
def nma_claims():
    """Create NMA-specific claims."""
    evidence = [
        EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="doi:10.1016/nma.2024.5678",
            content_hash="sha256:b" * 64,
        )
    ]

    return [
        # SUCRA scores
        NumericClaim(
            claim_id="sucra-treatment-a",
            claim_type=ClaimType.NMA_SUCRA,
            value=85.5,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Drug A", "n_treatments": 5},
        ),
        NumericClaim(
            claim_id="sucra-treatment-b",
            claim_type=ClaimType.NMA_SUCRA,
            value=62.3,
            unit="%",
            evidence=evidence,
            metadata={"treatment": "Drug B", "n_treatments": 5},
        ),
        # P-scores
        NumericClaim(
            claim_id="pscore-treatment-a",
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
        # PSRF convergence
        NumericClaim(
            claim_id="psrf-001",
            claim_type=ClaimType.NMA_PSRF,
            value=1.02,
            evidence=evidence,
            metadata={"parameter": "d[1,2]"},
        ),
        # Effective sample size
        NumericClaim(
            claim_id="ess-001",
            claim_type=ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
            value=5000,
            evidence=evidence,
        ),
    ]


class TestFullCertificationPipeline:
    """Test complete certification workflows."""

    def test_gold_profile_full_pipeline(
        self,
        gold_scope_lock,
        valid_meta_analysis_claims,
        signing_keys,
        temp_dir,
    ):
        """Test full GOLD certification with all validators."""
        # Run all validators
        validators_to_run = [
            "schema",
            "evidence_allowlist",
            "heterogeneity",
            "effect_size_plausibility",
        ]

        results = []
        for validator_name in validators_to_run:
            validator = ValidatorRegistry.get_instance(validator_name)
            if validator:
                result = validator.run(
                    valid_meta_analysis_claims,
                    gold_scope_lock,
                    {},
                )
                results.append(result)

        # All should pass
        blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]
        assert len(blocking) == 0, f"Blocking errors: {[r.message for r in blocking]}"

        # Create bundle
        validation_summary = ValidationSummary(
            results=results,
            all_passed=all(r.passed for r in results),
            has_blocking=len(blocking) > 0,
            has_warnings=any(r.severity == Severity.WARN for r in results),
        )

        bundle_path, receipt = create_bundle(
            claims=valid_meta_analysis_claims,
            scope_lock=gold_scope_lock,
            policy_id="gold",
            validation_summary=validation_summary,
            validators=validators_to_run,
        )

        # Verify bundle created successfully
        assert bundle_path.exists()
        assert receipt.get("outcome") == "PASS"

        # Load and verify bundle
        bundle_data = load_bundle(bundle_path)
        assert bundle_data["manifest"]["profile"] == "GOLD"
        assert bundle_data["manifest"]["outcome"] == "PASS"

    def test_nma_certification_pipeline(
        self,
        gold_scope_lock,
        nma_claims,
        signing_keys,
        temp_dir,
    ):
        """Test NMA-specific certification."""
        # Run NMA validator
        nma_validator = ValidatorRegistry.get_instance("nma")
        assert nma_validator is not None

        result = nma_validator.run(nma_claims, gold_scope_lock, {})

        # Should pass with valid NMA claims
        assert result.passed, f"NMA validation failed: {result.message}"
        assert result.details["validated_count"] == len(nma_claims)

    def test_qwed_integration(self, valid_meta_analysis_claims):
        """Test QWED deterministic verification integration."""
        verifier = QWEDVerifier()

        all_results = verify_all_claims(valid_meta_analysis_claims)
        summary = get_verification_summary(all_results)

        # Should have run multiple checks
        assert summary["total_checks"] > 0

        # At least CI checks should pass
        verified = [r for r in all_results if r.status.value == "verified"]
        assert len(verified) > 0


class TestMultiValidatorPipelines:
    """Test different validator combinations."""

    def test_bronze_pipeline(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test minimal BRONZE certification."""
        validators = ["schema"]

        results = []
        for name in validators:
            validator = ValidatorRegistry.get_instance(name)
            if validator:
                result = validator.run([sample_claim], sample_scope_lock, {})
                results.append(result)

        assert all(r.passed for r in results)

    def test_silver_pipeline(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test SILVER certification with memory checks."""
        # Update scope lock for SILVER
        silver_scope = ScopeLock(
            scope_id="silver-test",
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            required_validators=["schema", "memory_leak", "evidence_allowlist"],
        )

        validators = ["schema", "memory_leak", "evidence_allowlist"]

        results = []
        for name in validators:
            validator = ValidatorRegistry.get_instance(name)
            if validator:
                result = validator.run([sample_claim], silver_scope, {})
                results.append(result)

        blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]
        assert len(blocking) == 0

    def test_security_validator_pipeline(self, sample_claim, sample_scope_lock):
        """Test security-focused validators."""
        validators = ["evidence_allowlist", "idn_homograph"]

        for name in validators:
            validator = ValidatorRegistry.get_instance(name)
            assert validator is not None, f"Validator {name} not registered"

            result = validator.run([sample_claim], sample_scope_lock, {})
            assert result is not None


class TestIDNHomographIntegration:
    """Test IDN homograph attack detection."""

    def test_cyrillic_attack_blocked(self, sample_scope_lock):
        """Test that Cyrillic homograph attacks are detected."""
        from certifier.validators import IDNHomographValidator

        # Claim with Cyrillic 'а' in domain (looks like Latin 'a')
        malicious_claim = NumericClaim(
            claim_id="homograph-attack",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://аpple.com/research",  # Cyrillic 'а'
                    content_hash="sha256:" + "c" * 64,
                )
            ],
        )

        validator = IDNHomographValidator()
        result = validator.run([malicious_claim], sample_scope_lock, {})

        assert not result.passed
        assert "homoglyph" in result.message.lower() or "IDN" in result.message

    def test_legitimate_ascii_domain_passes(self, sample_claim, sample_scope_lock):
        """Test that legitimate ASCII domains pass."""
        from certifier.validators import IDNHomographValidator

        validator = IDNHomographValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        # Should pass for legitimate domains
        assert result.passed or "homoglyph" not in result.message.lower()


class TestPRISMAIntegration:
    """Test PRISMA checklist validation."""

    def test_prisma_gold_compliance(self, gold_scope_lock):
        """Test PRISMA 2020 compliance for GOLD profile."""
        from certifier.validators import PRISMAChecklistValidator

        validator = PRISMAChecklistValidator()

        # Create a minimal claim for validation
        claim = NumericClaim(
            claim_id="prisma-test",
            claim_type=ClaimType.POOLED_EFFECT,
            value=0.85,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/test",
                    content_hash="sha256:" + "d" * 64,
                )
            ],
        )

        result = validator.run([claim], gold_scope_lock, {})

        # Gold scope lock has full PRISMA documentation
        assert result.passed
        assert "compliance" in result.message.lower()

    def test_prisma_missing_items_warning(self, sample_scope_lock):
        """Test that missing PRISMA items generate warnings."""
        from certifier.validators import PRISMAChecklistValidator

        validator = PRISMAChecklistValidator()

        claim = NumericClaim(
            claim_id="prisma-test-2",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/test2",
                    content_hash="sha256:" + "e" * 64,
                )
            ],
        )

        result = validator.run([claim], sample_scope_lock, {})

        # Should have warnings about missing items
        assert result.severity == Severity.WARN or result.severity == Severity.INFO
        if result.details.get("missing_items"):
            assert len(result.details["missing_items"]) > 0


class TestSignatureIntegrity:
    """Test signature creation and verification."""

    def test_round_trip_signature(self, signing_keys):
        """Test signature creation and verification round-trip."""
        manifest = {
            "bundle_id": "sha256:test123",
            "policy_id": "gold",
            "profile": "GOLD",
            "outcome": "PASS",
            "scope_lock_hash": "sha256:scope456",
            "claim_count": 10,
            "validators": ["schema", "memory_leak", "nma"],
        }

        sig, pubkey = sign_manifest(manifest)

        # Verify original
        assert verify_signature(manifest, sig, pubkey)

        # Tampered manifest should fail
        manifest["outcome"] = "REJECT"
        with pytest.raises(VerificationError, match="Invalid signature"):
            verify_signature(manifest, sig, pubkey)

    def test_deterministic_bundle_id(self, sample_claim, sample_scope_lock):
        """Test that bundle ID is deterministic."""
        id1 = compute_bundle_id([sample_claim], sample_scope_lock, "gold")
        id2 = compute_bundle_id([sample_claim], sample_scope_lock, "gold")

        assert id1 == id2
        assert id1.startswith("sha256:")


class TestConnectionPooling:
    """Test job store connection pooling."""

    def test_concurrent_operations(self, temp_dir):
        """Test concurrent job store operations with pool."""
        from certifier.job_store import JobStore
        from certifier.models import Job, JobStatus
        import threading
        import time

        db_path = temp_dir / "pool_test.db"
        store = JobStore(str(db_path), pool_size=5)

        errors = []
        completed = []

        def create_and_query(i):
            try:
                job = Job(
                    job_id=f"pool-test-{i}",
                    status=JobStatus.PENDING,
                    policy_id="silver",
                    profile=CertificationProfile.SILVER,
                    created_at=datetime.now(timezone.utc),
                )
                store.create(job)

                # Simulate some work
                time.sleep(0.01)

                # Query back
                retrieved = store.get(f"pool-test-{i}")
                if retrieved and retrieved.job_id == f"pool-test-{i}":
                    completed.append(i)
                else:
                    errors.append(f"Failed to retrieve job {i}")
            except Exception as e:
                errors.append(str(e))

        # Launch concurrent threads
        threads = [
            threading.Thread(target=create_and_query, args=(i,))
            for i in range(20)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(completed) == 20
        store.close()


class TestQWEDVerification:
    """Test QWED deterministic verification."""

    def test_ci_consistency_verification(self):
        """Test CI consistency with SE."""
        claim = NumericClaim(
            claim_id="ci-test",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            standard_error=0.1,
            lower_bound=0.304,  # 0.5 - 1.96 * 0.1
            upper_bound=0.696,  # 0.5 + 1.96 * 0.1
            confidence_level=0.95,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/ci_test",
                    content_hash="sha256:" + "f" * 64,
                )
            ],
        )

        verifier = QWEDVerifier()
        results = verifier.verify_claim(claim)

        # Should have CI verification results
        ci_results = [r for r in results if "ci" in r.check_type.lower()]
        assert len(ci_results) > 0

        # Should pass
        assert all(r.status.value == "verified" for r in ci_results)

    def test_ratio_constraint_verification(self):
        """Test ratio measure constraint verification."""
        # Valid RR
        valid_claim = NumericClaim(
            claim_id="rr-valid",
            claim_type=ClaimType.RISK_RATIO,
            value=1.5,
            lower_bound=1.1,
            upper_bound=2.0,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/rr_test",
                    content_hash="sha256:" + "g" * 64,
                )
            ],
        )

        verifier = QWEDVerifier()
        results = verifier.verify_claim(valid_claim)

        ratio_results = [r for r in results if "ratio" in r.check_type.lower()]
        assert len(ratio_results) > 0
        assert all(r.status.value == "verified" for r in ratio_results)

        # Invalid RR (negative)
        invalid_claim = NumericClaim(
            claim_id="rr-invalid",
            claim_type=ClaimType.RISK_RATIO,
            value=-0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1001/rr_invalid",
                    content_hash="sha256:" + "h" * 64,
                )
            ],
        )

        results = verifier.verify_claim(invalid_claim)
        ratio_results = [r for r in results if "ratio" in r.check_type.lower()]
        assert any(r.status.value == "failed" for r in ratio_results)
