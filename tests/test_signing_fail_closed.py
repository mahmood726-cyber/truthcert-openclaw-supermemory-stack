"""Signing failures must not be laundered into successful certification receipts."""

import pytest

from certifier import bundle
from certifier.models import ValidationSummary


def test_requested_signature_failure_propagates_without_pass_receipt(
    monkeypatch, sample_claim, sample_scope_lock,
):
    """An exception during signing must abort instead of returning a PASS manifest."""
    def reject_signature(*_args, **_kwargs):
        raise RuntimeError("synthetic signing backend failure")

    monkeypatch.setattr(bundle, "write_attestation", reject_signature)
    summary = ValidationSummary(
        results=[],
        all_passed=True,
        has_blocking=False,
        has_warnings=False,
    )
    with pytest.raises(RuntimeError, match="synthetic signing backend failure"):
        bundle.create_bundle(
            claims=[sample_claim],
            scope_lock=sample_scope_lock,
            policy_id="silver",
            validation_summary=summary,
            validators=[],
            sign=True,
        )


def test_failed_attestation_never_publishes_a_pass_manifest(
    monkeypatch, temp_dir, sample_claim, sample_scope_lock,
):
    """Even a partly written attestation must remain private and be removed."""
    from certifier.constants import ENV_BUNDLE_DIR

    bundle_root = temp_dir / "atomic-bundles"
    monkeypatch.setenv(ENV_BUNDLE_DIR, str(bundle_root))

    def fail_after_partial_attestation(stage_path, *_args, **_kwargs):
        (stage_path / "attest" / "signature.ed25519").write_text(
            "synthetic-partial-signature", encoding="utf-8",
        )
        raise RuntimeError("synthetic signing interrupted")

    monkeypatch.setattr(bundle, "write_attestation", fail_after_partial_attestation)
    summary = ValidationSummary(
        results=[], all_passed=True, has_blocking=False, has_warnings=False,
    )
    with pytest.raises(RuntimeError, match="synthetic signing interrupted"):
        bundle.create_bundle(
            claims=[sample_claim], scope_lock=sample_scope_lock,
            policy_id="silver", validation_summary=summary,
            validators=[], sign=True,
        )
    assert not list(bundle_root.glob("bundle_*"))
    assert not list(bundle_root.glob(".tc-stage-*"))


def test_duplicate_bundle_cannot_replace_existing_signature(
    monkeypatch, temp_dir, sample_claim, sample_scope_lock, signing_keys,
):
    """A repeat invocation must not overwrite an existing signed artifact."""
    from certifier.constants import ENV_BUNDLE_DIR

    bundle_root = temp_dir / "immutable-bundles"
    monkeypatch.setenv(ENV_BUNDLE_DIR, str(bundle_root))
    summary = ValidationSummary(
        results=[], all_passed=True, has_blocking=False, has_warnings=False,
    )
    kwargs = {
        "claims": [sample_claim],
        "scope_lock": sample_scope_lock,
        "policy_id": "silver",
        "validation_summary": summary,
        "validators": [],
        "sign": True,
    }
    published_path, _receipt = bundle.create_bundle(**kwargs)
    signature_path = published_path / "attest" / "signature.ed25519"
    original_signature = signature_path.read_bytes()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        bundle.create_bundle(**kwargs)
    assert signature_path.read_bytes() == original_signature
    assert (published_path / "manifest.json").exists()
    assert not list(bundle_root.glob(".tc-stage-*"))
