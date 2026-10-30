"""
Pytest configuration and shared fixtures.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from certifier.models import (
    CertificationProfile,
    ClaimType,
    EvidenceLocator,
    EvidenceType,
    NumericClaim,
    Policy,
    ScopeLock,
    ValidatorConfig,
)
from certifier.signing import generate_keypair
from memory.backend_local_sqlite import LocalSQLiteBackend
from memory.schema import MemoryItem, MemoryProfile, MemorySource, MemoryType


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def signing_keys(monkeypatch):
    """Generate and set signing keys for tests."""
    private_b64, public_b64 = generate_keypair()
    monkeypatch.setenv("TRUTHCERT_SIGNING_KEY", private_b64)
    monkeypatch.setenv("TRUTHCERT_PUBLIC_KEY", public_b64)
    return private_b64, public_b64


@pytest.fixture
def sample_evidence():
    """Create sample evidence locator."""
    return EvidenceLocator(
        source_type=EvidenceType.OA_DOCUMENT,
        uri="https://example.com/paper.pdf",
        content_hash="sha256:abcd1234567890abcd1234567890abcd1234567890abcd1234567890abcd1234",
        extracted_at=datetime.now(UTC),
        page=5,
        section="Results",
    )


@pytest.fixture
def sample_claim(sample_evidence):
    """Create a sample valid claim."""
    return NumericClaim(
        claim_id="test-claim-001",
        claim_type=ClaimType.EFFECT_SIZE,
        value=0.45,
        unit="d",
        precision=2,
        confidence_level=0.95,
        lower_bound=0.25,
        upper_bound=0.65,
        evidence=[sample_evidence],
        provenance={"method": "extraction"},
    )


@pytest.fixture
def memory_claim():
    """Create a claim that incorrectly cites memory as evidence."""
    return NumericClaim(
        claim_id="memory-claim-001",
        claim_type=ClaimType.SAMPLE_SIZE,
        value=100,
        evidence=[
            EvidenceLocator(
                source_type=EvidenceType.OA_DOCUMENT,  # Lying about source
                uri="memory:recall-123",  # But URI reveals memory source
                content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            )
        ],
    )


@pytest.fixture
def sample_scope_lock():
    """Create a sample scope lock."""
    return ScopeLock(
        scope_id="test-scope-001",
        policy_id="silver",
        profile=CertificationProfile.SILVER,
        allowed_sources=["oa_document", "fixture"],
        required_validators=["schema", "no_naked_numbers", "memory_leak"],
    )


@pytest.fixture
def bronze_policy():
    """Create a bronze policy."""
    return Policy(
        policy_id="bronze",
        profile=CertificationProfile.BRONZE,
        validators=[
            ValidatorConfig(name="schema", enabled=True),
            ValidatorConfig(name="no_naked_numbers", enabled=True),
            ValidatorConfig(name="memory_leak", enabled=True),
        ],
    )


@pytest.fixture
def silver_policy():
    """Create a silver policy."""
    return Policy(
        policy_id="silver",
        profile=CertificationProfile.SILVER,
        validators=[
            ValidatorConfig(name="schema", enabled=True),
            ValidatorConfig(name="scope_lock", enabled=True),
            ValidatorConfig(name="no_naked_numbers", enabled=True),
            ValidatorConfig(name="memory_leak", enabled=True),
            ValidatorConfig(name="determinism", enabled=True),
            ValidatorConfig(name="multi_witness", enabled=True),
        ],
        require_determinism=True,
        require_multi_witness=True,
        witness_count=2,
    )


@pytest.fixture
def memory_db(temp_dir):
    """Create a temporary memory database."""
    db_path = temp_dir / "test_memory.db"
    return LocalSQLiteBackend(str(db_path))


@pytest.fixture
def memory_profile():
    """Create a test memory profile."""
    return MemoryProfile(
        name="test",
        auto_recall=True,
        auto_capture=True,
        max_recall_results=10,
        max_inject_chars=4000,
        redact_before_store=True,
    )


@pytest.fixture
def sample_memory_item():
    """Create a sample memory item."""
    return MemoryItem(
        type=MemoryType.NOTE,
        source=MemorySource.CHAT,
        text="This is a test memory note about meta-analysis methods.",
        tags=["test", "meta-analysis"],
    )


@pytest.fixture(autouse=True)
def setup_test_env(temp_dir, monkeypatch):
    """Setup test environment."""
    # Set bundle directory
    monkeypatch.setenv("TRUTHCERT_BUNDLE_DIR", str(temp_dir / "bundles"))

    # Set log directory
    monkeypatch.setenv("TRUTHCERT_LOG_DIR", str(temp_dir / "logs"))

    # Set memory DB
    monkeypatch.setenv("TRUTHCERT_MEMORY_DB", str(temp_dir / "memory.db"))

    # Set job DB (for job_store tests)
    monkeypatch.setenv("TRUTHCERT_DB_PATH", str(temp_dir / "jobs.db"))

    # Ensure directories exist
    (temp_dir / "bundles").mkdir(exist_ok=True)
    (temp_dir / "logs").mkdir(exist_ok=True)

    # Reset job store singleton after each test
    yield

    # Cleanup: reset job store singleton
    from certifier.job_store import reset_job_store

    reset_job_store()
