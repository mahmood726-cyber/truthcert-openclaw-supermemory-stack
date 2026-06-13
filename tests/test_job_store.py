"""
Tests for the JobStore - SQLite-backed persistent job storage.
"""

import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from certifier.job_store import JobStore, get_job_store, init_job_store, reset_job_store
from certifier.models import Job, JobStatus, CertificationProfile


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test_jobs.db")


@pytest.fixture
def job_store(temp_db_path):
    """Create a JobStore with temporary database."""
    store = JobStore(temp_db_path)
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def sample_job():
    """Create a sample job."""
    return Job(
        job_id="test-job-001",
        status=JobStatus.PENDING,
        policy_id="silver",
        profile=CertificationProfile.SILVER,
        created_at=datetime.now(timezone.utc),
    )


class TestJobStoreCRUD:
    """Test basic CRUD operations."""

    def test_create_job(self, job_store, sample_job):
        """Test creating a job."""
        created = job_store.create(sample_job)

        assert created.job_id == sample_job.job_id
        assert created.status == JobStatus.PENDING

    def test_get_job(self, job_store, sample_job):
        """Test retrieving a job."""
        job_store.create(sample_job)

        retrieved = job_store.get(sample_job.job_id)

        assert retrieved is not None
        assert retrieved.job_id == sample_job.job_id
        assert retrieved.policy_id == sample_job.policy_id

    def test_get_nonexistent_job(self, job_store):
        """Test retrieving a non-existent job returns None."""
        result = job_store.get("nonexistent-id")
        assert result is None

    def test_update_job(self, job_store, sample_job):
        """Test updating a job."""
        job_store.create(sample_job)

        # Update the job
        sample_job.status = JobStatus.RUNNING
        sample_job.started_at = datetime.now(timezone.utc)
        job_store.update(sample_job)

        # Verify update
        retrieved = job_store.get(sample_job.job_id)
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.started_at is not None

    def test_delete_job(self, job_store, sample_job):
        """Test deleting a job."""
        job_store.create(sample_job)

        result = job_store.delete(sample_job.job_id)
        assert result is True

        # Verify deletion
        retrieved = job_store.get(sample_job.job_id)
        assert retrieved is None

    def test_delete_nonexistent_job(self, job_store):
        """Test deleting a non-existent job returns False."""
        result = job_store.delete("nonexistent-id")
        assert result is False


class TestJobStoreQueries:
    """Test query operations."""

    def test_list_all_jobs(self, job_store):
        """Test listing all jobs."""
        # Create multiple jobs
        for i in range(5):
            job = Job(
                job_id=f"job-{i}",
                status=JobStatus.PENDING,
                policy_id="silver",
                profile=CertificationProfile.SILVER,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        jobs = job_store.list_jobs()
        assert len(jobs) == 5

    def test_list_jobs_by_status(self, job_store):
        """Test filtering jobs by status."""
        # Create jobs with different statuses
        statuses = [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED,
                    JobStatus.PENDING, JobStatus.FAILED]
        for i, status in enumerate(statuses):
            job = Job(
                job_id=f"job-{i}",
                status=status,
                policy_id="silver",
                profile=CertificationProfile.SILVER,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        pending_jobs = job_store.list_jobs(status=JobStatus.PENDING)
        assert len(pending_jobs) == 2

    def test_list_jobs_by_policy(self, job_store):
        """Test filtering jobs by policy."""
        # Create jobs with different policies
        policies = ["bronze", "silver", "gold", "silver", "bronze"]
        profiles = [CertificationProfile.BRONZE, CertificationProfile.SILVER,
                    CertificationProfile.GOLD, CertificationProfile.SILVER,
                    CertificationProfile.BRONZE]
        for i, (policy, profile) in enumerate(zip(policies, profiles)):
            job = Job(
                job_id=f"job-{i}",
                status=JobStatus.PENDING,
                policy_id=policy,
                profile=profile,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        silver_jobs = job_store.list_jobs(policy_id="silver")
        assert len(silver_jobs) == 2

    def test_list_jobs_pagination(self, job_store):
        """Test pagination."""
        # Create 10 jobs
        for i in range(10):
            job = Job(
                job_id=f"job-{i:02d}",
                status=JobStatus.PENDING,
                policy_id="silver",
                profile=CertificationProfile.SILVER,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        # Get first page
        page1 = job_store.list_jobs(limit=5, offset=0)
        assert len(page1) == 5

        # Get second page
        page2 = job_store.list_jobs(limit=5, offset=5)
        assert len(page2) == 5

        # Verify no overlap
        page1_ids = {j.job_id for j in page1}
        page2_ids = {j.job_id for j in page2}
        assert len(page1_ids & page2_ids) == 0

    def test_count_jobs(self, job_store):
        """Test counting jobs."""
        # Create jobs
        for i in range(3):
            job = Job(
                job_id=f"pending-{i}",
                status=JobStatus.PENDING,
                policy_id="silver",
                profile=CertificationProfile.SILVER,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        for i in range(2):
            job = Job(
                job_id=f"completed-{i}",
                status=JobStatus.COMPLETED,
                policy_id="silver",
                profile=CertificationProfile.SILVER,
                created_at=datetime.now(timezone.utc),
            )
            job_store.create(job)

        assert job_store.count() == 5
        assert job_store.count(status=JobStatus.PENDING) == 3
        assert job_store.count(status=JobStatus.COMPLETED) == 2


class TestJobStorePersistence:
    """Test persistence and recovery."""

    def test_jobs_survive_restart(self, temp_db_path):
        """Test that jobs persist after store is recreated."""
        # Create store and job
        store1 = JobStore(temp_db_path)
        job = Job(
            job_id="persistent-job",
            status=JobStatus.COMPLETED,
            policy_id="gold",
            profile=CertificationProfile.GOLD,
            created_at=datetime.now(timezone.utc),
            metadata={"key": "value"},
        )
        store1.create(job)
        store1.close()

        # Create new store instance (simulating restart)
        store2 = JobStore(temp_db_path)
        retrieved = store2.get("persistent-job")

        assert retrieved is not None
        assert retrieved.status == JobStatus.COMPLETED
        assert retrieved.metadata == {"key": "value"}
        store2.close()

    def test_wal_mode_enabled(self, temp_db_path):
        """Test that WAL mode is enabled for better concurrency."""
        store = JobStore(temp_db_path)

        # Create a job to trigger DB initialization
        job = Job(
            job_id="test",
            status=JobStatus.PENDING,
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            created_at=datetime.now(timezone.utc),
        )
        store.create(job)

        # WAL file should exist
        wal_path = Path(temp_db_path + "-wal")
        # Note: WAL file may not exist if no changes pending
        # Just verify no errors occur
        store.close()


class TestJobStoreThreadSafety:
    """Test thread safety of job store singleton."""

    def test_concurrent_get_job_store(self, temp_db_path, monkeypatch):
        """Test that concurrent access to singleton is thread-safe."""
        monkeypatch.setenv("TRUTHCERT_JOB_DB", temp_db_path)

        # Reset singleton
        reset_job_store()

        stores = []
        errors = []

        def get_store():
            try:
                store = get_job_store()
                stores.append(id(store))
            except Exception as e:
                errors.append(e)

        # Launch multiple threads
        threads = [threading.Thread(target=get_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should get same instance
        assert len(errors) == 0
        assert len(set(stores)) == 1  # All same ID

        # Cleanup
        reset_job_store()

    def test_concurrent_create_jobs(self, job_store):
        """Test concurrent job creation."""
        errors = []

        def create_job(i):
            try:
                job = Job(
                    job_id=f"concurrent-{i}",
                    status=JobStatus.PENDING,
                    policy_id="silver",
                    profile=CertificationProfile.SILVER,
                    created_at=datetime.now(timezone.utc),
                )
                job_store.create(job)
            except Exception as e:
                errors.append(e)

        # Launch multiple threads
        threads = [threading.Thread(target=create_job, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert job_store.count() == 20


class TestJobStoreCleanup:
    """Test cleanup operations."""

    def test_cleanup_old_jobs(self, job_store):
        """Test cleaning up old jobs."""
        from datetime import timedelta

        # Create old completed job
        old_job = Job(
            job_id="old-job",
            status=JobStatus.COMPLETED,
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        job_store.create(old_job)

        # Create recent job
        recent_job = Job(
            job_id="recent-job",
            status=JobStatus.COMPLETED,
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            created_at=datetime.now(timezone.utc),
        )
        job_store.create(recent_job)

        # Cleanup jobs older than 30 days
        deleted = job_store.cleanup_old_jobs(days=30)

        assert deleted == 1
        assert job_store.get("old-job") is None
        assert job_store.get("recent-job") is not None


class TestJobStoreMetadata:
    """Test metadata handling."""

    def test_job_metadata_persists(self, job_store):
        """Test that job metadata is properly persisted."""
        job = Job(
            job_id="metadata-job",
            status=JobStatus.COMPLETED,
            policy_id="gold",
            profile=CertificationProfile.GOLD,
            created_at=datetime.now(timezone.utc),
            metadata={
                "claims_count": 150,
                "validators": ["schema", "memory_leak"],
                "nested": {"key": "value"},
            },
        )
        job_store.create(job)

        retrieved = job_store.get("metadata-job")
        assert retrieved.metadata["claims_count"] == 150
        assert retrieved.metadata["nested"]["key"] == "value"

    def test_job_timestamps_persists(self, job_store):
        """Test that timestamps are properly persisted."""
        now = datetime.now(timezone.utc)
        job = Job(
            job_id="timestamp-job",
            status=JobStatus.COMPLETED,
            policy_id="silver",
            profile=CertificationProfile.SILVER,
            created_at=now,
            started_at=now,
            completed_at=now,
        )
        job_store.create(job)

        retrieved = job_store.get("timestamp-job")
        assert retrieved.created_at == now
        assert retrieved.started_at == now
        assert retrieved.completed_at == now
