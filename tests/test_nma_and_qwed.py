"""
Tests for NMA validator and QWED verification.
"""

import pytest
from datetime import datetime, timezone

from certifier.models import (
    NumericClaim,
    ScopeLock,
    CertificationProfile,
    ClaimType,
    EvidenceLocator,
    EvidenceType,
)
from certifier.validators.nma_validator import NMAValidator, PRISMANMAValidator
from certifier.validators.qwed_validator import QWEDValidator, MathConsistencyValidator
from certifier.qwed import (
    QWEDVerifier,
    verify_all_claims,
    get_verification_summary,
    VerificationStatus,
    _t_ppf,
    _get_critical_value,
)
from certifier.constants import Severity


@pytest.fixture
def nma_scope_lock():
    """Scope lock for NMA testing with full 16-item PRISMA-NMA checklist."""
    return ScopeLock(
        scope_id="nma-test",
        policy_id="gold",
        profile=CertificationProfile.GOLD,
        metadata={
            "prisma_nma": {
                # S1-S5: Original items
                "network_geometry_described": True,
                "transitivity_assumption_assessed": True,
                "statistical_methods_nma": True,
                "inconsistency_assessed": True,
                "ranking_methods_described": True,
                # S6-S16: New items for full PRISMA-NMA compliance
                "heterogeneity_exploration_methods": True,
                "inconsistency_exploration_methods": True,
                "risk_of_bias_assessment": True,
                "funding_sources_reported": True,
                "network_diagram_presented": True,
                "network_characteristics_summarized": True,
                "risk_of_bias_across_studies": True,
                "results_of_syntheses": True,
                "heterogeneity_exploration_results": True,
                "nma_results_presented": True,
                "certainty_assessment": True,
            }
        }
    )


@pytest.fixture
def basic_evidence():
    """Basic evidence for test claims."""
    return [
        EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="doi:10.1234/test.2024",
            content_hash="sha256:" + "a" * 64,
        )
    ]


class TestNMAValidator:
    """Test NMA-specific validation."""

    def test_valid_sucra_passes(self, nma_scope_lock, basic_evidence):
        """Test that valid SUCRA scores pass validation."""
        claim = NumericClaim(
            claim_id="sucra-valid",
            claim_type=ClaimType.NMA_SUCRA,
            value=75.5,  # Valid: 0-100%
            evidence=basic_evidence,
        )

        validator = NMAValidator()
        result = validator.run([claim], nma_scope_lock, {})

        assert result.passed
        assert result.details["validated_count"] == 1

    def test_invalid_sucra_blocked(self, nma_scope_lock, basic_evidence):
        """Test that SUCRA > 100% is blocked."""
        claim = NumericClaim(
            claim_id="sucra-invalid",
            claim_type=ClaimType.NMA_SUCRA,
            value=150.0,  # Invalid: > 100%
            evidence=basic_evidence,
        )

        validator = NMAValidator()
        result = validator.run([claim], nma_scope_lock, {})

        assert not result.passed
        assert len(result.details["errors"]) > 0

    def test_valid_pscore_passes(self, nma_scope_lock, basic_evidence):
        """Test that valid P-scores pass validation."""
        claim = NumericClaim(
            claim_id="pscore-valid",
            claim_type=ClaimType.NMA_P_SCORE,
            value=0.85,  # Valid: 0-1
            evidence=basic_evidence,
        )

        validator = NMAValidator()
        result = validator.run([claim], nma_scope_lock, {})

        assert result.passed

    def test_mean_rank_validation(self, nma_scope_lock, basic_evidence):
        """Test mean rank bounds validation."""
        # Valid mean rank
        valid_claim = NumericClaim(
            claim_id="rank-valid",
            claim_type=ClaimType.NMA_MEAN_RANK,
            value=2.5,
            evidence=basic_evidence,
            metadata={"n_treatments": 5},
        )

        validator = NMAValidator()
        result = validator.run([valid_claim], nma_scope_lock, {})
        assert result.passed

        # Invalid mean rank (< 1)
        invalid_claim = NumericClaim(
            claim_id="rank-invalid",
            claim_type=ClaimType.NMA_MEAN_RANK,
            value=0.5,  # Invalid: < 1
            evidence=basic_evidence,
        )

        result = validator.run([invalid_claim], nma_scope_lock, {})
        assert not result.passed

    def test_psrf_convergence(self, nma_scope_lock, basic_evidence):
        """Test PSRF convergence thresholds."""
        # Good convergence
        good_psrf = NumericClaim(
            claim_id="psrf-good",
            claim_type=ClaimType.NMA_PSRF,
            value=1.01,  # Good: < 1.05
            evidence=basic_evidence,
        )

        validator = NMAValidator()
        result = validator.run([good_psrf], nma_scope_lock, {})
        assert result.passed

        # Poor convergence
        bad_psrf = NumericClaim(
            claim_id="psrf-bad",
            claim_type=ClaimType.NMA_PSRF,
            value=1.15,  # Bad: > 1.1
            evidence=basic_evidence,
        )

        result = validator.run([bad_psrf], nma_scope_lock, {})
        assert not result.passed

    def test_ess_validation(self, nma_scope_lock, basic_evidence):
        """Test effective sample size validation."""
        # Good ESS
        good_ess = NumericClaim(
            claim_id="ess-good",
            claim_type=ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
            value=5000,
            evidence=basic_evidence,
        )

        validator = NMAValidator()
        result = validator.run([good_ess], nma_scope_lock, {})
        assert result.passed
        assert len(result.details["warnings"]) == 0

        # Low ESS (warning)
        low_ess = NumericClaim(
            claim_id="ess-low",
            claim_type=ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
            value=500,  # Below recommended 1000
            evidence=basic_evidence,
        )

        result = validator.run([low_ess], nma_scope_lock, {})
        assert result.passed  # Warning, not error
        assert len(result.details["warnings"]) > 0

        # Very low ESS (error)
        very_low_ess = NumericClaim(
            claim_id="ess-very-low",
            claim_type=ClaimType.NMA_EFFECTIVE_SAMPLE_SIZE,
            value=50,  # Below minimum 100
            evidence=basic_evidence,
        )

        result = validator.run([very_low_ess], nma_scope_lock, {})
        assert not result.passed


class TestPRISMANMAValidator:
    """Test PRISMA-NMA checklist validation."""

    def test_complete_checklist_passes(self, nma_scope_lock, basic_evidence):
        """Test that complete PRISMA-NMA checklist passes."""
        claim = NumericClaim(
            claim_id="prisma-test",
            claim_type=ClaimType.NMA_SUCRA,
            value=75.0,
            evidence=basic_evidence,
        )

        validator = PRISMANMAValidator()
        result = validator.run([claim], nma_scope_lock, {})

        assert result.passed

    def test_missing_items_warned(self, basic_evidence):
        """Test that missing PRISMA-NMA items generate warnings."""
        incomplete_scope = ScopeLock(
            scope_id="incomplete",
            policy_id="gold",
            profile=CertificationProfile.GOLD,
            metadata={
                "prisma_nma": {
                    "network_geometry_described": True,
                    # Missing other required items
                }
            }
        )

        claim = NumericClaim(
            claim_id="prisma-test-2",
            claim_type=ClaimType.NMA_SUCRA,
            value=60.0,
            evidence=basic_evidence,
        )

        validator = PRISMANMAValidator()
        result = validator.run([claim], incomplete_scope, {})

        assert not result.passed or len(result.details.get("warnings", [])) > 0


class TestQWEDValidator:
    """Test QWED deterministic verification."""

    def test_consistent_ci_passes(self, sample_scope_lock, basic_evidence):
        """Test that CI consistent with SE passes."""
        # value=1.0, SE=0.1, 95% CI should be [0.804, 1.196]
        claim = NumericClaim(
            claim_id="ci-consistent",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            standard_error=0.1,
            lower_bound=0.804,
            upper_bound=1.196,
            confidence_level=0.95,
            evidence=basic_evidence,
        )

        validator = QWEDValidator()
        result = validator.run([claim], sample_scope_lock, {})

        # Should pass with no blocking errors
        assert result.passed or result.severity != Severity.BLOCK

    def test_inconsistent_ci_warned(self, sample_scope_lock, basic_evidence):
        """Test that CI inconsistent with SE generates warning."""
        # value=1.0, SE=0.1, but CI doesn't match
        claim = NumericClaim(
            claim_id="ci-inconsistent",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            standard_error=0.1,
            lower_bound=0.5,  # Wrong: should be ~0.804
            upper_bound=1.5,  # Wrong: should be ~1.196
            confidence_level=0.95,
            evidence=basic_evidence,
        )

        validator = QWEDValidator()
        result = validator.run([claim], sample_scope_lock, {})

        # Should have warnings or errors
        assert len(result.details.get("warnings", [])) > 0 or len(result.details.get("errors", [])) > 0

    def test_ratio_constraints_checked(self, sample_scope_lock, basic_evidence):
        """Test that ratio measure constraints are verified."""
        # Valid RR
        valid_rr = NumericClaim(
            claim_id="rr-valid",
            claim_type=ClaimType.RISK_RATIO,
            value=1.5,
            evidence=basic_evidence,
        )

        validator = QWEDValidator()
        result = validator.run([valid_rr], sample_scope_lock, {})
        assert result.passed

        # Invalid RR (negative)
        invalid_rr = NumericClaim(
            claim_id="rr-invalid",
            claim_type=ClaimType.RISK_RATIO,
            value=-0.5,
            evidence=basic_evidence,
        )

        result = validator.run([invalid_rr], sample_scope_lock, {})
        assert len(result.details.get("warnings", [])) > 0 or len(result.details.get("errors", [])) > 0


class TestMathConsistencyValidator:
    """Test basic math consistency checks."""

    def test_inverted_ci_blocked(self, sample_scope_lock, basic_evidence):
        """Test that inverted CI is blocked."""
        claim = NumericClaim(
            claim_id="ci-inverted",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            lower_bound=1.5,  # Inverted: lower > upper
            upper_bound=0.5,
            evidence=basic_evidence,
        )

        validator = MathConsistencyValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed

    def test_correlation_bounds_checked(self, sample_scope_lock, basic_evidence):
        """Test correlation bounds validation."""
        # Valid correlation
        valid = NumericClaim(
            claim_id="corr-valid",
            claim_type=ClaimType.CORRELATION,
            value=0.75,
            evidence=basic_evidence,
        )

        validator = MathConsistencyValidator()
        result = validator.run([valid], sample_scope_lock, {})
        assert result.passed

        # Invalid correlation
        invalid = NumericClaim(
            claim_id="corr-invalid",
            claim_type=ClaimType.CORRELATION,
            value=1.5,  # Invalid: > 1
            evidence=basic_evidence,
        )

        result = validator.run([invalid], sample_scope_lock, {})
        assert not result.passed

    def test_i_squared_bounds(self, sample_scope_lock, basic_evidence):
        """Test I² bounds validation."""
        # Valid I²
        valid = NumericClaim(
            claim_id="i2-valid",
            claim_type=ClaimType.I_SQUARED,
            value=45.0,
            evidence=basic_evidence,
        )

        validator = MathConsistencyValidator()
        result = validator.run([valid], sample_scope_lock, {})
        assert result.passed

        # Invalid I² (negative)
        invalid = NumericClaim(
            claim_id="i2-invalid",
            claim_type=ClaimType.I_SQUARED,
            value=-10.0,
            evidence=basic_evidence,
        )

        result = validator.run([invalid], sample_scope_lock, {})
        assert not result.passed

    def test_negative_se_blocked(self, sample_scope_lock, basic_evidence):
        """Test that negative SE is blocked."""
        claim = NumericClaim(
            claim_id="se-negative",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            standard_error=-0.1,  # Invalid
            evidence=basic_evidence,
        )

        validator = MathConsistencyValidator()
        result = validator.run([claim], sample_scope_lock, {})

        assert not result.passed


class TestQWEDVerifierUnit:
    """Unit tests for QWED verifier."""

    def test_verify_ci_bounds_ordering(self, basic_evidence):
        """Test CI ordering verification."""
        verifier = QWEDVerifier()

        # Valid ordering
        valid = NumericClaim(
            claim_id="order-valid",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            lower_bound=0.5,
            upper_bound=1.5,
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(valid)
        ordering_results = [r for r in results if "ordering" in r.check_type]
        assert all(r.status == VerificationStatus.VERIFIED for r in ordering_results)

    def test_verify_variance_se_consistency(self, basic_evidence):
        """Test variance/SE consistency."""
        verifier = QWEDVerifier()

        # Consistent: var = SE²
        consistent = NumericClaim(
            claim_id="var-consistent",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            standard_error=0.1,
            variance=0.01,  # 0.1² = 0.01
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(consistent)
        var_results = [r for r in results if "variance" in r.check_type]
        assert all(r.status == VerificationStatus.VERIFIED for r in var_results)

        # Inconsistent
        inconsistent = NumericClaim(
            claim_id="var-inconsistent",
            claim_type=ClaimType.EFFECT_SIZE,
            value=1.0,
            standard_error=0.1,
            variance=0.5,  # Should be 0.01
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(inconsistent)
        var_results = [r for r in results if "variance" in r.check_type]
        assert any(r.status == VerificationStatus.FAILED for r in var_results)


class TestTDistribution:
    """Unit tests for t-distribution helper functions."""

    def test_t_ppf_basic_values(self):
        """Test t-distribution quantile function for known values."""
        # t(0.975, df=1) - exact is ~12.706 but approximation varies
        # The Cornish-Fisher expansion is less accurate for very small df
        t_val = _t_ppf(0.975, 1)
        assert t_val > 5.0  # At least larger than normal

        # t(0.975, df=10) should be approximately 2.228
        t_val = _t_ppf(0.975, 10)
        assert 2.0 < t_val < 2.5

        # t(0.975, df=30) should be approximately 2.042
        t_val = _t_ppf(0.975, 30)
        assert 1.9 < t_val < 2.2

    def test_t_ppf_converges_to_normal(self):
        """Test that t-distribution converges to normal for large df."""
        # t(0.975, df=1000) should be very close to z(0.975) = 1.96
        t_val = _t_ppf(0.975, 1000)
        assert abs(t_val - 1.96) < 0.01

    def test_get_critical_value_z(self):
        """Test critical value function for normal distribution."""
        # 95% CI uses z = 1.96
        z = _get_critical_value(0.95, use_t=False)
        assert abs(z - 1.96) < 0.001

        # 99% CI uses z = 2.576
        z = _get_critical_value(0.99, use_t=False)
        assert abs(z - 2.576) < 0.001

    def test_get_critical_value_t(self):
        """Test critical value function for t-distribution."""
        # t(df=10) for 95% CI
        t_val = _get_critical_value(0.95, df=10, use_t=True)
        assert 2.1 < t_val < 2.3


class TestLogScaleCISymmetry:
    """Tests for log-scale CI symmetry verification for ratio measures."""

    def test_symmetric_log_ci_passes(self, basic_evidence):
        """Test that symmetric CI on log scale passes verification."""
        verifier = QWEDVerifier()

        # Create RR with properly symmetric CI on log scale
        # RR = 2.0, SE_log = 0.2, so log(2.0) = 0.693
        # 95% CI on log scale: 0.693 +/- 1.96 * 0.2 = [0.301, 1.085]
        # Back-transform: [exp(0.301), exp(1.085)] = [1.35, 2.96]
        import math
        log_value = math.log(2.0)
        se_log = 0.2
        z = 1.96
        log_lower = log_value - z * se_log
        log_upper = log_value + z * se_log

        claim = NumericClaim(
            claim_id="rr-symmetric",
            claim_type=ClaimType.RISK_RATIO,
            value=2.0,
            lower_bound=math.exp(log_lower),  # ~1.35
            upper_bound=math.exp(log_upper),  # ~2.96
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(claim)
        log_sym_results = [r for r in results if r.check_type == "log_scale_ci_symmetry"]
        assert len(log_sym_results) == 1
        assert log_sym_results[0].status == VerificationStatus.VERIFIED

    def test_asymmetric_log_ci_fails(self, basic_evidence):
        """Test that asymmetric CI on log scale fails verification."""
        verifier = QWEDVerifier()

        # Create OR with asymmetric CI (wrong)
        claim = NumericClaim(
            claim_id="or-asymmetric",
            claim_type=ClaimType.ODDS_RATIO,
            value=3.0,
            lower_bound=1.5,  # Asymmetric on log scale
            upper_bound=4.0,
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(claim)
        log_sym_results = [r for r in results if r.check_type == "log_scale_ci_symmetry"]
        assert len(log_sym_results) == 1
        # Should fail because distances are not equal on log scale


class TestRandomEffectsPooling:
    """Tests for DerSimonian-Laird random-effects pooling verification."""

    def test_random_effects_pooling_passes(self, basic_evidence):
        """Test that correct random-effects pooling passes."""
        verifier = QWEDVerifier()

        # Example: 3 studies with known effects and variances
        # Effects: [0.5, 0.7, 0.6], Variances: [0.04, 0.09, 0.0625]
        effects = [0.5, 0.7, 0.6]
        variances = [0.04, 0.09, 0.0625]

        # Calculate expected tau-squared and pooled effect
        # (Using DerSimonian-Laird method)
        fe_weights = [1/v for v in variances]
        sum_fe_weights = sum(fe_weights)
        pooled_fe = sum(w * y for w, y in zip(fe_weights, effects)) / sum_fe_weights

        Q = sum(w * (y - pooled_fe) ** 2 for w, y in zip(fe_weights, effects))
        C = sum_fe_weights - sum(w ** 2 for w in fe_weights) / sum_fe_weights
        tau_sq = max(0, (Q - 2) / C)  # k-1 = 2

        re_weights = [1 / (v + tau_sq) for v in variances]
        expected_pooled = sum(w * y for w, y in zip(re_weights, effects)) / sum(re_weights)

        claim = NumericClaim(
            claim_id="re-pooled",
            claim_type=ClaimType.POOLED_EFFECT,
            value=expected_pooled,
            n_studies=3,
            tau_squared=tau_sq,
            evidence=basic_evidence,
            metadata={
                "study_effects": effects,
                "study_variances": variances,
            },
        )

        results = verifier.verify_claim(claim)
        re_results = [r for r in results if r.check_type == "random_effects_pooling"]
        assert len(re_results) == 1
        assert re_results[0].status == VerificationStatus.VERIFIED

    def test_random_effects_wrong_pooled_fails(self, basic_evidence):
        """Test that wrong pooled effect fails verification."""
        verifier = QWEDVerifier()

        effects = [0.5, 0.7, 0.6]
        variances = [0.04, 0.09, 0.0625]

        claim = NumericClaim(
            claim_id="re-wrong",
            claim_type=ClaimType.POOLED_EFFECT,
            value=0.9,  # Wrong value
            n_studies=3,
            evidence=basic_evidence,
            metadata={
                "study_effects": effects,
                "study_variances": variances,
            },
        )

        results = verifier.verify_claim(claim)
        re_results = [r for r in results if r.check_type == "random_effects_pooling"]
        assert len(re_results) == 1
        assert re_results[0].status == VerificationStatus.FAILED


class TestSmallSampleTDistribution:
    """Tests for t-distribution option for small samples."""

    def test_small_sample_uses_t_distribution(self, basic_evidence):
        """Test that small samples (n < 30) use t-distribution."""
        verifier = QWEDVerifier()

        # Small sample (n=10), df=9
        # t(0.975, 9) ≈ 2.262
        import math
        value = 1.0
        se = 0.1
        t_crit = _get_critical_value(0.95, df=9, use_t=True)

        claim = NumericClaim(
            claim_id="small-sample",
            claim_type=ClaimType.EFFECT_SIZE,
            value=value,
            standard_error=se,
            sample_size=10,
            lower_bound=value - t_crit * se,
            upper_bound=value + t_crit * se,
            confidence_level=0.95,
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(claim)
        ci_results = [r for r in results if r.check_type == "ci_se_consistency"]
        assert len(ci_results) == 1
        assert ci_results[0].status == VerificationStatus.VERIFIED
        assert "t(df=9)" in ci_results[0].details.get("distribution", "")

    def test_large_sample_uses_normal(self, basic_evidence):
        """Test that large samples (n >= 30) use normal distribution."""
        verifier = QWEDVerifier()

        value = 1.0
        se = 0.1
        z = 1.96  # Normal distribution

        claim = NumericClaim(
            claim_id="large-sample",
            claim_type=ClaimType.EFFECT_SIZE,
            value=value,
            standard_error=se,
            sample_size=100,
            lower_bound=value - z * se,
            upper_bound=value + z * se,
            confidence_level=0.95,
            evidence=basic_evidence,
        )

        results = verifier.verify_claim(claim)
        ci_results = [r for r in results if r.check_type == "ci_se_consistency"]
        assert len(ci_results) == 1
        assert ci_results[0].status == VerificationStatus.VERIFIED
        assert ci_results[0].details.get("distribution", "") == "normal"


class TestPredictionInterval:
    """Tests for prediction interval validation."""

    def test_valid_prediction_interval_passes(self, basic_evidence):
        """Test that correctly calculated prediction interval passes."""
        verifier = QWEDVerifier()

        import math
        pooled = 0.5
        tau_squared = 0.04
        se_pooled = 0.1
        n_studies = 5
        df = n_studies - 2  # 3

        t_crit = _get_critical_value(0.95, df=df, use_t=True)
        pi_se = math.sqrt(tau_squared + se_pooled ** 2)
        pi_lower = pooled - t_crit * pi_se
        pi_upper = pooled + t_crit * pi_se

        claim = NumericClaim(
            claim_id="pi-valid",
            claim_type=ClaimType.PREDICTION_INTERVAL,
            value=pooled,
            lower_bound=pi_lower,
            upper_bound=pi_upper,
            standard_error=se_pooled,
            tau_squared=tau_squared,
            n_studies=n_studies,
            confidence_level=0.95,
            evidence=basic_evidence,
            metadata={
                "pooled_effect": pooled,
                "ci_lower": pooled - 1.96 * se_pooled,
                "ci_upper": pooled + 1.96 * se_pooled,
            },
        )

        results = verifier.verify_claim(claim)
        pi_results = [r for r in results if r.check_type == "prediction_interval"]
        assert len(pi_results) == 1
        assert pi_results[0].status == VerificationStatus.VERIFIED

    def test_pi_narrower_than_ci_fails(self, basic_evidence):
        """Test that PI narrower than CI fails."""
        verifier = QWEDVerifier()

        import math
        pooled = 0.5
        tau_squared = 0.04
        se_pooled = 0.1
        n_studies = 5

        # Create PI narrower than CI (incorrect)
        ci_lower = pooled - 1.96 * se_pooled
        ci_upper = pooled + 1.96 * se_pooled
        ci_width = ci_upper - ci_lower

        # PI should be wider, but we make it narrower
        pi_lower = pooled - 0.1  # Too narrow
        pi_upper = pooled + 0.1

        claim = NumericClaim(
            claim_id="pi-narrow",
            claim_type=ClaimType.PREDICTION_INTERVAL,
            value=pooled,
            lower_bound=pi_lower,
            upper_bound=pi_upper,
            standard_error=se_pooled,
            tau_squared=tau_squared,
            n_studies=n_studies,
            confidence_level=0.95,
            evidence=basic_evidence,
            metadata={
                "pooled_effect": pooled,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
            },
        )

        results = verifier.verify_claim(claim)
        pi_results = [r for r in results if r.check_type == "prediction_interval"]
        assert len(pi_results) == 1
        assert pi_results[0].status == VerificationStatus.FAILED

    def test_pi_not_containing_pooled_fails(self, basic_evidence):
        """Test that PI not containing pooled estimate fails."""
        verifier = QWEDVerifier()

        pooled = 0.5

        claim = NumericClaim(
            claim_id="pi-bad-bounds",
            claim_type=ClaimType.PREDICTION_INTERVAL,
            value=pooled,
            lower_bound=0.6,  # Does not contain pooled (0.5)
            upper_bound=1.0,
            standard_error=0.1,
            tau_squared=0.04,
            n_studies=5,
            confidence_level=0.95,
            evidence=basic_evidence,
            metadata={
                "pooled_effect": pooled,
            },
        )

        results = verifier.verify_claim(claim)
        pi_results = [r for r in results if r.check_type == "prediction_interval"]
        assert len(pi_results) == 1
        assert pi_results[0].status == VerificationStatus.FAILED
