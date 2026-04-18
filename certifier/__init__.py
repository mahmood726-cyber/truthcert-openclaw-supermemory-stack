"""
TruthCert Certifier - Fail-closed certification for numeric claims.

Core principle: ONLY TruthCert can publish numbers. Memory is never evidence.
"""

__version__ = "1.0.0"

from .constants import (
    CertificationProfile,
    Severity,
    BundleOutcome,
)
from .models import (
    NumericClaim,
    ClaimType,
    EvidenceLocator,
    EvidenceType,
    ValidatorResult,
    ValidationSummary,
    ScopeLock,
    Policy,
    Job,
    JobStatus,
)
from .signing import sign_manifest, verify_signature
from .bundle import create_bundle, load_bundle, list_bundles
from .job_store import JobStore, get_job_store, init_job_store

__all__ = [
    # Version
    "__version__",
    # Constants
    "CertificationProfile",
    "Severity",
    "BundleOutcome",
    # Models
    "NumericClaim",
    "ClaimType",
    "EvidenceLocator",
    "EvidenceType",
    "ValidatorResult",
    "ValidationSummary",
    "ScopeLock",
    "Policy",
    "Job",
    "JobStatus",
    # Operations
    "sign_manifest",
    "verify_signature",
    "create_bundle",
    "load_bundle",
    "list_bundles",
    # Job store
    "JobStore",
    "get_job_store",
    "init_job_store",
]
