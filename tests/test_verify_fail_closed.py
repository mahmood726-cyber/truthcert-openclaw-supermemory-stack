"""Fail-closed verification controls for unsigned synthetic TruthCert bundles."""

import json

import pytest
from click.testing import CliRunner

from cli.tc import cli


@pytest.fixture
def unsigned_bundle(tmp_path):
    bundle = tmp_path / "bundle_unsigned"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"bundle_id": "sha256:synthetic-control", "outcome": "PASS"}),
        encoding="utf-8",
    )
    return bundle


@pytest.mark.parametrize(
    ("extra_flags", "required_message"),
    [
        ([], "Missing signature files"),
        (["--no-check-signature"], "Missing scope lock file"),
        (["--no-check-scope-lock"], "Missing signature files"),
    ],
)
def test_verify_refuses_missing_required_evidence(unsigned_bundle, extra_flags, required_message):
    """Each enabled signature/scope-lock check must fail when its evidence is absent."""
    result = CliRunner().invoke(cli, ["verify", str(unsigned_bundle), *extra_flags])
    assert result.exit_code != 0
    assert required_message in result.output
    assert "Verification PASSED" not in result.output


def test_verify_explicit_opt_out_cannot_rescue_invalid_legacy_fixture(unsigned_bundle):
    """Skipped checks cannot override the independent payload-version refusal."""
    result = CliRunner().invoke(
        cli,
        [
            "verify",
            str(unsigned_bundle),
            "--no-check-signature",
            "--no-check-scope-lock",
        ],
    )
    assert result.exit_code != 0, result.output
    assert "Verification FAILED" in result.output
    assert "NONCERTIFYING: legacy manifest" in result.output
    assert "Verification PASSED" not in result.output
