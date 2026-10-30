"""
Pydantic models for TruthCert certifier.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import hashlib
import json

from .constants import (
    CertificationProfile,
    Severity,
    BundleOutcome,
    HASH_PREFIX,
)


# =============================================================================
# Enums
# =============================================================================


class ClaimType(str, Enum):
    """Types of numeric claims."""
    # General types
    EFFECT_SIZE = "effect_size"
    HETEROGENEITY = "heterogeneity"
    SAMPLE_SIZE = "sample_size"
    P_VALUE = "p_value"
    CONFIDENCE_INTERVAL = "confidence_interval"
    COUNT = "count"
    PROPORTION = "proportion"
    CUSTOM = "custom"

    # Specific effect size measures
    RISK_RATIO = "risk_ratio"              # RR
    ODDS_RATIO = "odds_ratio"              # OR
    HAZARD_RATIO = "hazard_ratio"          # HR
    MEAN_DIFFERENCE = "mean_difference"     # MD
    STANDARDIZED_MEAN_DIFFERENCE = "standardized_mean_difference"  # SMD/Cohen's d
    NUMBER_NEEDED_TO_TREAT = "number_needed_to_treat"  # NNT
    NUMBER_NEEDED_TO_HARM = "number_needed_to_harm"    # NNH

    # Risk/rate measures
    ABSOLUTE_RISK = "absolute_risk"
    RELATIVE_RISK_REDUCTION = "relative_risk_reduction"  # RRR
    ABSOLUTE_RISK_REDUCTION = "absolute_risk_reduction"  # ARR
    INCIDENCE_RATE = "incidence_rate"
    PREVALENCE = "prevalence"

    # Correlation and agreement
    CORRELATION = "correlation"
    KAPPA = "kappa"
    ICC = "icc"  # Intraclass correlation

    # Diagnostic accuracy
    SENSITIVITY = "sensitivity"
    SPECIFICITY = "specificity"
    POSITIVE_PREDICTIVE_VALUE = "ppv"
    NEGATIVE_PREDICTIVE_VALUE = "npv"
    LIKELIHOOD_RATIO_POSITIVE = "lr_positive"
    LIKELIHOOD_RATIO_NEGATIVE = "lr_negative"
    AUC_ROC = "auc_roc"

    # Meta-analysis specific
    POOLED_EFFECT = "pooled_effect"
    PREDICTION_INTERVAL = "prediction_interval"
    I_SQUARED = "i_squared"
    TAU_SQUARED = "tau_squared"
    COCHRAN_Q = "cochran_q"

    # Publication bias
    EGGER_INTERCEPT = "egger_intercept"
    FAIL_SAFE_N = "fail_safe_n"

    # Quality/certainty
    GRADE_CERTAINTY = "grade_certainty"
    QUALITY_SCORE = "quality_score"
    RISK_OF_BIAS = "risk_of_bias"

    # Network Meta-Analysis (NMA) specific
    NMA_SUCRA = "nma_sucra"                    # Surface Under Cumulative Ranking
    NMA_P_SCORE = "nma_p_score"                # P-score (frequentist SUCRA)
    NMA_MEAN_RANK = "nma_mean_rank"            # Mean treatment rank
    NMA_BEST_PROBABILITY = "nma_best_prob"     # Probability of being best
    NMA_RELATIVE_EFFECT = "nma_relative_effect"  # Pairwise comparison from NMA
    NMA_LEAGUE_TABLE = "nma_league_table"      # League table cell
    NMA_INCONSISTENCY = "nma_inconsistency"    # Local inconsistency (node-splitting)
    NMA_GLOBAL_INCONSISTENCY = "nma_global_inconsistency"  # Global inconsistency (design-by-treatment)
    NMA_PSRF = "nma_psrf"                      # PSRF for Bayesian NMA convergence
    NMA_EFFECTIVE_SAMPLE_SIZE = "nma_ess"     # Effective sample size (Bayesian)

    # Prediction model metrics
    CALIBRATION = "calibration"               # Calibration slope or intercept
    BRIER_SCORE = "brier_score"               # Brier score for predictions
    NET_BENEFIT = "net_benefit"               # Decision curve analysis


class EvidenceType(str, Enum):
    """Types of evidence sources."""
    OA_DOCUMENT = "oa_document"
    FIXTURE = "fixture"
    COMPUTED = "computed"
    EXTERNAL_API = "external_api"


# =============================================================================
# Evidence Models
# =============================================================================


def is_canonical_sha256_content_hash(value: str) -> bool:
    """Validate SHA-256 digest syntax; this does not authenticate the source."""
    if not isinstance(value, str) or not value.startswith(HASH_PREFIX):
        return False
    digest = value[len(HASH_PREFIX):]
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


class EvidenceLocator(BaseModel):
    """Reference to evidence supporting a claim."""
    source_type: EvidenceType
    uri: str = Field(..., description="URI or path to evidence")
    content_hash: str = Field(..., description="SHA-256 hash of content")
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    page: Optional[int] = None
    section: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        """Reject noncanonical digests before they become evidence identifiers."""
        if not is_canonical_sha256_content_hash(v):
            raise ValueError("Content hash must be sha256: followed by 64 lowercase hexadecimal characters")
        return v


# =============================================================================
# Claim Models
# =============================================================================


class NumericClaim(BaseModel):
    """A numeric claim requiring certification."""
    claim_id: str = Field(..., description="Unique identifier for this claim")
    claim_type: ClaimType
    value: float
    unit: Optional[str] = None
    precision: Optional[int] = None
    confidence_level: Optional[float] = Field(default=0.95, description="CI level, typically 0.95")
    lower_bound: Optional[float] = Field(None, description="Lower CI bound")
    upper_bound: Optional[float] = Field(None, description="Upper CI bound")

    # Statistical metadata
    standard_error: Optional[float] = Field(None, description="Standard error of the estimate")
    variance: Optional[float] = Field(None, description="Variance of the estimate")
    weight: Optional[float] = Field(None, description="Study weight in meta-analysis")
    sample_size: Optional[int] = Field(None, description="Total sample size")
    n_events: Optional[int] = Field(None, description="Number of events (for binary outcomes)")

    # For meta-analysis pooled estimates
    n_studies: Optional[int] = Field(None, description="Number of studies in meta-analysis")
    i_squared: Optional[float] = Field(None, description="I² heterogeneity statistic (0-100)")
    tau_squared: Optional[float] = Field(None, description="τ² between-study variance")

    # Quality indicators
    quality_score: Optional[float] = Field(None, description="Study quality score")
    risk_of_bias: Optional[str] = Field(None, description="Risk of bias assessment (low/unclear/high)")
    grade_certainty: Optional[str] = Field(None, description="GRADE certainty (high/moderate/low/very low)")

    # Required evidence
    evidence: list[EvidenceLocator] = Field(
        ..., min_length=1, description="At least one evidence locator required"
    )
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_hash(self) -> str:
        """Compute content hash for this claim."""
        canonical = json.dumps(
            {
                "claim_id": self.claim_id,
                "claim_type": self.claim_type.value,
                "value": self.value,
                "unit": self.unit,
                "evidence_hashes": sorted([e.content_hash for e in self.evidence]),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return f"{HASH_PREFIX}{digest}"


# =============================================================================
# Validation Models
# =============================================================================


class ValidatorResult(BaseModel):
    """Result from a single validator."""
    validator_name: str
    passed: bool
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: float = 0.0


class ValidationSummary(BaseModel):
    """Summary of all validation results."""
    results: list[ValidatorResult]
    all_passed: bool
    has_blocking: bool
    has_warnings: bool
    blocking_count: int = 0
    warning_count: int = 0


# =============================================================================
# Scope Lock Models
# =============================================================================


class ScopeLock(BaseModel):
    """Defines the scope and constraints for certification."""
    scope_id: str
    policy_id: str
    profile: CertificationProfile
    allowed_sources: list[str] = Field(default_factory=list)
    required_validators: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_hash(self) -> str:
        """Compute hash of scope lock for integrity verification."""
        canonical = json.dumps(
            {
                "scope_id": self.scope_id,
                "policy_id": self.policy_id,
                "profile": self.profile.value,
                "allowed_sources": sorted(self.allowed_sources),
                "required_validators": sorted(self.required_validators),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return f"{HASH_PREFIX}{digest}"


# =============================================================================
# Bundle Models
# =============================================================================


class BundleManifest(BaseModel):
    """Manifest for a certification bundle."""
    bundle_id: str
    policy_id: str
    profile: CertificationProfile
    outcome: BundleOutcome
    scope_lock_hash: str
    claim_count: int
    claims_sha256: Optional[str] = None  # signed complete claims.jsonl payload for v2
    validators: list[str]
    validation_summary: ValidationSummary
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    tool_metadata: dict[str, Any] = Field(default_factory=dict)
    signature_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "tc-bundle-v2"


class BundleReceipt(BaseModel):
    """Receipt for a certified bundle."""
    bundle_id: str
    outcome: BundleOutcome
    profile: CertificationProfile
    claim_count: int
    signature: str
    public_key: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_url: Optional[str] = None


# =============================================================================
# Policy Models
# =============================================================================


class ValidatorConfig(BaseModel):
    """Configuration for a single validator."""
    name: str
    enabled: bool = True
    severity: Severity = Severity.BLOCK
    params: dict[str, Any] = Field(default_factory=dict)


class Policy(BaseModel):
    """Certification policy defining validation requirements."""
    policy_id: str
    profile: CertificationProfile
    description: str = ""
    validators: list[ValidatorConfig]
    require_determinism: bool = False
    require_multi_witness: bool = False
    witness_count: int = 1
    max_claims: int = 10000
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Job Models
# =============================================================================


class JobStatus(str, Enum):
    """Status of a certification job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """A certification job."""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    policy_id: str
    profile: CertificationProfile
    input_path: Optional[str] = None
    output_bundle_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# API Request/Response Models
# =============================================================================


class CertifyRequest(BaseModel):
    """Request to certify claims."""
    claims: list[NumericClaim]
    policy_id: str = "silver"
    scope_lock: ScopeLock = Field(..., description="Scope lock is mandatory - must be provided by caller")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CertifyResponse(BaseModel):
    """Response from certification."""
    bundle_id: str
    outcome: BundleOutcome
    validation_summary: ValidationSummary
    receipt: Optional[BundleReceipt] = None
    errors: list[str] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    """Request to verify a bundle."""
    bundle_id: str
    check_signature: bool = True
    check_scope_lock: bool = True
    deep_audit: bool = False


class VerifyResponse(BaseModel):
    """Response from verification."""
    bundle_id: str
    valid: bool
    signature_valid: Optional[bool] = None
    scope_lock_valid: Optional[bool] = None
    schema_valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class JobSubmitRequest(BaseModel):
    """Request to submit a new job."""
    policy_id: str = "silver"
    input_path: Optional[str] = None
    claims: Optional[list[NumericClaim]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    """Response with job details."""
    job: Job
    bundle_id: Optional[str] = None
