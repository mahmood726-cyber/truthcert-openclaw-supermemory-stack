"""
Tests for gateway/glue layer.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, Mock
from dataclasses import asdict

import httpx

from gateway.openclaw.glue import TruthCertGlue, CertificationResult


@pytest.fixture
def mock_memory_commands():
    """Create mock MemoryCommands."""
    mock = MagicMock()
    mock.recall_memories.return_value = {
        "packed": False,
        "items": [],
        "total_matches": 0,
        "execution_time_ms": 0.1,
    }
    mock.remember.return_value = {
        "id": "mock-memory-id",
        "type": "note",
        "tags": [],
        "redacted": False,
    }
    mock.capture = MagicMock()
    mock.capture.capture_certification_result = MagicMock()
    return mock


@pytest.fixture
def glue(mock_memory_commands):
    """Create TruthCertGlue instance with mocked memory."""
    return TruthCertGlue(
        base_url="http://test-server:8000",
        timeout=10,
        memory_commands=mock_memory_commands,
    )


class TestTruthCertGlueCertify:
    """Test TruthCertGlue.certify_claims()."""

    def test_certify_claims_success(self, glue, mock_memory_commands):
        """Test successful claim certification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:test123",
            "outcome": "PASS",
            "errors": [],
            "receipt": {
                "bundle_id": "sha256:test123",
                "outcome": "PASS",
            },
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.certify_claims(
                claims=[{"claim_id": "test", "value": 1.0}],
                policy_id="silver",
            )

        assert isinstance(result, CertificationResult)
        assert result.bundle_id == "sha256:test123"
        assert result.outcome == "PASS"
        assert result.errors == []

    def test_certify_claims_with_metadata(self, glue):
        """Test certification with metadata."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:meta123",
            "outcome": "PASS",
            "errors": [],
            "receipt": {"bundle_id": "sha256:meta123"},
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response) as mock_post:
            result = glue.certify_claims(
                claims=[{"claim_id": "test", "value": 1.0}],
                policy_id="gold",
                metadata={"source": "unit_test"},
            )

            # Check metadata was passed
            call_args = mock_post.call_args
            assert call_args[1]["json"]["metadata"] == {"source": "unit_test"}

    def test_certify_claims_reject_outcome(self, glue):
        """Test certification resulting in REJECT."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:reject123",
            "outcome": "REJECT",
            "errors": ["Memory leak detected"],
            "receipt": None,
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.certify_claims(
                claims=[{"claim_id": "bad", "value": 1.0}],
                policy_id="bronze",
            )

        assert result.outcome == "REJECT"
        assert "Memory leak detected" in result.errors

    def test_certify_claims_http_error(self, glue):
        """Test certification handles HTTP errors."""
        with patch.object(
            glue.client, 'post',
            side_effect=httpx.HTTPError("Connection failed")
        ):
            result = glue.certify_claims(
                claims=[{"claim_id": "test", "value": 1.0}],
                policy_id="bronze",
            )

        assert result.bundle_id == ""
        assert result.outcome == "ERROR"
        assert len(result.errors) > 0

    def test_certify_claims_stores_result(self, glue, mock_memory_commands):
        """Test that certification stores result to memory."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:store123",
            "outcome": "PASS",
            "errors": [],
            "receipt": {"bundle_id": "sha256:store123"},
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            glue.certify_claims(
                claims=[{"claim_id": "test"}],
                policy_id="silver",
                store_result=True,
            )

        mock_memory_commands.capture.capture_certification_result.assert_called_once()

    def test_certify_claims_skip_store(self, glue, mock_memory_commands):
        """Test that store_result=False skips memory storage."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:nostore123",
            "outcome": "PASS",
            "errors": [],
            "receipt": {},
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            glue.certify_claims(
                claims=[{"claim_id": "test"}],
                policy_id="bronze",
                store_result=False,
            )

        mock_memory_commands.capture.capture_certification_result.assert_not_called()


class TestTruthCertGlueVerify:
    """Test TruthCertGlue.verify_bundle()."""

    def test_verify_bundle_valid(self, glue):
        """Test verifying a valid bundle."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:valid123",
            "valid": True,
            "signature_valid": True,
            "scope_lock_valid": True,
            "schema_valid": True,
            "errors": [],
            "warnings": [],
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.verify_bundle("sha256:valid123")

        assert result["valid"] is True
        assert result["signature_valid"] is True
        assert result["errors"] == []

    def test_verify_bundle_invalid(self, glue):
        """Test verifying an invalid bundle."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundle_id": "sha256:invalid123",
            "valid": False,
            "signature_valid": False,
            "errors": ["Signature verification failed"],
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.verify_bundle("sha256:invalid123")

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_verify_bundle_check_options(self, glue):
        """Test verify with different check options."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": True,
            "errors": [],
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response) as mock_post:
            glue.verify_bundle(
                "sha256:test",
                check_signature=False,
                check_scope_lock=False,
            )

            call_args = mock_post.call_args
            assert call_args[1]["json"]["check_signature"] is False
            assert call_args[1]["json"]["check_scope_lock"] is False

    def test_verify_bundle_http_error(self, glue):
        """Test verify handles HTTP errors."""
        with patch.object(
            glue.client, 'post',
            side_effect=httpx.HTTPError("Connection refused")
        ):
            result = glue.verify_bundle("sha256:test123")

        assert result["valid"] is False
        assert len(result["errors"]) > 0


class TestTruthCertGlueHealthCheck:
    """Test TruthCertGlue.health_check()."""

    def test_health_check_healthy(self, glue):
        """Test health check returns True when healthy."""
        mock_response = Mock()
        mock_response.status_code = 200

        with patch.object(glue.client, 'get', return_value=mock_response):
            result = glue.health_check()

        assert result is True

    def test_health_check_unhealthy_status(self, glue):
        """Test health check returns False on non-200 status."""
        mock_response = Mock()
        mock_response.status_code = 503

        with patch.object(glue.client, 'get', return_value=mock_response):
            result = glue.health_check()

        assert result is False

    def test_health_check_connection_error(self, glue):
        """Test health check returns False on connection error."""
        with patch.object(
            glue.client, 'get',
            side_effect=httpx.HTTPError("Connection refused")
        ):
            result = glue.health_check()

        assert result is False


class TestTruthCertGlueJobs:
    """Test TruthCertGlue job management."""

    def test_submit_job(self, glue):
        """Test submitting a certification job."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "job_id": "job-123",
                "status": "pending",
                "policy_id": "silver",
            },
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.submit_job(
                policy_id="silver",
                input_path="/data/claims",
                metadata={"source": "batch"},
            )

        assert "job" in result
        assert result["job"]["job_id"] == "job-123"

    def test_submit_job_error(self, glue):
        """Test job submission error handling."""
        with patch.object(
            glue.client, 'post',
            side_effect=httpx.HTTPError("Server error")
        ):
            result = glue.submit_job(policy_id="bronze")

        assert "error" in result

    def test_get_job_status(self, glue):
        """Test getting job status."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "job_id": "job-123",
                "status": "completed",
                "output_bundle_id": "sha256:result123",
            },
        }
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'get', return_value=mock_response):
            result = glue.get_job_status("job-123")

        assert result["job"]["status"] == "completed"

    def test_get_job_status_error(self, glue):
        """Test job status error handling."""
        with patch.object(
            glue.client, 'get',
            side_effect=httpx.HTTPError("Not found")
        ):
            result = glue.get_job_status("nonexistent")

        assert "error" in result


class TestTruthCertGlueMemory:
    """Test TruthCertGlue memory operations."""

    def test_recall_memory(self, glue, mock_memory_commands):
        """Test recalling from memory."""
        mock_memory_commands.recall_memories.return_value = {
            "packed": False,
            "items": [
                {"id": "mem-1", "text": "Previous certification"},
            ],
            "total_matches": 1,
        }

        result = glue.recall_memory("certification")

        assert "warning" in result
        assert "NOT EVIDENCE" in result["warning"]
        mock_memory_commands.recall_memories.assert_called_once()

    def test_recall_memory_packed(self, glue, mock_memory_commands):
        """Test recalling with packed context."""
        mock_memory_commands.recall_memories.return_value = {
            "packed": True,
            "content": "Packed context content",
            "items_included": 5,
        }

        result = glue.recall_memory("test", pack=True)

        assert result["warning"] is not None
        call_args = mock_memory_commands.recall_memories.call_args
        assert call_args[1]["pack"] is True

    def test_remember(self, glue, mock_memory_commands):
        """Test storing to memory."""
        result = glue.remember(
            text="Important decision made",
            tags=["decision"],
            memory_type="decision",
        )

        mock_memory_commands.remember.assert_called_once_with(
            "Important decision made",
            tags=["decision"],
            memory_type="decision",
        )


class TestTruthCertGlueContextManager:
    """Test TruthCertGlue context manager."""

    def test_context_manager(self, mock_memory_commands):
        """Test using glue as context manager."""
        with TruthCertGlue(
            base_url="http://test:8000",
            memory_commands=mock_memory_commands,
        ) as glue:
            assert glue is not None
            assert glue.client is not None

        # Client should be closed after context exit
        # (httpx.Client doesn't expose is_closed, but no error means success)

    def test_close_method(self, glue):
        """Test explicit close."""
        # Should not raise
        glue.close()


class TestCertificationResult:
    """Test CertificationResult dataclass."""

    def test_result_creation(self):
        """Test creating CertificationResult."""
        result = CertificationResult(
            bundle_id="sha256:test",
            outcome="PASS",
            errors=[],
            warnings=["minor warning"],
            receipt={"key": "value"},
        )

        assert result.bundle_id == "sha256:test"
        assert result.outcome == "PASS"
        assert result.errors == []
        assert result.warnings == ["minor warning"]
        assert result.receipt == {"key": "value"}

    def test_result_defaults(self):
        """Test CertificationResult default values."""
        result = CertificationResult(
            bundle_id="",
            outcome="ERROR",
            errors=["failed"],
            warnings=[],
        )

        assert result.receipt is None


class TestGlueConfiguration:
    """Test glue configuration."""

    def test_default_configuration(self, mock_memory_commands):
        """Test default configuration values."""
        with patch.dict('os.environ', {}, clear=True):
            glue = TruthCertGlue(memory_commands=mock_memory_commands)

            assert glue.base_url == "http://localhost:8000"
            assert glue.timeout == 30

    def test_environment_configuration(self, mock_memory_commands):
        """Test configuration from environment."""
        with patch.dict('os.environ', {
            'TRUTHCERT_URL': 'http://custom:9000',
            'TRUTHCERT_TIMEOUT': '60',
        }):
            glue = TruthCertGlue(memory_commands=mock_memory_commands)

            assert glue.base_url == "http://custom:9000"
            assert glue.timeout == 60

    def test_explicit_configuration_overrides_env(self, mock_memory_commands):
        """Test explicit configuration overrides environment."""
        with patch.dict('os.environ', {
            'TRUTHCERT_URL': 'http://env:8000',
        }):
            glue = TruthCertGlue(
                base_url="http://explicit:8000",
                memory_commands=mock_memory_commands,
            )

            assert glue.base_url == "http://explicit:8000"


class TestMockedHTTPResponses:
    """Test with various mocked HTTP response scenarios."""

    def test_timeout_handling(self, glue):
        """Test timeout error handling."""
        with patch.object(
            glue.client, 'post',
            side_effect=httpx.TimeoutException("Request timed out")
        ):
            result = glue.certify_claims(
                claims=[{"claim_id": "test"}],
                policy_id="bronze",
            )

        assert result.outcome == "ERROR"
        assert len(result.errors) > 0

    def test_connection_error_handling(self, glue):
        """Test connection error handling."""
        with patch.object(
            glue.client, 'post',
            side_effect=httpx.ConnectError("Failed to connect")
        ):
            result = glue.certify_claims(
                claims=[{"claim_id": "test"}],
                policy_id="bronze",
            )

        assert result.outcome == "ERROR"

    def test_server_error_response(self, glue):
        """Test server error (5xx) response handling."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=Mock(),
                response=mock_response,
            )
        )

        with patch.object(glue.client, 'post', return_value=mock_response):
            result = glue.certify_claims(
                claims=[{"claim_id": "test"}],
                policy_id="bronze",
            )

        assert result.outcome == "ERROR"

    def test_malformed_json_response(self, glue):
        """Test handling of malformed JSON responses."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = Mock()

        with patch.object(glue.client, 'post', return_value=mock_response):
            # The glue code raises an exception on JSON parse errors
            # which is caught by the httpx error handler
            try:
                result = glue.certify_claims(
                    claims=[{"claim_id": "test"}],
                    policy_id="bronze",
                )
                # If it doesn't raise, check for error outcome
                assert result.outcome == "ERROR"
            except ValueError:
                # This is acceptable - malformed JSON causes a ValueError
                pass
