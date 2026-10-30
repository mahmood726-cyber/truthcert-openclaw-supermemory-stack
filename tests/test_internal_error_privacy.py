"""Negative controls for internal API error privacy and explicit error handling."""

from fastapi import HTTPException

from certifier.errors import ErrorCode, ValidationError, handle_exception


def test_unexpected_exception_does_not_disclose_sensitive_details():
    secret = "SYNTHETIC_PATIENT_REFERENCE_12345"
    raised = RuntimeError(f"SQLite failed while reading {secret} at /private/path")
    response = handle_exception(raised)

    assert response.status_code == 500
    assert response.detail == {
        "error": ErrorCode.INTERNAL_ERROR.value,
        "message": "Internal server error",
    }
    assert secret not in str(response.detail)
    assert "/private/path" not in str(response.detail)


def test_explicit_validation_error_preserves_structured_refusal():
    response = handle_exception(
        ValidationError(
            "Source scope mismatch",
            code=ErrorCode.SCOPE_LOCK_MISMATCH,
            details={"rule": "source_scope"},
        )
    )

    assert response.status_code == 400
    assert response.detail["error"] == ErrorCode.SCOPE_LOCK_MISMATCH.value
    assert response.detail["details"] == {"rule": "source_scope"}


def test_existing_http_exception_preserves_intended_status():
    original = HTTPException(status_code=404, detail={"error": "MISSING"})
    assert handle_exception(original) is original
