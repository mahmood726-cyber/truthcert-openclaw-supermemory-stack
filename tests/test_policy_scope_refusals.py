"""Synthetic policy-path and scope-lock refusal regressions.

Policy names must never select arbitrary files, and a caller cannot certify
under a different policy or profile from the signed scope declaration.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from certifier import main
from certifier.errors import ValidationError


@pytest.mark.parametrize(
    "candidate",
    [
        "../secrets",
        "../../policies/silver",
        r"..\\secrets",
        "/tmp/silver",
        "bronze/../silver",
        "bronze.json",
        ".",
        "",
        "brοnze",  # non-ASCII lookalike: Greek omicron
        "x" * 129,
    ],
)
def test_unsafe_policy_identifiers_refuse_before_filesystem_access(candidate):
    with pytest.raises(ValidationError, match="Invalid policy ID format") as error:
        main.load_policy(candidate)
    assert error.value.status_code == 400


def test_policy_file_identity_mismatch_refuses_and_does_not_cache(tmp_path, monkeypatch):
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "synthetic.json").write_text(
        json.dumps({
            "policy_id": "other",
            "profile": "BRONZE",
            "validators": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "_policy_cache", {})

    with pytest.raises(ValidationError, match="Policy file identifier") as error:
        main.load_policy("synthetic")
    assert error.value.status_code == 400
    assert "synthetic" not in main._policy_cache


@pytest.mark.parametrize(
    ("locked_policy", "locked_profile"),
    [("silver", "BRONZE"), ("bronze", "SILVER")],
)
def test_certification_refuses_scope_policy_or_profile_mismatch(
    locked_policy, locked_profile, monkeypatch,
):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setattr(main, "_policy_cache", {})
    monkeypatch.setattr(main.limiter, "enabled", False)

    def unexpected_publication(*args, **kwargs):
        raise AssertionError("Mismatched scope must not reach bundle creation")

    monkeypatch.setattr(main, "create_bundle", unexpected_publication)
    response = TestClient(main.app).post(
        "/api/v1/certify",
        json={
            "policy_id": "bronze",
            "claims": [],
            "scope_lock": {
                "scope_id": "synthetic-scope",
                "policy_id": locked_policy,
                "profile": locked_profile,
                "allowed_sources": ["oa_document"],
                "required_validators": [],
            },
        },
    )
    assert response.status_code == 400
    assert "Scope lock policy or profile" in response.json()["message"]


def test_canonical_policy_name_still_loads(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setattr(main, "_policy_cache", {})
    policy = main.load_policy("bronze")
    assert policy.policy_id == "bronze"
    assert policy.profile.value == "BRONZE"
