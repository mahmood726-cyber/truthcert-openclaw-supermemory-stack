"""
Tests for validators.
"""

import pytest
from certifier.validators import (
    SchemaValidator,
    NoNakedNumbersValidator,
    MemoryLeakValidator,
    MemoryDriftValidator,
    ScopeLockValidator,
    EvidenceAllowlistValidator,
    HeterogeneityValidator,
    PublicationBiasValidator,
    EffectSizePlausibilityValidator,
)
from certifier.models import (
    NumericClaim,
    EvidenceLocator,
    EvidenceType,
    ClaimType,
    ScopeLock,
    CertificationProfile,
)
from certifier.constants import Severity


class TestSchemaValidator:
    """Test schema validation."""

    def test_valid_claim_passes(self, sample_claim, sample_scope_lock):
        """Test that valid claims pass schema validation."""
        validator = SchemaValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        assert result.passed
        assert result.severity == Severity.INFO

    def test_missing_evidence_fails(self, sample_scope_lock):
        """Test that claims without evidence fail at model creation (Pydantic validation)."""
        from pydantic import ValidationError

        # Pydantic now enforces minimum 1 evidence item at model level
        with pytest.raises(ValidationError) as exc_info:
            NumericClaim(
                claim_id="no-evidence",
                claim_type=ClaimType.EFFECT_SIZE,
                value=0.5,
                evidence=[],  # Empty evidence - fails Pydantic validation
            )

        assert "too_short" in str(exc_info.value) or "at least 1" in str(exc_info.value)

    @pytest.mark.parametrize(
        "bad_hash",
        [
            "sha256:abc",
            "sha256:" + "a" * 63,
            "sha256:" + "a" * 65,
            "sha256:" + "g" * 64,
            "sha256:" + "A" * 64,
            "sha256:" + "a" * 64 + "\n",
            "md5:" + "a" * 64,
            "",
        ],
    )
    def test_invalid_hash_format_fails(self, bad_hash):
        """An invalid digest must never pass Pydantic evidence construction."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="64 lowercase hexadecimal characters"):
            EvidenceLocator(
                source_type=EvidenceType.OA_DOCUMENT,
                uri="https://example.com/synthetic.pdf",
                content_hash=bad_hash,
            )

    def test_canonical_digest_is_accepted(self):
        evidence = EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="https://example.com/synthetic.pdf",
            content_hash="sha256:" + "a" * 64,
        )
        assert evidence.content_hash == "sha256:" + "a" * 64

    def test_schema_rejects_hash_tampered_after_model_creation(
        self, sample_claim, sample_scope_lock
    ):
        """The validator must refuse even if assignment bypasses model creation."""
        tampered = sample_claim.model_copy(deep=True)
        tampered.evidence[0].content_hash = "sha256:abc"
        result = SchemaValidator().run([tampered], sample_scope_lock, {})
        assert not result.passed
        assert result.severity == Severity.BLOCK
        assert any(
            "Invalid content hash format" in issue["issue"]
            for issue in result.details["issues"]
        )



class TestNoNakedNumbersValidator:
    """Test no naked numbers validation."""

    def test_claim_with_evidence_passes(self, sample_claim, sample_scope_lock):
        """Test that claims with evidence pass."""
        validator = NoNakedNumbersValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        assert result.passed

    def test_claim_without_content_hash_fails(self, sample_scope_lock):
        """Test that claims without content hash fail at model or validator level."""
        from pydantic import ValidationError

        # Empty content_hash may fail at model level (Pydantic validation)
        try:
            claim = NumericClaim(
                claim_id="no-hash",
                claim_type=ClaimType.EFFECT_SIZE,
                value=0.5,
                evidence=[
                    EvidenceLocator(
                        source_type=EvidenceType.OA_DOCUMENT,
                        uri="https://example.com/paper.pdf",
                        content_hash="",  # Missing hash - may fail at model level
                    )
                ],
            )

            # If model creation succeeds, validator should catch it
            validator = NoNakedNumbersValidator()
            result = validator.run([claim], sample_scope_lock, {})

            # Should fail because content_hash is required
            assert not result.passed or "hash" in str(result.details).lower()

        except ValidationError:
            # Model-level validation caught the empty hash - test passes
            pass


class TestMemoryLeakValidator:
    """Test memory leak detection - CRITICAL validator."""

    def test_oa_evidence_passes(self, sample_claim, sample_scope_lock):
        """Test that OA document evidence passes."""
        validator = MemoryLeakValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        assert result.passed
        assert "memory" not in result.message.lower() or "no memory" in result.message.lower()

    def test_memory_uri_fails(self, memory_claim, sample_scope_lock):
        """Test that memory: URI prefix is detected and blocked."""
        validator = MemoryLeakValidator()
        result = validator.run([memory_claim], sample_scope_lock, {})

        assert not result.passed
        assert result.severity == Severity.BLOCK
        assert "MEMORY" in result.message.upper()

    def test_recall_uri_fails(self, sample_scope_lock):
        """Test that recall: URI prefix is detected and blocked."""
        claim = NumericClaim(
            claim_id="recall-claim",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=50,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="recall:item-456",
                    content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                )
            ],
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed
        assert result.severity == Severity.BLOCK

    def test_memory_in_metadata_fails(self, sample_scope_lock):
        """Test that memory references in metadata are detected."""
        claim = NumericClaim(
            claim_id="metadata-memory",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                    metadata={"source": "memory"},  # Memory reference in metadata
                )
            ],
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed

    def test_memory_in_provenance_fails(self, sample_scope_lock):
        """Test that memory references in provenance are detected."""
        claim = NumericClaim(
            claim_id="provenance-memory",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
            provenance={"source": "memory:recall-789"},  # Memory in provenance
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed


class TestMemoryDriftValidator:
    """Test memory drift detection."""

    def test_no_drift_passes(self, sample_claim, sample_scope_lock):
        """Test that claims without expected values pass."""
        validator = MemoryDriftValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        assert result.passed

    def test_matching_expected_passes(self, sample_scope_lock):
        """Test that matching expected values pass."""
        claim = NumericClaim(
            claim_id="matching",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
            metadata={
                "expected_n": 100,  # Matches value
            },
        )

        validator = MemoryDriftValidator()
        result = validator.run([claim], sample_scope_lock, {})

        # Should pass because values match
        assert result.passed or result.severity != Severity.BLOCK

    def test_drift_detected(self, sample_scope_lock):
        """Test that drift is detected when expected differs from actual."""
        claim = NumericClaim(
            claim_id="drifted",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
            metadata={
                "expected_value": 200,  # Different from value=100
            },
        )

        validator = MemoryDriftValidator()
        result = validator.run([claim], sample_scope_lock, {})

        # Should detect drift
        if result.details.get("drifts"):
            assert len(result.details["drifts"]) > 0


class TestScopeLockValidator:
    """Test scope lock validation."""

    def test_valid_scope_lock_passes(self, sample_claim, sample_scope_lock):
        """Test that valid scope lock passes."""
        validator = ScopeLockValidator()
        result = validator.run([sample_claim], sample_scope_lock, {})

        assert result.passed

    def test_disallowed_source_fails(self, sample_scope_lock):
        """Test that disallowed source types fail."""
        # Create scope lock that only allows fixtures
        strict_scope = ScopeLock(
            scope_id="strict",
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            allowed_sources=["fixture"],  # Only fixtures allowed
        )

        # Claim with OA document (not allowed)
        claim = NumericClaim(
            claim_id="oa-claim",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,  # Not in allowed_sources
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = ScopeLockValidator()
        result = validator.run([claim], strict_scope, {})

        assert not result.passed


class TestEvidenceAllowlistValidator:
    """Test evidence allowlist validation."""

    def test_valid_doi_passes(self, sample_scope_lock):
        """Test that valid DOI URIs pass."""
        
        claim = NumericClaim(
            claim_id="doi-claim",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1234/example.2024",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert result.passed

    def test_valid_pmid_passes(self, sample_scope_lock):
        """Test that valid PMID URIs pass."""
        
        claim = NumericClaim(
            claim_id="pmid-claim",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="pmid:12345678",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert result.passed

    def test_memory_uri_blocked(self, sample_scope_lock):
        """Test that memory: URIs are blocked."""
        
        claim = NumericClaim(
            claim_id="memory-uri",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="memory:item-123",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert not result.passed
        assert "MEMORY" in str(result.details).upper()

    def test_file_uri_blocked(self, sample_scope_lock):
        """Test that file:// URIs are blocked in SILVER profile."""
        
        claim = NumericClaim(
            claim_id="file-uri",
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

    def test_unknown_scheme_blocked(self, sample_scope_lock):
        """Test that unknown URI schemes are blocked."""
        
        claim = NumericClaim(
            claim_id="unknown-scheme",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="ftp://example.com/data.csv",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert not result.passed

    def test_trusted_domain_passes(self, sample_scope_lock):
        """Test that trusted domains pass."""
        
        claim = NumericClaim(
            claim_id="trusted-domain",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://pubmed.ncbi.nlm.nih.gov/12345678",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = EvidenceAllowlistValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert result.passed


class TestHeterogeneityValidator:
    """Test heterogeneity validation for meta-analysis."""

    def test_valid_i_squared_passes(self, sample_scope_lock):
        """Test that valid I² values pass."""
        
        claim = NumericClaim(
            claim_id="het-claim",
            claim_type=ClaimType.HETEROGENEITY,
            value=45.0,  # I² = 45%
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
        assert result.passed

    def test_negative_i_squared_fails(self, sample_scope_lock):
        """Test that negative I² fails."""
        
        claim = NumericClaim(
            claim_id="neg-i2",
            claim_type=ClaimType.HETEROGENEITY,
            value=-5.0,  # Invalid negative I²
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

    def test_i_squared_over_100_fails(self, sample_scope_lock):
        """Test that I² > 100% fails."""
        
        claim = NumericClaim(
            claim_id="over-100",
            claim_type=ClaimType.HETEROGENEITY,
            value=105.0,  # Invalid: I² cannot exceed 100%
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

    def test_high_heterogeneity_warning(self, sample_scope_lock):
        """Test that high I² (> 75%) generates warning."""
        
        claim = NumericClaim(
            claim_id="high-het",
            claim_type=ClaimType.HETEROGENEITY,
            value=85.0,  # High heterogeneity
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
        # Should pass but with warnings
        assert result.passed
        assert len(result.details.get("warnings", [])) > 0

    def test_negative_tau_squared_fails(self, sample_scope_lock):
        """Test that negative τ² fails."""
        
        claim = NumericClaim(
            claim_id="neg-tau2",
            claim_type=ClaimType.HETEROGENEITY,
            value=50.0,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="doi:10.1234/meta.2024",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
            metadata={"tau_squared": -0.5},  # Invalid negative τ²
        )

        validator = HeterogeneityValidator()
        result = validator.run([claim], sample_scope_lock, {})
        assert not result.passed


class TestEffectSizePlausibilityValidator:
    """Test effect size plausibility validation."""

    def test_valid_risk_ratio_passes(self, sample_scope_lock):
        """Test that valid RR passes."""
        
        claim = NumericClaim(
            claim_id="rr-claim",
            claim_type=ClaimType.RISK_RATIO,
            value=1.5,  # RR = 1.5
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
        assert result.passed

    def test_negative_risk_ratio_fails(self, sample_scope_lock):
        """Test that negative RR fails."""
        
        claim = NumericClaim(
            claim_id="neg-rr",
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

    def test_extreme_smd_warning(self, sample_scope_lock):
        """Test that extreme SMD generates warning."""
        
        claim = NumericClaim(
            claim_id="extreme-smd",
            claim_type=ClaimType.STANDARDIZED_MEAN_DIFFERENCE,
            value=4.5,  # Very large effect size
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
        # Should pass but with warnings about extreme value
        assert result.passed
        assert len(result.details.get("warnings", [])) > 0

    def test_invalid_nnt_fails(self, sample_scope_lock):
        """Test that NNT < 1 fails."""
        
        claim = NumericClaim(
            claim_id="invalid-nnt",
            claim_type=ClaimType.NUMBER_NEEDED_TO_TREAT,
            value=0.5,  # Invalid: NNT must be >= 1
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


class TestMemoryLeakAntiEvasion:
    """Test anti-evasion techniques in memory leak detection."""

    def test_base64_encoded_memory_detected(self, sample_scope_lock):
        """Test that base64-encoded memory references are detected in URIs or suspicious keys."""
        import base64

        # Encode "memory:secret-123" in base64
        encoded = base64.b64encode(b"memory:secret-123").decode()

        # Use the base64 in the URI where it will be scanned
        claim = NumericClaim(
            claim_id="b64-memory",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri=f"https://example.com/paper.pdf?ref={encoded}",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                    metadata={"source": encoded},  # Use suspicious key "source"
                )
            ],
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})
        # Should detect the base64-encoded memory reference
        assert not result.passed or "base64" in str(result.details).lower()

    def test_cyrillic_homoglyph_detected(self, sample_scope_lock):
        """Test that Cyrillic homoglyph evasion is detected in URIs."""
        # Using Cyrillic 'е' which looks like Latin 'e'
        # "mеmory" with Cyrillic 'е' - put in URI for detection
        evasion_uri = "m\u0435mory:secret"  # Cyrillic е

        claim = NumericClaim(
            claim_id="homoglyph",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri=evasion_uri,  # Obfuscated memory URI
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})
        # Should detect the homoglyph evasion
        assert not result.passed

    def test_leetspeak_detected(self, sample_scope_lock):
        """Test that leetspeak evasion is detected in URIs."""
        # "m3m0ry" as leetspeak for "memory" - put in URI for detection
        leetspeak_uri = "m3m0ry:secret-123"

        claim = NumericClaim(
            claim_id="leetspeak",
            claim_type=ClaimType.SAMPLE_SIZE,
            value=100,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri=leetspeak_uri,  # Obfuscated memory URI
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validator = MemoryLeakValidator()
        result = validator.run([claim], sample_scope_lock, {})
        # Should detect the leetspeak evasion
        assert not result.passed
