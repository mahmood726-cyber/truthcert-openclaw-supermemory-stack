"""
Tests for PCN renderer.
"""

import pytest
from pathlib import Path

from renderer.pcn_renderer import PCNRenderer, RenderResult
from certifier.models import (
    NumericClaim,
    ScopeLock,
    ValidationSummary,
    ValidatorResult,
    CertificationProfile,
)
from certifier.bundle import create_bundle
from certifier.constants import Severity


class TestPCNRenderer:
    """Test PCN renderer functionality."""

    def test_render_pass_bundle(self, sample_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test rendering a PASS bundle."""
        # Create PASS bundle
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

        bundle_path, _ = create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=["schema"],
        )

        # Render
        renderer = PCNRenderer()
        result = renderer.render_bundle(bundle_path)

        assert result.success
        assert "pcn-certified" in result.content
        assert str(sample_claim.value) in result.content

    def test_refuse_reject_bundle(self, memory_claim, sample_scope_lock, signing_keys, temp_dir):
        """Test that REJECT bundles are refused."""
        # Create REJECT bundle
        validation_summary = ValidationSummary(
            results=[
                ValidatorResult(
                    validator_name="memory_leak",
                    passed=False,
                    severity=Severity.BLOCK,
                    message="Memory leak detected",
                ),
            ],
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

        # Attempt to render - should be refused
        renderer = PCNRenderer()
        result = renderer.render_bundle(bundle_path)

        assert not result.success
        assert "REFUSED" in result.error
        assert "REJECT" in result.error or "PASS" in result.error

    def test_refuse_uncertified_number(self):
        """Test explicit refusal of uncertified numbers."""
        renderer = PCNRenderer()
        result = renderer.refuse_uncertified(0.45)

        assert not result.success
        assert "REFUSED" in result.error
        assert "uncertified" in result.error.lower()

    def test_render_with_confidence_interval(self, sample_scope_lock, signing_keys, temp_dir):
        """Test rendering claim with confidence interval."""
        from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType

        claim = NumericClaim(
            claim_id="ci-claim",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            unit="d",
            lower_bound=0.3,
            upper_bound=0.7,
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validation_summary = ValidationSummary(
            results=[],
            all_passed=True,
            has_blocking=False,
            has_warnings=False,
        )

        bundle_path, _ = create_bundle(
            claims=[claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=[],
        )

        renderer = PCNRenderer()
        result = renderer.render_bundle(bundle_path)

        assert result.success
        assert "0.3" in result.content
        assert "0.7" in result.content
        assert "pcn-ci" in result.content

    def test_html_escaping(self, sample_scope_lock, signing_keys, temp_dir):
        """Test that HTML is properly escaped."""
        from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType

        # Create claim with potentially dangerous content
        claim = NumericClaim(
            claim_id="<script>alert('xss')</script>",
            claim_type=ClaimType.EFFECT_SIZE,
            value=0.5,
            unit="<img src=x onerror=alert(1)>",
            evidence=[
                EvidenceLocator(
                    source_type=EvidenceType.OA_DOCUMENT,
                    uri="https://example.com/paper.pdf",
                    content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                )
            ],
        )

        validation_summary = ValidationSummary(
            results=[],
            all_passed=True,
            has_blocking=False,
            has_warnings=False,
        )

        bundle_path, _ = create_bundle(
            claims=[claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=validation_summary,
            validators=[],
        )

        renderer = PCNRenderer()
        result = renderer.render_bundle(bundle_path)

        assert result.success
        # Should be escaped
        assert "<script>" not in result.content
        assert "&lt;script&gt;" in result.content
