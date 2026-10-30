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
