"""
Bundle generation and management for TruthCert.
"""

import hashlib
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import (
    ATTEST_DIR,
    AUDIT_LOG_FILE,
    CAPSULE_DIR,
    CLAIMS_FILE,
    DEFAULT_BUNDLE_DIR,
    ENV_BUNDLE_DIR,
    HASH_PREFIX,
    MANIFEST_FILE,
    OUTPUTS_DIR,
    PROVENANCE_FILE,
    PUBLIC_KEY_FILE,
    RECEIPT_FILE,
    SCOPE_LOCK_FILE,
    SIGNATURE_FILE,
    TELEMETRY_FILE,
    BundleOutcome,
)
from .models import (
    BundleManifest,
    NumericClaim,
    ScopeLock,
    ValidationSummary,
)
from .signing import create_receipt, sign_manifest


def get_bundle_dir() -> Path:
    """Get the bundle storage directory."""
    bundle_dir = Path(os.environ.get(ENV_BUNDLE_DIR, DEFAULT_BUNDLE_DIR))
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return bundle_dir


def compute_bundle_id(
    claims: list[NumericClaim],
    scope_lock: ScopeLock,
    policy_id: str,
    claims_sha256: str | None = None,
) -> str:
    """Derive a deterministic v2 full-payload ID or historical v1 claim ID."""
    # No new bundle may reuse a legacy ID after changing an unbound CI bound,
    # evidence URI or provenance field. Existing v1 callers keep their IDs.
    source = (
        {"claims_sha256": claims_sha256}
        if claims_sha256 is not None
        else {"claim_hashes": sorted([c.compute_hash() for c in claims])}
    )
    canonical = json.dumps(
        {
            "policy_id": policy_id,
            "scope_lock_hash": scope_lock.compute_hash(),
            **source,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{HASH_PREFIX}{digest}"


def create_bundle_structure(bundle_id: str, bundle_dir: Path | None = None) -> Path:
    """Create a bundle directory under the selected root."""
    bundle_dir = bundle_dir if bundle_dir is not None else get_bundle_dir()
    # Use short hash for directory name
    short_id = bundle_id.replace(HASH_PREFIX, "")[:16]
    bundle_path = bundle_dir / f"bundle_{short_id}"

    # Create directories
    bundle_path.mkdir(parents=True, exist_ok=True)
    (bundle_path / OUTPUTS_DIR).mkdir(exist_ok=True)
    (bundle_path / CAPSULE_DIR).mkdir(exist_ok=True)
    (bundle_path / ATTEST_DIR).mkdir(exist_ok=True)

    return bundle_path


def write_claims_jsonl(bundle_path: Path, claims: list[NumericClaim]) -> None:
    """Write claims to JSONL file."""
    claims_file = bundle_path / CLAIMS_FILE
    # Commit the exact UTF-8 bytes that the v2 manifest hashes. Text-mode
    # writing translates newlines to CRLF on Windows and made otherwise
    # correct synthetic claim bundles refuse signing on that platform.
    payload = "".join(claim.model_dump_json() + "\n" for claim in claims).encode("utf-8")
    claims_file.write_bytes(payload)


def write_scope_lock(bundle_path: Path, scope_lock: ScopeLock) -> None:
    """Write scope lock to JSON file."""
    scope_lock_file = bundle_path / SCOPE_LOCK_FILE
    with open(scope_lock_file, "w") as f:
        json.dump(scope_lock.model_dump(mode="json"), f, indent=2, default=str)


def write_provenance(
    bundle_path: Path,
    claims: list[NumericClaim],
    metadata: dict[str, Any],
) -> None:
    """Write provenance records to JSONL file."""
    provenance_file = bundle_path / PROVENANCE_FILE
    with open(provenance_file, "w") as f:
        # Write bundle-level provenance
        f.write(
            json.dumps(
                {
                    "type": "bundle_creation",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "claim_count": len(claims),
                    "metadata": metadata,
                }
            )
            + "\n"
        )

        # Write claim-level provenance
        f.writelines(
            json.dumps(
                {
                    "type": "claim",
                    "claim_id": claim.claim_id,
                    "claim_hash": claim.compute_hash(),
                    "evidence_count": len(claim.evidence),
                    "evidence_hashes": [e.content_hash for e in claim.evidence],
                    "provenance": claim.provenance,
                }
            )
            + "\n"
            for claim in claims
        )


def write_manifest(
    bundle_path: Path,
    manifest: BundleManifest,
) -> None:
    """Write manifest to JSON file."""
    manifest_file = bundle_path / MANIFEST_FILE
    with open(manifest_file, "w") as f:
        json.dump(manifest.model_dump(mode="json"), f, indent=2, default=str)


def write_attestation(
    bundle_path: Path,
    manifest_data: dict[str, Any],
    verification_url: str | None = None,
) -> dict[str, Any]:
    """
    Sign the manifest and write attestation files.

    Returns:
        Receipt dictionary
    """
    attest_path = bundle_path / ATTEST_DIR

    # Sign manifest
    signature_b64, public_key_b64 = sign_manifest(manifest_data)

    # Write signature
    sig_file = attest_path / SIGNATURE_FILE
    sig_file.write_text(signature_b64)

    # Write public key
    pubkey_file = attest_path / PUBLIC_KEY_FILE
    pubkey_file.write_text(public_key_b64)

    # Create and write receipt
    receipt = create_receipt(
        bundle_id=manifest_data["bundle_id"],
        outcome=manifest_data["outcome"],
        profile=manifest_data["profile"],
        claim_count=manifest_data["claim_count"],
        signature_b64=signature_b64,
        public_key_b64=public_key_b64,
        verification_url=verification_url,
    )

    receipt_file = attest_path / RECEIPT_FILE
    with open(receipt_file, "w") as f:
        json.dump(receipt, f, indent=2)

    return receipt


def create_bundle(
    claims: list[NumericClaim],
    scope_lock: ScopeLock,
    policy_id: str,
    validation_summary: ValidationSummary,
    validators: list[str],
    model_metadata: dict[str, Any] | None = None,
    tool_metadata: dict[str, Any] | None = None,
    sign: bool = True,
    verification_url: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Create a complete certification bundle.

    Returns:
        Tuple of (bundle_path, receipt_or_manifest)
    """
    # Determine outcome
    outcome = BundleOutcome.PASS if validation_summary.all_passed else BundleOutcome.REJECT

    # V2 identity includes every serialized clinical field, not just the
    # historical claim hash subset. Unicode bytes are always UTF-8.
    claim_bytes = "".join(c.model_dump_json() + "\n" for c in claims).encode("utf-8")
    expected_claims_sha256 = f"{HASH_PREFIX}{hashlib.sha256(claim_bytes).hexdigest()}"
    bundle_id = compute_bundle_id(
        claims,
        scope_lock,
        policy_id,
        claims_sha256=expected_claims_sha256,
    )

    # Stage all artifacts privately: incomplete signed bundles must not be visible.
    bundle_root = get_bundle_dir()
    final_bundle_path = bundle_root / f"bundle_{bundle_id.removeprefix(HASH_PREFIX)[:16]}"
    if final_bundle_path.exists() or final_bundle_path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite an existing bundle: {final_bundle_path}")

    with tempfile.TemporaryDirectory(prefix=".tc-stage-", dir=bundle_root) as stage_dir:
        bundle_path = create_bundle_structure(bundle_id, bundle_dir=Path(stage_dir))

        # Write claims and bind their exact serialized bytes into the signed v2 manifest.
        # The historical bundle_id algorithm remains intact; v1 signed artifacts are
        # preserved, but cannot be promoted to complete-payload certification.
        write_claims_jsonl(bundle_path, claims)
        claims_sha256 = (
            f"{HASH_PREFIX}{hashlib.sha256((bundle_path / CLAIMS_FILE).read_bytes()).hexdigest()}"
        )
        if claims_sha256 != expected_claims_sha256:
            raise ValueError("Serialized claims bytes changed before signing")

        # Write scope lock
        write_scope_lock(bundle_path, scope_lock)

        # Write provenance
        write_provenance(
            bundle_path,
            claims,
            metadata={
                "policy_id": policy_id,
                "profile": scope_lock.profile.value,
                "model_metadata": model_metadata or {},
                "tool_metadata": tool_metadata or {},
            },
        )

        # Create manifest
        manifest = BundleManifest(
            bundle_id=bundle_id,
            policy_id=policy_id,
            profile=scope_lock.profile,
            outcome=outcome,
            scope_lock_hash=scope_lock.compute_hash(),
            claim_count=len(claims),
            claims_sha256=claims_sha256,
            validators=validators,
            validation_summary=validation_summary,
            model_metadata=model_metadata or {},
            tool_metadata=tool_metadata or {},
        )

        # Write manifest
        write_manifest(bundle_path, manifest)

        # Initialize empty files
        (bundle_path / AUDIT_LOG_FILE).touch()
        (bundle_path / TELEMETRY_FILE).touch()

        # Sign and create receipt if enabled
        result: dict[str, Any]
        if sign:
            # A requested signature is mandatory: never return a PASS-shaped
            # unsigned manifest if signing, key loading, or file writing fails.
            # Leave the exception visible to the calling API/CLI, which must
            # not construct a certification receipt from an unsigned artifact.
            result = write_attestation(
                bundle_path,
                manifest.model_dump(mode="json"),
                verification_url=verification_url,
            )
        else:
            # Explicit unsigned mode is noncertifying, for fixtures/tools only.
            result = manifest.model_dump(mode="json")

        # Do not overwrite a historical bundle if another writer published first.
        if final_bundle_path.exists() or final_bundle_path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite an existing bundle: {final_bundle_path}")
        bundle_path.rename(final_bundle_path)
        return final_bundle_path, result


def create_bundle_tarball(bundle_path: Path) -> Path:
    """Create a tarball of the bundle."""
    tarball_path = bundle_path.with_suffix(".tar.gz")
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(bundle_path, arcname=bundle_path.name)
    return tarball_path


def load_bundle(bundle_path: Path) -> dict[str, Any]:
    """Load a bundle from disk."""
    manifest_file = bundle_path / MANIFEST_FILE
    if not manifest_file.exists():
        raise FileNotFoundError(f"Bundle manifest not found: {manifest_file}")

    with open(manifest_file) as f:
        manifest = json.load(f)

    # Load claims
    claims = []
    claims_file = bundle_path / CLAIMS_FILE
    if claims_file.exists():
        with open(claims_file) as f:
            for line in f:
                if line.strip():
                    claims.append(json.loads(line))

    # Load scope lock
    scope_lock = None
    scope_lock_file = bundle_path / SCOPE_LOCK_FILE
    if scope_lock_file.exists():
        with open(scope_lock_file) as f:
            scope_lock = json.load(f)

    return {
        "manifest": manifest,
        "claims": claims,
        "scope_lock": scope_lock,
        "path": str(bundle_path),
    }


def claims_payload_problems(bundle_path: Path, manifest: dict[str, Any]) -> list[str]:
    """Fail closed unless the complete claims file is covered by a v2 signature.

    The historical v1 bundle ID hashes only selected claim fields; it does not
    authenticate CI bounds, sample sizes, provenance, or every evidence field.
    Never treat its valid manifest signature as complete claims verification.
    """
    if manifest.get("version") != "tc-bundle-v2":
        return ["NONCERTIFYING: legacy manifest has no signed full claims payload digest"]
    expected = manifest.get("claims_sha256")
    if (
        not isinstance(expected, str)
        or not expected.startswith(HASH_PREFIX)
        or len(expected) != len(HASH_PREFIX) + 64
        or any(c not in "0123456789abcdef" for c in expected[len(HASH_PREFIX) :])
    ):
        return ["Missing or invalid signed claims_sha256"]
    try:
        raw = (bundle_path / CLAIMS_FILE).read_bytes()
    except OSError:
        return ["Missing or unreadable claims.jsonl"]
    observed = f"{HASH_PREFIX}{hashlib.sha256(raw).hexdigest()}"
    if observed != expected:
        return ["Signed claims payload digest mismatch"]
    try:
        lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
        if not lines:
            return ["Empty claims.jsonl cannot establish a certified claim"]
        if any(not isinstance(json.loads(line), dict) for line in lines):
            return ["Malformed JSON claim entry"]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["Malformed claims.jsonl"]
    if manifest.get("claim_count") != len(lines):
        return ["Signed claim_count does not match claims.jsonl"]
    try:
        parsed_claims = [NumericClaim.model_validate(json.loads(line)) for line in lines]
        scope_data = json.loads((bundle_path / SCOPE_LOCK_FILE).read_text(encoding="utf-8"))
        scope = ScopeLock.model_validate(scope_data)
    except (OSError, ValueError, TypeError):
        return ["Cannot reconstruct signed claim identities and scope"]
    if scope.policy_id != manifest.get("policy_id") or scope.profile.value != manifest.get(
        "profile"
    ):
        return ["Signed policy/profile does not match scope lock"]
    if compute_bundle_id(
        parsed_claims, scope, scope.policy_id, claims_sha256=expected
    ) != manifest.get("bundle_id"):
        return ["Signed bundle_id disagrees with claims and scope"]
    return []


def list_bundles(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """List bundles with minimal manifest data."""
    bundle_dir = get_bundle_dir()
    bundles = []

    # Get bundle directories sorted by modification time
    bundle_paths = sorted(
        [p for p in bundle_dir.iterdir() if p.is_dir() and p.name.startswith("bundle_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Apply pagination
    for bundle_path in bundle_paths[offset : offset + limit]:
        manifest_file = bundle_path / MANIFEST_FILE
        if manifest_file.exists():
            try:
                with open(manifest_file) as f:
                    manifest = json.load(f)
                bundles.append(
                    {
                        "bundle_id": manifest.get("bundle_id"),
                        "outcome": manifest.get("outcome"),
                        "profile": manifest.get("profile"),
                        "claim_count": manifest.get("claim_count"),
                        "created_at": manifest.get("created_at"),
                        "path": str(bundle_path),
                    }
                )
            except json.JSONDecodeError:
                continue

    return bundles
