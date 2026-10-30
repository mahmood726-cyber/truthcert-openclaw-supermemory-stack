"""
TruthCert Certifier - Fail-closed certification for numeric claims.

Core principle: ONLY TruthCert can publish numbers. Memory is never evidence.
"""

__version__ = "1.0.0"

from .bundle import create_bundle, list_bundles, load_bundle
from .constants import (
    BundleOutcome,
    CertificationProfile,
    Severity,
)
from .job_store import JobStore, get_job_store, init_job_store
from .models import (
    ClaimType,
    EvidenceLocator,
    EvidenceType,
    Job,
    JobStatus,
    NumericClaim,
    Policy,
    ScopeLock,
    ValidationSummary,
    ValidatorResult,
)
from .signing import sign_manifest, verify_signature

__all__ = [
    "BundleOutcome",
    # Constants
    "CertificationProfile",
    "ClaimType",
    "EvidenceLocator",
    "EvidenceType",
    "Job",
    "JobStatus",
    # Job store
    "JobStore",
    # Models
    "NumericClaim",
    "Policy",
    "ScopeLock",
    "Severity",
    "ValidationSummary",
    "ValidatorResult",
    # Version
    "__version__",
    "create_bundle",
    "get_job_store",
    "init_job_store",
    "list_bundles",
    "load_bundle",
    # Operations
    "sign_manifest",
    "verify_signature",
]
