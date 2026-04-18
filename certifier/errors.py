"""
Standardized error handling for TruthCert certifier.
"""

from enum import Enum
from typing import Any, Optional
from fastapi import HTTPException


class ErrorCode(str, Enum):
    """Standardized error codes."""
    # Validation errors (400)
    INVALID_REQUEST = "INVALID_REQUEST"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_CLAIM = "INVALID_CLAIM"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    SCOPE_LOCK_MISMATCH = "SCOPE_LOCK_MISMATCH"
    MEMORY_LEAK_DETECTED = "MEMORY_LEAK_DETECTED"

    # Not found errors (404)
    BUNDLE_NOT_FOUND = "BUNDLE_NOT_FOUND"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"

    # Configuration errors (500)
    SIGNING_KEY_NOT_CONFIGURED = "SIGNING_KEY_NOT_CONFIGURED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"

    # Rate limiting (429)
    RATE_LIMITED = "RATE_LIMITED"

    # Internal errors (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SIGNING_ERROR = "SIGNING_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


class TruthCertError(Exception):
    """Base exception for TruthCert errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
        hint: Optional[str] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "error": self.code.value,
            "message": self.message,
            "details": self.details,
        }
        if self.hint:
            result["hint"] = self.hint
        return result

    def to_http_exception(self) -> HTTPException:
        """Convert to FastAPI HTTPException."""
        return HTTPException(
            status_code=self.status_code,
            detail=self.to_dict(),
        )


class ValidationError(TruthCertError):
    """Validation-related errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.VALIDATION_FAILED,
        details: Optional[dict[str, Any]] = None,
        hint: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=400,
            details=details,
            hint=hint,
        )


class NotFoundError(TruthCertError):
    """Resource not found errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.BUNDLE_NOT_FOUND,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=404,
            details=details,
        )


class ConfigurationError(TruthCertError):
    """Configuration-related errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.SIGNING_KEY_NOT_CONFIGURED,
        details: Optional[dict[str, Any]] = None,
        hint: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=500,
            details=details,
            hint=hint,
        )


class RateLimitError(TruthCertError):
    """Rate limiting errors."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            details=details,
        )


class MemoryLeakError(ValidationError):
    """Error when memory is cited as evidence."""

    def __init__(
        self,
        claim_id: str,
        evidence_uri: str,
    ):
        super().__init__(
            message=f"Memory cited as evidence in claim {claim_id}: {evidence_uri}",
            code=ErrorCode.MEMORY_LEAK_DETECTED,
            details={
                "claim_id": claim_id,
                "evidence_uri": evidence_uri,
                "rule": "Memory is never evidence",
            },
            hint="Remove memory references from evidence. Use only OA sources or fixtures.",
        )


# =============================================================================
# Helper Functions
# =============================================================================


def create_validation_error(
    field: str,
    message: str,
    value: Any = None,
) -> ValidationError:
    """Create a validation error with field details."""
    details = {"field": field}
    if value is not None:
        details["value"] = str(value)[:100]  # Truncate long values
    return ValidationError(
        message=f"Validation failed for {field}: {message}",
        details=details,
    )


def create_not_found_error(
    resource_type: str,
    resource_id: str,
) -> NotFoundError:
    """Create a not found error for a resource."""
    code_map = {
        "bundle": ErrorCode.BUNDLE_NOT_FOUND,
        "policy": ErrorCode.POLICY_NOT_FOUND,
        "job": ErrorCode.JOB_NOT_FOUND,
    }
    return NotFoundError(
        message=f"{resource_type.title()} not found: {resource_id}",
        code=code_map.get(resource_type, ErrorCode.BUNDLE_NOT_FOUND),
        details={"resource_type": resource_type, "resource_id": resource_id},
    )


def handle_exception(exc: Exception) -> HTTPException:
    """Convert any exception to HTTPException."""
    if isinstance(exc, TruthCertError):
        return exc.to_http_exception()
    if isinstance(exc, HTTPException):
        return exc
    # Generic exception
    return HTTPException(
        status_code=500,
        detail={
            "error": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
        },
    )
