"""
TruthCert FastAPI application - fail-closed certification service.
"""

import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, APIRouter
from fastapi.responses import JSONResponse, FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RATE_LIMIT_CERTIFY,
    DEFAULT_RATE_LIMIT_VERIFY,
    DEFAULT_RATE_LIMIT_DEFAULT,
    DEFAULT_MAX_CLAIMS,
    DEFAULT_MAX_REQUEST_MB,
    DEFAULT_POLICY_CACHE_TTL,
    ENV_HOST,
    ENV_PORT,
    ENV_RATE_LIMIT_CERTIFY,
    ENV_RATE_LIMIT_VERIFY,
    ENV_RATE_LIMIT_DEFAULT,
    ENV_MAX_CLAIMS,
    ENV_MAX_REQUEST_MB,
    API_PATH_HEALTH,
    API_PATH_JOBS,
    API_PATH_CERTIFY,
    API_PATH_VERIFY,
    API_PATH_BUNDLES,
    API_PATH_AUDIT,
    BundleOutcome,
    Severity,
)
from .models import (
    CertifyRequest,
    CertifyResponse,
    VerifyRequest,
    VerifyResponse,
    JobSubmitRequest,
    JobResponse,
    Job,
    JobStatus,
    Policy,
    ScopeLock,
    ValidationSummary,
    ValidatorResult,
    CertificationProfile,
)
from .bundle import (
    create_bundle,
    load_bundle,
    list_bundles,
    get_bundle_dir,
)
from .signing import verify_signature
from .errors import (
    TruthCertError,
    ValidationError,
    NotFoundError,
    RateLimitError,
    create_not_found_error,
    handle_exception,
)
from .validators import ValidatorRegistry
from .job_store import get_job_store, init_job_store

# =============================================================================
# Rate Limiting Setup
# =============================================================================

limiter = Limiter(key_func=get_remote_address)

# =============================================================================
# Policy Cache
# =============================================================================

_policy_cache: dict[str, tuple[Policy, float]] = {}


def load_policy(policy_id: str) -> Policy:
    """Load a policy with caching."""
    now = datetime.now(timezone.utc).timestamp()

    # Check cache
    if policy_id in _policy_cache:
        policy, cached_at = _policy_cache[policy_id]
        if now - cached_at < DEFAULT_POLICY_CACHE_TTL:
            return policy

    # Load from file
    policy_dir = Path("policies")
    policy_file = policy_dir / f"{policy_id}.json"

    if not policy_file.exists():
        raise create_not_found_error("policy", policy_id)

    with open(policy_file) as f:
        policy_data = json.load(f)

    policy = Policy(**policy_data)
    _policy_cache[policy_id] = (policy, now)
    return policy


# =============================================================================
# Request Validation
# =============================================================================


def validate_bundle_id(bundle_id: str) -> str:
    """Validate and sanitize bundle ID to prevent path traversal."""
    # Only allow alphanumeric, hyphens, underscores, colons
    if not re.match(r'^[a-zA-Z0-9_:\-]+$', bundle_id):
        raise ValidationError(
            message="Invalid bundle ID format",
            details={"bundle_id": bundle_id[:50]},
        )
    # Prevent path traversal
    if ".." in bundle_id or "/" in bundle_id or "\\" in bundle_id:
        raise ValidationError(
            message="Invalid characters in bundle ID",
            details={"bundle_id": bundle_id[:50]},
        )
    return bundle_id


async def validate_request_size(request: Request) -> None:
    """Validate request body size."""
    max_size = int(os.environ.get(ENV_MAX_REQUEST_MB, DEFAULT_MAX_REQUEST_MB)) * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_size:
        raise ValidationError(
            message=f"Request too large. Maximum size: {DEFAULT_MAX_REQUEST_MB}MB",
            details={"content_length": content_length, "max_size": max_size},
        )


# =============================================================================
# Application Lifecycle
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    # Startup
    get_bundle_dir()  # Ensure bundle directory exists
    init_job_store()  # Initialize SQLite job store
    yield
    # Shutdown
    pass


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="TruthCert Certifier",
    description="Fail-closed certification service for numeric claims",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

# =============================================================================
# API Versioning - v1 Router
# =============================================================================

api_v1_router = APIRouter(prefix="/api/v1")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded."""
    return JSONResponse(
        status_code=429,
        content=RateLimitError().to_dict(),
    )


@app.exception_handler(TruthCertError)
async def truthcert_error_handler(request: Request, exc: TruthCertError):
    """Handle TruthCert errors."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


# =============================================================================
# Health Endpoint
# =============================================================================


@app.get(API_PATH_HEALTH)
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "truthcert",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Jobs Endpoints
# =============================================================================


@api_v1_router.post("/jobs", response_model=JobResponse)
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def submit_job(request: Request, body: JobSubmitRequest):
    """Submit a new certification job."""
    await validate_request_size(request)

    job_id = str(uuid.uuid4())

    # Load policy to get profile
    policy = load_policy(body.policy_id)

    job = Job(
        job_id=job_id,
        status=JobStatus.PENDING,
        policy_id=body.policy_id,
        profile=policy.profile,
        input_path=body.input_path,
        metadata=body.metadata,
    )

    # Persist job to SQLite
    job_store = get_job_store()
    job_store.create(job)

    return JobResponse(job=job)


@api_v1_router.get("/jobs/{job_id}", response_model=JobResponse)
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def get_job(request: Request, job_id: str):
    """Get job status."""
    job_store = get_job_store()
    job = job_store.get(job_id)

    if job is None:
        raise create_not_found_error("job", job_id)

    return JobResponse(job=job, bundle_id=job.output_bundle_id)


# =============================================================================
# Certification Endpoint
# =============================================================================


@api_v1_router.post("/certify", response_model=CertifyResponse)
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_CERTIFY, DEFAULT_RATE_LIMIT_CERTIFY))
async def certify_claims(request: Request, body: CertifyRequest):
    """
    Certify a set of claims.

    This is a fail-closed operation:
    - If any blocking validator fails, outcome is REJECT
    - Memory references in evidence result in BLOCK
    """
    await validate_request_size(request)

    # Validate claim count
    max_claims = int(os.environ.get(ENV_MAX_CLAIMS, DEFAULT_MAX_CLAIMS))
    if len(body.claims) > max_claims:
        raise ValidationError(
            message=f"Too many claims. Maximum: {max_claims}",
            details={"claim_count": len(body.claims), "max_claims": max_claims},
        )

    # Load policy
    policy = load_policy(body.policy_id)

    # Scope lock is mandatory - no auto-generation
    # The model now requires scope_lock, but we add explicit validation for clarity
    scope_lock = body.scope_lock

    # Build validation context
    context = {
        "policy": policy,
        "require_determinism": policy.require_determinism,
        "require_multi_witness": policy.require_multi_witness,
        "witness_count": policy.witness_count,
    }

    # Create validation pipeline
    pipeline = ValidatorRegistry.create_pipeline(policy.validators)

    # Run validators
    results: list[ValidatorResult] = []
    for validator in pipeline:
        result = validator.run(body.claims, scope_lock, context)
        results.append(result)

    # Summarize results
    blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]
    warnings = [r for r in results if not r.passed and r.severity == Severity.WARN]

    validation_summary = ValidationSummary(
        results=results,
        all_passed=len(blocking) == 0,
        has_blocking=len(blocking) > 0,
        has_warnings=len(warnings) > 0,
        blocking_count=len(blocking),
        warning_count=len(warnings),
    )

    # Create bundle
    bundle_path, receipt = create_bundle(
        claims=body.claims,
        scope_lock=scope_lock,
        policy_id=body.policy_id,
        validation_summary=validation_summary,
        validators=[v.name for v in pipeline],
        model_metadata=body.metadata.get("model", {}),
        tool_metadata=body.metadata.get("tool", {}),
        sign=True,
    )

    outcome = BundleOutcome.PASS if validation_summary.all_passed else BundleOutcome.REJECT

    return CertifyResponse(
        bundle_id=receipt.get("bundle_id", ""),
        outcome=outcome,
        validation_summary=validation_summary,
        receipt=receipt if outcome == BundleOutcome.PASS else None,
        errors=[r.message for r in blocking],
    )


# =============================================================================
# Verification Endpoint
# =============================================================================


@api_v1_router.post("/verify", response_model=VerifyResponse)
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_VERIFY, DEFAULT_RATE_LIMIT_VERIFY))
async def verify_bundle(request: Request, body: VerifyRequest):
    """Verify a bundle's integrity and signature."""
    bundle_id = validate_bundle_id(body.bundle_id)

    # Find bundle
    bundle_dir = get_bundle_dir()
    short_id = bundle_id.replace("sha256:", "")[:16]
    bundle_path = bundle_dir / f"bundle_{short_id}"

    if not bundle_path.exists():
        raise create_not_found_error("bundle", bundle_id)

    # Load bundle
    bundle_data = load_bundle(bundle_path)
    manifest = bundle_data["manifest"]

    errors = []
    warnings = []

    # Schema validation
    schema_valid = True
    if not manifest.get("bundle_id"):
        schema_valid = False
        errors.append("Missing bundle_id in manifest")
    if not manifest.get("outcome"):
        schema_valid = False
        errors.append("Missing outcome in manifest")

    # Full claims payload integrity is necessary in addition to a manifest
    # signature: legacy bundle IDs omit clinical fields such as CI bounds.
    from .bundle import claims_payload_problems
    payload_errors = claims_payload_problems(bundle_path, manifest)
    if payload_errors:
        schema_valid = False
        errors.extend(payload_errors)

    # Signature validation
    signature_valid = None
    if body.check_signature:
        attest_path = bundle_path / "attest"
        sig_file = attest_path / "signature.ed25519"
        pubkey_file = attest_path / "public_key.txt"

        if sig_file.exists() and pubkey_file.exists():
            try:
                signature_b64 = sig_file.read_text().strip()
                public_key_b64 = pubkey_file.read_text().strip()
                verify_signature(manifest, signature_b64, public_key_b64)
                signature_valid = True
            except Exception as e:
                signature_valid = False
                errors.append(f"Signature verification failed: {str(e)}")
        else:
            signature_valid = False
            errors.append("Missing signature or public key files")

    # Scope lock validation
    scope_lock_valid = None
    if body.check_scope_lock:
        scope_lock_data = bundle_data.get("scope_lock")
        if scope_lock_data:
            scope_lock = ScopeLock(**scope_lock_data)
            computed_hash = scope_lock.compute_hash()
            expected_hash = manifest.get("scope_lock_hash")
            if computed_hash == expected_hash:
                scope_lock_valid = True
            else:
                scope_lock_valid = False
                errors.append("Scope lock hash mismatch")
        else:
            scope_lock_valid = False
            errors.append("Missing scope lock file")

    # Disabled checks permit diagnostic inspection only. In particular,
    # None means NOT_CHECKED, never an implicit True in a public valid flag.
    if not body.check_signature:
        warnings.append("NONCERTIFYING: signature verification skipped")
    if not body.check_scope_lock:
        warnings.append("NONCERTIFYING: scope lock verification skipped")
    valid = schema_valid and signature_valid is True and scope_lock_valid is True

    return VerifyResponse(
        bundle_id=bundle_id,
        valid=valid,
        signature_valid=signature_valid,
        scope_lock_valid=scope_lock_valid,
        schema_valid=schema_valid,
        errors=errors,
        warnings=warnings,
    )


# =============================================================================
# Bundles Endpoints
# =============================================================================


@api_v1_router.get("/bundles")
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def list_all_bundles(request: Request, limit: int = 100, offset: int = 0):
    """List all bundles with pagination."""
    bundles = list_bundles(limit=limit, offset=offset)
    return {
        "bundles": bundles,
        "count": len(bundles),
        "limit": limit,
        "offset": offset,
    }


@api_v1_router.get("/bundles/{bundle_id}")
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def get_bundle(request: Request, bundle_id: str):
    """Get bundle details."""
    bundle_id = validate_bundle_id(bundle_id)

    bundle_dir = get_bundle_dir()
    short_id = bundle_id.replace("sha256:", "")[:16]
    bundle_path = bundle_dir / f"bundle_{short_id}"

    if not bundle_path.exists():
        raise create_not_found_error("bundle", bundle_id)

    return load_bundle(bundle_path)


@api_v1_router.get("/bundles/{bundle_id}/receipt.json")
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def get_receipt(request: Request, bundle_id: str):
    """Get bundle receipt."""
    bundle_id = validate_bundle_id(bundle_id)

    bundle_dir = get_bundle_dir()
    short_id = bundle_id.replace("sha256:", "")[:16]
    receipt_path = bundle_dir / f"bundle_{short_id}" / "attest" / "receipt.json"

    if not receipt_path.exists():
        raise create_not_found_error("bundle", bundle_id)

    with open(receipt_path) as f:
        return json.load(f)


@api_v1_router.get("/bundles/{bundle_id}/bundle.tar.gz")
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def download_bundle(request: Request, bundle_id: str):
    """Download bundle as tarball."""
    bundle_id = validate_bundle_id(bundle_id)

    bundle_dir = get_bundle_dir()
    short_id = bundle_id.replace("sha256:", "")[:16]
    bundle_path = bundle_dir / f"bundle_{short_id}"

    if not bundle_path.exists():
        raise create_not_found_error("bundle", bundle_id)

    from .bundle import create_bundle_tarball
    tarball_path = create_bundle_tarball(bundle_path)

    return FileResponse(
        path=tarball_path,
        media_type="application/gzip",
        filename=f"bundle_{short_id}.tar.gz",
    )


# =============================================================================
# Audit Endpoint
# =============================================================================


@api_v1_router.get("/audit/{run_id}")
@limiter.limit(os.environ.get(ENV_RATE_LIMIT_DEFAULT, DEFAULT_RATE_LIMIT_DEFAULT))
async def get_audit_log(request: Request, run_id: str):
    """Get audit log for a run."""
    run_id = validate_bundle_id(run_id)

    bundle_dir = get_bundle_dir()
    short_id = run_id.replace("sha256:", "")[:16]
    audit_path = bundle_dir / f"bundle_{short_id}" / "audit.log.jsonl"

    if not audit_path.exists():
        raise create_not_found_error("bundle", run_id)

    logs = []
    with open(audit_path) as f:
        for line in f:
            if line.strip():
                logs.append(json.loads(line))

    return {"run_id": run_id, "logs": logs}


# =============================================================================
# Register API v1 Router
# =============================================================================

app.include_router(api_v1_router)


# =============================================================================
# Server Runner
# =============================================================================


def run_server():
    """Run the server."""
    import uvicorn

    host = os.environ.get(ENV_HOST, DEFAULT_HOST)
    port = int(os.environ.get(ENV_PORT, DEFAULT_PORT))

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
