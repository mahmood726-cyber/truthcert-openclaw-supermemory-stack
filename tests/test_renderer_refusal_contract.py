"""Synthetic checks: proof rendering must never invent evidence or accept errors."""

from certifier.bundle import create_bundle
from certifier.models import ValidationSummary
from renderer.pcn_renderer import PCNRenderer


def test_qwed_receives_original_claim_and_evidence(sample_claim):
    renderer = PCNRenderer()
    seen = []

    def inspect(claim):
        seen.append(claim)
        return []

    renderer.qwed_verifier.verify_claim = inspect
    renderer.verify_claim_qwed(sample_claim.model_dump(mode="json"))
    assert len(seen) == 1
    assert seen[0].model_dump() == sample_claim.model_dump()


def test_malformed_claim_does_not_receive_qwed_verification():
    passed, details = PCNRenderer().verify_claim_qwed({"claim_type": "invalid"})
    assert passed is False
    assert details


def test_verifier_exception_refuses_and_redacts_internals(sample_claim, monkeypatch):
    renderer = PCNRenderer()

    def unavailable(_claim):
        raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")

    monkeypatch.setattr(renderer.qwed_verifier, "verify_claim", unavailable)
    passed, details = renderer.verify_claim_qwed(sample_claim.model_dump(mode="json"))
    assert passed is False
    assert "SYNTHETIC_PRIVATE_MARKER" not in str(details)


def test_proof_rendering_refuses_failed_verification(
    sample_claim, sample_scope_lock, signing_keys, monkeypatch
):
    bundle, _ = create_bundle(
        claims=[sample_claim],
        scope_lock=sample_scope_lock,
        policy_id="silver",
        validation_summary=ValidationSummary(
            results=[], all_passed=True, has_blocking=False, has_warnings=False
        ),
        validators=[],
    )
    renderer = PCNRenderer()
    monkeypatch.setattr(renderer, "verify_claim_qwed", lambda _: (False, [{"error": "failed"}]))
    result = renderer.render_with_proof(bundle)
    assert result.success is False
    assert result.content == ""
    assert "REFUSED" in result.error
