"""
Tests for FastAPI endpoints.
"""

import os
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from certifier.main import app
from certifier.models import (
    NumericClaim,
    EvidenceLocator,
    EvidenceType,
    ClaimType,
    ScopeLock,
    CertificationProfile,
)
from certifier.constants import BundleOutcome, Severity


# Get the project root directory (where policies folder is located)
PROJECT_ROOT = Path(__file__).parent.parent

# API version prefix for all versioned endpoints
API_V1 = "/api/v1"


@pytest.fixture
def client(temp_dir, monkeypatch, signing_keys):
    """Create FastAPI test client with proper test environment."""
    # Change to project root so policies can be found
    monkeypatch.chdir(PROJECT_ROOT)

    # Set up bundle directory in temp location
    bundle_dir = temp_dir / "bundles"
    bundle_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("TRUTHCERT_BUNDLE_DIR", str(bundle_dir))

    # Disable rate limiting for tests by setting enabled=False on the limiter
    from certifier.main import limiter
    limiter.enabled = False

    return TestClient(app)


@pytest.fixture
def valid_claim_data(sample_evidence):
    """Create valid claim data for API requests."""
    return {
        "claim_id": "test-api-claim-001",
        "claim_type": "effect_size",
        "value": 0.45,
        "unit": "d",
        "precision": 2,
        "confidence_level": 0.95,
        "lower_bound": 0.25,
        "upper_bound": 0.65,
        "evidence": [
            {
                "source_type": "oa_document",
                "uri": "https://example.com/paper.pdf",
                "content_hash": "sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "page": 5,
                "section": "Results",
            }
        ],
        "provenance": {"method": "extraction"},
    }


@pytest.fixture
def memory_leak_claim_data():
    """Create claim data that triggers memory leak detection."""
    return {
        "claim_id": "memory-leak-claim-001",
        "claim_type": "sample_size",
        "value": 100,
        "evidence": [
            {
                "source_type": "oa_document",
                "uri": "memory:recall-123",  # Memory URI triggers leak
                "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


@pytest.fixture
def default_scope_lock():
    """Create a default scope lock for API tests."""
    return {
        "scope_id": "api-test-scope-001",
        "policy_id": "bronze",
        "profile": "BRONZE",
        "allowed_sources": ["oa_document", "fixture"],
        "required_validators": ["schema", "no_naked_numbers", "memory_leak"],
    }


class TestHealthEndpoint:
    """Test GET /health endpoint."""

    def test_health_returns_200(self, client):
        """Test health endpoint returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client):
        """Test health response has expected structure."""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "timestamp" in data

        assert data["status"] == "healthy"
        assert data["service"] == "truthcert"

    def test_health_timestamp_is_recent(self, client):
        """Test health timestamp is recent (within 1 minute)."""
        response = client.get("/health")
        data = response.json()

        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = abs((now - timestamp).total_seconds())

        assert diff < 60  # Within 1 minute


class TestCertifyEndpoint:
    """Test POST /api/v1/certify endpoint."""

    def test_certify_valid_claim(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test certifying a valid claim returns PASS."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
                "metadata": {"test": True},
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "bundle_id" in data
        assert "outcome" in data
        assert "validation_summary" in data
        assert data["bundle_id"].startswith("sha256:")

    def test_certify_memory_leak_claim_rejected(self, client, memory_leak_claim_data, default_scope_lock, signing_keys):
        """Test that claims citing memory are rejected."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [memory_leak_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Memory leak should cause rejection
        assert data["outcome"] == "REJECT"
        assert data["validation_summary"]["has_blocking"] is True

    def test_certify_empty_claims_rejected(self, client, signing_keys):
        """Test that empty claims list is rejected."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [],
                "policy_id": "bronze",
            },
        )

        # Pydantic validation should fail for empty claims
        assert response.status_code == 422

    def test_certify_missing_evidence_rejected(self, client, signing_keys):
        """Test that claims without evidence are rejected."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [
                    {
                        "claim_id": "no-evidence",
                        "claim_type": "effect_size",
                        "value": 0.5,
                        "evidence": [],
                    }
                ],
                "policy_id": "bronze",
            },
        )

        # Pydantic validation should fail for no evidence
        assert response.status_code == 422

    def test_certify_invalid_policy_returns_404(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test that invalid policy ID returns 404."""
        scope_lock = default_scope_lock.copy()
        scope_lock["policy_id"] = "nonexistent_policy"
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "nonexistent_policy",
                "scope_lock": scope_lock,
            },
        )

        assert response.status_code == 404

    def test_certify_too_many_claims_rejected(self, client, valid_claim_data, default_scope_lock, signing_keys, monkeypatch):
        """Test that exceeding max claims is rejected."""
        # Set very low max claims
        monkeypatch.setenv("TRUTHCERT_MAX_CLAIMS", "1")

        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data, valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )

        assert response.status_code == 400

    def test_certify_with_scope_lock(self, client, valid_claim_data, signing_keys):
        """Test certifying with explicit scope lock."""
        scope_lock = {
            "scope_id": "test-scope-001",
            "policy_id": "bronze",
            "profile": "BRONZE",
            "allowed_sources": ["oa_document"],
            "required_validators": ["schema", "memory_leak"],
        }

        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": scope_lock,
            },
        )

        assert response.status_code == 200

    def test_certify_response_has_receipt_on_pass(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test that PASS outcome includes receipt."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )

        data = response.json()

        if data["outcome"] == "PASS":
            assert data.get("receipt") is not None
        # For REJECT, receipt may be None


class TestVerifyEndpoint:
    """Test POST /api/v1/verify endpoint."""

    def test_verify_nonexistent_bundle_returns_404(self, client, signing_keys):
        """Test verifying nonexistent bundle returns 404."""
        response = client.post(
            f"{API_V1}/verify",
            json={
                "bundle_id": "sha256:nonexistent1234567890",
            },
        )

        assert response.status_code == 404

    def test_verify_invalid_bundle_id_format(self, client, signing_keys):
        """Test verifying invalid bundle ID format is rejected."""
        response = client.post(
            f"{API_V1}/verify",
            json={
                "bundle_id": "../etc/passwd",  # Path traversal attempt
            },
        )

        assert response.status_code == 400

    def test_verify_existing_bundle(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test verifying an existing bundle."""
        # First create a bundle
        certify_response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )
        bundle_id = certify_response.json()["bundle_id"]

        # Now verify it
        verify_response = client.post(
            f"{API_V1}/verify",
            json={
                "bundle_id": bundle_id,
                "check_signature": True,
                "check_scope_lock": True,
            },
        )

        assert verify_response.status_code == 200
        data = verify_response.json()

        assert "bundle_id" in data
        assert "valid" in data
        assert data["bundle_id"] == bundle_id

    def test_verify_response_structure(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test verify response has expected structure."""
        # Create bundle first
        certify_response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )
        bundle_id = certify_response.json()["bundle_id"]

        # Verify
        verify_response = client.post(
            f"{API_V1}/verify",
            json={"bundle_id": bundle_id},
        )

        data = verify_response.json()

        assert "bundle_id" in data
        assert "valid" in data
        assert "signature_valid" in data
        assert "scope_lock_valid" in data
        assert "schema_valid" in data
        assert "errors" in data
        assert "warnings" in data

    @pytest.mark.parametrize(
        ("check_signature", "check_scope_lock"),
        [(False, False), (False, True), (True, False)],
    )
    def test_skipped_integrity_checks_never_report_valid(
        self, client, valid_claim_data, default_scope_lock, signing_keys,
        check_signature, check_scope_lock,
    ):
        """A syntactically valid real bundle is not certified by skipped controls."""
        certified = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )
        assert certified.status_code == 200
        bundle_id = certified.json()["bundle_id"]
        response = client.post(
            f"{API_V1}/verify",
            json={
                "bundle_id": bundle_id,
                "check_signature": check_signature,
                "check_scope_lock": check_scope_lock,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["schema_valid"] is True
        assert result["valid"] is False
        if not check_signature:
            assert result["signature_valid"] is None
            assert "NONCERTIFYING: signature verification skipped" in result["warnings"]
        if not check_scope_lock:
            assert result["scope_lock_valid"] is None
            assert "NONCERTIFYING: scope lock verification skipped" in result["warnings"]


class TestBundlesEndpoint:
    """Test /api/v1/bundles endpoints."""

    def test_list_bundles_empty(self, client, signing_keys):
        """Test listing bundles when none exist."""
        response = client.get(f"{API_V1}/bundles")

        assert response.status_code == 200
        data = response.json()

        assert "bundles" in data
        assert "count" in data
        assert "limit" in data
        assert "offset" in data

    def test_list_bundles_with_pagination(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test listing bundles with pagination."""
        # Create a few bundles
        for i in range(3):
            claim_data = valid_claim_data.copy()
            claim_data["claim_id"] = f"test-claim-{i}"
            client.post(
                f"{API_V1}/certify",
                json={
                    "claims": [claim_data],
                    "policy_id": "bronze",
                    "scope_lock": default_scope_lock,
                },
            )

        # List with pagination
        response = client.get(f"{API_V1}/bundles?limit=2&offset=0")

        assert response.status_code == 200
        data = response.json()

        assert data["limit"] == 2
        assert data["offset"] == 0

    def test_get_bundle_by_id(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test getting a specific bundle by ID."""
        # Create bundle
        certify_response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )
        bundle_id = certify_response.json()["bundle_id"]

        # Get bundle
        response = client.get(f"{API_V1}/bundles/{bundle_id}")

        assert response.status_code == 200
        data = response.json()

        assert "manifest" in data

    def test_get_nonexistent_bundle_returns_404(self, client, signing_keys):
        """Test getting nonexistent bundle returns 404."""
        response = client.get(f"{API_V1}/bundles/sha256:nonexistent123456")

        assert response.status_code == 404

    def test_get_bundle_with_path_traversal_rejected(self, client, signing_keys):
        """Test path traversal in bundle ID is rejected."""
        response = client.get(f"{API_V1}/bundles/../../etc/passwd")

        # Path traversal should be rejected (400) or not found (404)
        assert response.status_code in [400, 404]

    def test_get_bundle_receipt(self, client, valid_claim_data, default_scope_lock, signing_keys):
        """Test getting bundle receipt."""
        # Create bundle
        certify_response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )
        bundle_id = certify_response.json()["bundle_id"]

        # Get receipt
        response = client.get(f"{API_V1}/bundles/{bundle_id}/receipt.json")

        assert response.status_code == 200


class TestJobsEndpoint:
    """Test /api/v1/jobs endpoints."""

    def test_submit_job(self, client, signing_keys):
        """Test submitting a certification job."""
        response = client.post(
            f"{API_V1}/jobs",
            json={
                "policy_id": "bronze",
                "metadata": {"test": True},
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "job" in data
        assert "job_id" in data["job"]
        assert data["job"]["status"] == "pending"

    def test_get_job_status(self, client, signing_keys):
        """Test getting job status."""
        # Submit job
        submit_response = client.post(
            f"{API_V1}/jobs",
            json={"policy_id": "bronze"},
        )
        job_id = submit_response.json()["job"]["job_id"]

        # Get status
        response = client.get(f"{API_V1}/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()

        assert data["job"]["job_id"] == job_id

    def test_get_nonexistent_job_returns_404(self, client, signing_keys):
        """Test getting nonexistent job returns 404."""
        response = client.get(f"{API_V1}/jobs/nonexistent-job-id")

        assert response.status_code == 404

    def test_submit_job_invalid_policy_returns_404(self, client, signing_keys):
        """Test submitting job with invalid policy returns 404."""
        response = client.post(
            f"{API_V1}/jobs",
            json={
                "policy_id": "nonexistent_policy",
            },
        )

        assert response.status_code == 404


class TestErrorResponses:
    """Test error response formats."""

    def test_400_error_format(self, client, valid_claim_data, default_scope_lock, signing_keys, monkeypatch):
        """Test 400 error response format."""
        monkeypatch.setenv("TRUTHCERT_MAX_CLAIMS", "1")

        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": [valid_claim_data, valid_claim_data],
                "policy_id": "bronze",
                "scope_lock": default_scope_lock,
            },
        )

        assert response.status_code == 400
        data = response.json()

        assert "error" in data or "detail" in data

    def test_404_error_format(self, client, signing_keys):
        """Test 404 error response format."""
        response = client.get(f"{API_V1}/bundles/sha256:nonexistent123456")

        assert response.status_code == 404
        data = response.json()

        assert "error" in data or "detail" in data

    def test_422_validation_error_format(self, client, signing_keys):
        """Test 422 validation error response format."""
        response = client.post(
            f"{API_V1}/certify",
            json={
                "claims": "not_a_list",  # Invalid type
                "policy_id": "bronze",
            },
        )

        assert response.status_code == 422
        data = response.json()

        # FastAPI validation error format
        assert "detail" in data


class TestRateLimiting:
    """Test rate limiting (basic tests)."""

    def test_health_not_rate_limited(self, client):
        """Test that health endpoint allows many requests."""
        for _ in range(10):
            response = client.get("/health")
            assert response.status_code == 200


class TestContentTypeHandling:
    """Test content type handling."""

    def test_json_content_type_required(self, client, signing_keys):
        """Test that JSON content type is handled correctly."""
        response = client.post(
            f"{API_V1}/certify",
            content="not json",
            headers={"Content-Type": "text/plain"},
        )

        # Should fail due to invalid content type or body
        assert response.status_code in [400, 415, 422]

    def test_response_content_type_is_json(self, client):
        """Test that responses have JSON content type."""
        response = client.get("/health")

        assert "application/json" in response.headers.get("content-type", "")


def test_verify_api_refuses_modified_signed_claim_payload(
    client, valid_claim_data, default_scope_lock, signing_keys,
):
    """A still-valid signed manifest must not authenticate altered CI bounds."""
    created = client.post(
        f"{API_V1}/certify",
        json={
            "claims": [valid_claim_data],
            "policy_id": "bronze",
            "scope_lock": default_scope_lock,
        },
    )
    assert created.status_code == 200, created.text
    bundle_id = created.json()["bundle_id"]
    before = client.post(f"{API_V1}/verify", json={"bundle_id": bundle_id})
    assert before.status_code == 200 and before.json()["valid"] is True, before.text

    bundle_path = Path(os.environ["TRUTHCERT_BUNDLE_DIR"]) / (
        "bundle_" + bundle_id.removeprefix("sha256:")[:16]
    )
    claims_path = bundle_path / "claims.jsonl"
    original = json.loads(claims_path.read_text(encoding="utf-8").strip())
    original["lower_bound"] = -100
    claims_path.write_text(json.dumps(original) + "\n", encoding="utf-8")

    result = client.post(f"{API_V1}/verify", json={"bundle_id": bundle_id})
    assert result.status_code == 200
    assert result.json()["valid"] is False
    assert "Signed claims payload digest mismatch" in result.json()["errors"]
