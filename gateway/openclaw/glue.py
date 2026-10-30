"""
OpenClaw to TruthCert glue layer.

This module provides the integration between OpenClaw runtime and TruthCert certifier.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from memory.commands import MemoryCommands


@dataclass
class CertificationResult:
    """Result from certification request."""

    bundle_id: str
    outcome: str
    errors: list[str]
    warnings: list[str]
    receipt: dict[str, Any] | None = None


class TruthCertGlue:
    """
    Glue layer for OpenClaw to TruthCert integration.

    Handles:
    - Submitting claims for certification
    - Handling responses
    - Storing results to memory
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
        memory_commands: MemoryCommands | None = None,
    ):
        self.base_url = base_url or os.environ.get("TRUTHCERT_URL", "http://localhost:8000")
        self.timeout = int(os.environ.get("TRUTHCERT_TIMEOUT", timeout))
        self.memory = memory_commands or MemoryCommands()
        self.client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def certify_claims(
        self,
        claims: list[dict[str, Any]],
        policy_id: str = "silver",
        metadata: dict[str, Any] | None = None,
        store_result: bool = True,
    ) -> CertificationResult:
        """
        Submit claims for certification.

        Args:
            claims: List of claim dictionaries
            policy_id: Policy to use (bronze, silver, gold)
            metadata: Optional metadata
            store_result: Store result to memory

        Returns:
            CertificationResult
        """
        try:
            response = self.client.post(
                "/certify",
                json={
                    "claims": claims,
                    "policy_id": policy_id,
                    "metadata": metadata or {},
                },
            )
            response.raise_for_status()
            data = response.json()

            result = CertificationResult(
                bundle_id=data.get("bundle_id", ""),
                outcome=data.get("outcome", "UNKNOWN"),
                errors=data.get("errors", []),
                warnings=[],
                receipt=data.get("receipt"),
            )

            # Store to memory if enabled
            if store_result:
                self._store_certification_result(result, policy_id, len(claims))

            return result

        except httpx.HTTPError as e:
            return CertificationResult(
                bundle_id="",
                outcome="ERROR",
                errors=[str(e)],
                warnings=[],
            )

    def verify_bundle(
        self,
        bundle_id: str,
        check_signature: bool = True,
        check_scope_lock: bool = True,
    ) -> dict[str, Any]:
        """
        Verify a bundle.

        Args:
            bundle_id: Bundle ID to verify
            check_signature: Verify signature
            check_scope_lock: Verify scope lock hash

        Returns:
            Verification result
        """
        try:
            response = self.client.post(
                "/verify",
                json={
                    "bundle_id": bundle_id,
                    "check_signature": check_signature,
                    "check_scope_lock": check_scope_lock,
                },
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "valid": False,
                "errors": [str(e)],
            }

    def submit_job(
        self,
        policy_id: str = "silver",
        input_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Submit a certification job.

        Args:
            policy_id: Policy to use
            input_path: Path to input directory
            metadata: Optional metadata

        Returns:
            Job details
        """
        try:
            response = self.client.post(
                "/jobs",
                json={
                    "policy_id": policy_id,
                    "input_path": input_path,
                    "metadata": metadata or {},
                },
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "error": str(e),
            }

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status."""
        try:
            response = self.client.get(f"/jobs/{job_id}")
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "error": str(e),
            }

    def recall_memory(
        self,
        query: str,
        limit: int = 10,
        pack: bool = False,
    ) -> dict[str, Any]:
        """
        Recall from memory for planning.

        Note: Memory content is NOT evidence.
        """
        result = self.memory.recall_memories(query, pack=pack, limit=limit)

        # Add warning
        result["warning"] = "MEMORY IS NOT EVIDENCE - Use only for planning"

        return result

    def remember(
        self,
        text: str,
        tags: list[str] | None = None,
        memory_type: str = "note",
    ) -> dict[str, Any]:
        """Store to memory."""
        return self.memory.remember(text, tags=tags, memory_type=memory_type)

    def _store_certification_result(
        self,
        result: CertificationResult,
        policy_id: str,
        claim_count: int,
    ) -> None:
        """Store certification result to memory."""
        self.memory.capture.capture_certification_result(
            bundle_id=result.bundle_id,
            outcome=result.outcome,
            profile=policy_id.upper(),
            claim_count=claim_count,
            errors=result.errors if result.errors else None,
        )

    def health_check(self) -> bool:
        """Check if TruthCert service is healthy."""
        try:
            response = self.client.get("/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Example usage for cron jobs
def run_daily_certification(
    input_dir: str,
    policy_id: str = "silver",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """
    Run daily certification job.

    This function can be called from cron jobs.
    """
    import json
    from pathlib import Path

    input_path = Path(input_dir)
    if not input_path.exists():
        return {"error": f"Input directory not found: {input_dir}"}

    # Load claims
    claims = []
    for claims_file in input_path.glob("*.jsonl"):
        with open(claims_file) as f:
            for line in f:
                if line.strip():
                    claims.append(json.loads(line))

    if not claims:
        return {"error": "No claims found in input directory"}

    # Submit for certification
    with TruthCertGlue() as glue:
        result = glue.certify_claims(
            claims=claims,
            policy_id=policy_id,
            metadata={
                "source": "daily_cron",
                "input_dir": str(input_path),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    return {
        "bundle_id": result.bundle_id,
        "outcome": result.outcome,
        "claim_count": len(claims),
        "errors": result.errors,
    }
