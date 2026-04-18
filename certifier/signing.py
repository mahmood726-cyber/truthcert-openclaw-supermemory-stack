"""
Ed25519 digital signing for TruthCert bundles.
"""

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from .constants import (
    ENV_SIGNING_KEY,
    ENV_PUBLIC_KEY,
    HASH_PREFIX,
)
from .errors import ConfigurationError, TruthCertError, ErrorCode


class SigningError(TruthCertError):
    """Error during signing operations."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.SIGNING_ERROR,
            status_code=500,
            details=details or {},
        )


class VerificationError(TruthCertError):
    """Error during verification operations."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.VERIFICATION_ERROR,
            status_code=400,
            details=details or {},
        )


def generate_keypair() -> tuple[str, str]:
    """
    Generate a new Ed25519 keypair.

    Returns:
        Tuple of (private_key_b64, public_key_b64)
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return (
        base64.b64encode(private_bytes).decode("utf-8"),
        base64.b64encode(public_bytes).decode("utf-8"),
    )


def save_keypair(
    private_key_path: Path,
    public_key_path: Path,
) -> tuple[str, str]:
    """
    Generate and save a keypair to files with secure permissions.

    Returns:
        Tuple of (private_key_b64, public_key_b64)

    Note:
        On Unix systems, private key is saved with 0o600 permissions.
        On Windows, chmod is not effective - consider using environment
        variables or a secure key store instead of file-based keys.
    """
    private_b64, public_b64 = generate_keypair()

    # Write private key with restricted permissions
    private_key_path.write_text(private_b64)
    try:
        os.chmod(private_key_path, 0o600)  # Owner read/write only
    except OSError:
        # Windows does not support Unix-style chmod
        # SECURITY NOTE: On Windows, use environment variables or
        # Windows Credential Manager instead of file-based keys
        import warnings
        warnings.warn(
            f"Could not set secure permissions on {private_key_path}. "
            "On Windows, consider using environment variables for key storage.",
            RuntimeWarning,
        )

    # Write public key (no special permissions needed)
    public_key_path.write_text(public_b64)

    return private_b64, public_b64


def load_private_key() -> Ed25519PrivateKey:
    """
    Load private key from environment variable.

    Raises:
        ConfigurationError: If key is not configured or invalid
    """
    key_b64 = os.environ.get(ENV_SIGNING_KEY)
    if not key_b64:
        raise ConfigurationError(
            message="Signing key not configured",
            hint=f"Set {ENV_SIGNING_KEY} environment variable with base64-encoded Ed25519 private key",
        )

    try:
        key_bytes = base64.b64decode(key_b64)
        return Ed25519PrivateKey.from_private_bytes(key_bytes)
    except Exception as e:
        raise ConfigurationError(
            message=f"Invalid signing key: {e}",
            details={"error": str(e)},
        )


def load_public_key(key_b64: Optional[str] = None) -> Ed25519PublicKey:
    """
    Load public key from string or environment variable.

    Args:
        key_b64: Base64-encoded public key, or None to load from env

    Raises:
        ConfigurationError: If key is invalid
    """
    if key_b64 is None:
        key_b64 = os.environ.get(ENV_PUBLIC_KEY)
        if not key_b64:
            # Try to derive from private key
            try:
                private_key = load_private_key()
                return private_key.public_key()
            except ConfigurationError:
                raise ConfigurationError(
                    message="Public key not configured",
                    hint=f"Set {ENV_PUBLIC_KEY} environment variable",
                )

    try:
        key_bytes = base64.b64decode(key_b64)
        return Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception as e:
        raise ConfigurationError(
            message=f"Invalid public key: {e}",
            details={"error": str(e)},
        )


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of content with prefix."""
    digest = hashlib.sha256(content).hexdigest()
    return f"{HASH_PREFIX}{digest}"


def compute_manifest_hash(manifest_data: dict[str, Any]) -> str:
    """
    Compute deterministic hash of manifest for signing.
    Uses only core fields to ensure stability.
    """
    # Select only fields that should be signed
    core_fields = {
        "bundle_id": manifest_data.get("bundle_id"),
        "policy_id": manifest_data.get("policy_id"),
        "profile": manifest_data.get("profile"),
        "outcome": manifest_data.get("outcome"),
        "scope_lock_hash": manifest_data.get("scope_lock_hash"),
        "claim_count": manifest_data.get("claim_count"),
        "validators": sorted(manifest_data.get("validators", [])),
    }
    canonical = json.dumps(core_fields, sort_keys=True, separators=(",", ":"))
    return compute_content_hash(canonical.encode())


def sign_manifest(manifest_data: dict[str, Any]) -> tuple[str, str]:
    """
    Sign a manifest and return signature + public key.

    Returns:
        Tuple of (signature_b64, public_key_b64)
    """
    private_key = load_private_key()
    public_key = private_key.public_key()

    # Compute hash of manifest
    manifest_hash = compute_manifest_hash(manifest_data)

    # Sign the hash
    signature = private_key.sign(manifest_hash.encode())

    # Encode results
    signature_b64 = base64.b64encode(signature).decode("utf-8")
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_b64 = base64.b64encode(public_bytes).decode("utf-8")

    return signature_b64, public_key_b64


def verify_signature(
    manifest_data: dict[str, Any],
    signature_b64: str,
    public_key_b64: str,
) -> bool:
    """
    Verify a manifest signature.

    Returns:
        True if signature is valid

    Raises:
        VerificationError: If signature is invalid
    """
    try:
        public_key = load_public_key(public_key_b64)
        signature = base64.b64decode(signature_b64)
        manifest_hash = compute_manifest_hash(manifest_data)

        public_key.verify(signature, manifest_hash.encode())
        return True

    except InvalidSignature:
        raise VerificationError(
            message="Invalid signature",
            details={"reason": "Signature does not match manifest content"},
        )
    except Exception as e:
        raise VerificationError(
            message=f"Signature verification failed: {e}",
            details={"error": str(e)},
        )


def create_receipt(
    bundle_id: str,
    outcome: str,
    profile: str,
    claim_count: int,
    signature_b64: str,
    public_key_b64: str,
    verification_url: Optional[str] = None,
) -> dict[str, Any]:
    """Create a certification receipt."""
    return {
        "bundle_id": bundle_id,
        "outcome": outcome,
        "profile": profile,
        "claim_count": claim_count,
        "signature": signature_b64,
        "public_key": public_key_b64,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verification_url": verification_url,
    }
