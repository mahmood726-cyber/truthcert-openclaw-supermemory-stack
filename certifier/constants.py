"""
Centralized constants for TruthCert certifier.
Eliminates magic strings and provides single source of truth.
"""

from enum import Enum
from typing import Final

# =============================================================================
# Environment Variable Names
# =============================================================================

ENV_SIGNING_KEY: Final[str] = "TRUTHCERT_SIGNING_KEY"
ENV_PUBLIC_KEY: Final[str] = "TRUTHCERT_PUBLIC_KEY"
ENV_LOG_LEVEL: Final[str] = "TRUTHCERT_LOG_LEVEL"
ENV_LOG_DIR: Final[str] = "TRUTHCERT_LOG_DIR"
ENV_BUNDLE_DIR: Final[str] = "TRUTHCERT_BUNDLE_DIR"
ENV_EVIDENCE_CACHE: Final[str] = "TRUTHCERT_EVIDENCE_CACHE"
ENV_MAX_CLAIMS: Final[str] = "TRUTHCERT_MAX_CLAIMS"
ENV_MAX_REQUEST_MB: Final[str] = "TRUTHCERT_MAX_REQUEST_MB"
ENV_RATE_LIMIT_CERTIFY: Final[str] = "TRUTHCERT_RATE_LIMIT_CERTIFY"
ENV_RATE_LIMIT_VERIFY: Final[str] = "TRUTHCERT_RATE_LIMIT_VERIFY"
ENV_RATE_LIMIT_DEFAULT: Final[str] = "TRUTHCERT_RATE_LIMIT_DEFAULT"
ENV_HOST: Final[str] = "TRUTHCERT_HOST"
ENV_PORT: Final[str] = "TRUTHCERT_PORT"
ENV_DB_PATH: Final[str] = "TRUTHCERT_DB_PATH"

# =============================================================================
# Default Values
# =============================================================================

DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOG_DIR: Final[str] = "./logs/spans"
DEFAULT_BUNDLE_DIR: Final[str] = "./bundles"
DEFAULT_EVIDENCE_CACHE: Final[str] = "./evidence_cache"
DEFAULT_MAX_CLAIMS: Final[int] = 10000
DEFAULT_MAX_REQUEST_MB: Final[int] = 50
DEFAULT_RATE_LIMIT_CERTIFY: Final[str] = "10/minute"
DEFAULT_RATE_LIMIT_VERIFY: Final[str] = "60/minute"
DEFAULT_RATE_LIMIT_DEFAULT: Final[str] = "100/minute"
DEFAULT_HOST: Final[str] = "127.0.0.1"  # Local-only unless TRUTHCERT_HOST is explicit
DEFAULT_PORT: Final[int] = 8000
DEFAULT_DB_PATH: Final[str] = "./truthcert.db"
DEFAULT_POLICY_CACHE_TTL: Final[int] = 300  # 5 minutes

# =============================================================================
# File Names
# =============================================================================

MANIFEST_FILE: Final[str] = "manifest.json"
SCOPE_LOCK_FILE: Final[str] = "scope_lock.json"
CLAIMS_FILE: Final[str] = "claims.jsonl"
PROVENANCE_FILE: Final[str] = "provenance.jsonl"
AUDIT_LOG_FILE: Final[str] = "audit.log.jsonl"
TELEMETRY_FILE: Final[str] = "telemetry.jsonl"
SIGNATURE_FILE: Final[str] = "signature.ed25519"
PUBLIC_KEY_FILE: Final[str] = "public_key.txt"
RECEIPT_FILE: Final[str] = "receipt.json"

# =============================================================================
# Directory Names
# =============================================================================

OUTPUTS_DIR: Final[str] = "outputs"
CAPSULE_DIR: Final[str] = "capsule"
ATTEST_DIR: Final[str] = "attest"

# =============================================================================
# Certification Profiles
# =============================================================================


class CertificationProfile(str, Enum):
    """Certification assurance levels."""

    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# =============================================================================
# Validation Severity Levels
# =============================================================================


class Severity(str, Enum):
    """Validator result severity levels."""

    INFO = "INFO"
    WARN = "WARN"
    BLOCK = "BLOCK"


# =============================================================================
# Bundle Outcomes
# =============================================================================


class BundleOutcome(str, Enum):
    """Certification outcomes."""

    PASS = "PASS"
    REJECT = "REJECT"


# =============================================================================
# Validator Names
# =============================================================================

VALIDATOR_SCHEMA: Final[str] = "schema"
VALIDATOR_SCOPE_LOCK: Final[str] = "scope_lock"
VALIDATOR_NO_NAKED_NUMBERS: Final[str] = "no_naked_numbers"
VALIDATOR_MEMORY_LEAK: Final[str] = "memory_leak"
VALIDATOR_MEMORY_DRIFT: Final[str] = "memory_drift"
VALIDATOR_DETERMINISM: Final[str] = "determinism"
VALIDATOR_MULTI_WITNESS: Final[str] = "multi_witness"
VALIDATOR_UNIT_DRIFT: Final[str] = "unit_drift"
VALIDATOR_DOMAIN_PACK: Final[str] = "domain_pack"

# =============================================================================
# Memory Source Markers
# =============================================================================

MEMORY_SOURCE_PREFIX: Final[str] = "memory:"
MEMORY_SOURCE_LITERAL: Final[str] = "memory"

# =============================================================================
# Content Hashing
# =============================================================================

HASH_ALGORITHM: Final[str] = "sha256"
HASH_PREFIX: Final[str] = "sha256:"

# =============================================================================
# API Paths
# =============================================================================

API_PATH_HEALTH: Final[str] = "/health"
API_PATH_JOBS: Final[str] = "/jobs"
API_PATH_CERTIFY: Final[str] = "/certify"
API_PATH_VERIFY: Final[str] = "/verify"
API_PATH_BUNDLES: Final[str] = "/bundles"
API_PATH_AUDIT: Final[str] = "/audit"
