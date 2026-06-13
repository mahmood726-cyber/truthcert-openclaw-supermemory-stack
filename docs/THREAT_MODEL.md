# Threat Model

## Overview

This document describes the security considerations for the TruthCert + OpenClaw + Supermemory stack.

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                      UNTRUSTED ZONE                              │
│  - External data sources                                         │
│  - User input                                                    │
│  - Memory content                                                │
│  - Model outputs                                                 │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                        ┌───────▼───────┐
                        │  VALIDATION   │
                        │   BOUNDARY    │
                        └───────┬───────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                      TRUSTED ZONE                                │
│  - Signed bundles                                                │
│  - Verified evidence                                             │
│  - Validated claims                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Threat Categories

### T1: Memory Contamination

**Threat**: Memory content used as evidence for certification.

**Mitigations**:
- MEMORY_LEAK validator blocks `memory:` URI prefixes
- Source type validation rejects `memory` as evidence type
- Context packer includes explicit warning
- All memory content marked as "untrusted"

### T2: Signature Forgery

**Threat**: Forged bundle signatures to claim false certification.

**Mitigations**:
- Ed25519 signatures (128-bit security)
- Private keys stored only in environment variables
- Public keys included in bundles for verification
- Receipt includes signature metadata

### T3: Bundle Tampering

**Threat**: Modifying bundle contents after certification.

**Mitigations**:
- Content-addressed bundle IDs (SHA-256)
- Scope lock hash verification
- Manifest signing
- Immutable bundle structure

### T4: Evidence Substitution

**Threat**: Replacing evidence with different content after hash computation.

**Mitigations**:
- Content hashes computed at extraction time
- Evidence cache with deduplication
- Hash verification on retrieval
- Provenance tracking

### T5: Privilege Escalation

**Threat**: Agent gaining elevated tool permissions.

**Mitigations**:
- Reader/Worker agent separation
- Tool allowlist enforcement
- Sandbox isolation
- No default elevated permissions

### T6: Secret Leakage

**Threat**: Secrets captured in memory and exposed.

**Mitigations**:
- Automatic redaction before storage
- Sensitive tool denylist
- No secrets in bundles
- Key-only via environment variables

### T7: Denial of Service

**Threat**: Resource exhaustion through excessive requests.

**Mitigations**:
- Rate limiting on all endpoints
- Request size limits
- Claim count limits
- Pagination for listings

### T8: Path Traversal

**Threat**: Accessing files outside allowed directories.

**Mitigations**:
- Bundle ID validation (alphanumeric only)
- No `..` in paths
- Sandboxed file operations

### T9: Injection Attacks

**Threat**: HTML/XSS injection in rendered output.

**Mitigations**:
- HTML escaping in renderer
- Content Security Policy headers
- Sanitized output

### T10: Model Manipulation

**Threat**: Model producing claims from hallucinated evidence.

**Mitigations**:
- Evidence hash verification
- No naked numbers validator
- Multi-witness requirement (SILVER/GOLD)
- Determinism validation

## Security Principles

### 1. Fail-Closed

If any blocking validator fails, certification is rejected. No exceptions.

### 2. Memory is Never Evidence

This is the core security boundary. Memory can inform planning but is never sufficient to establish claims.

### 3. Deny by Default

- Tools require explicit allowlisting
- Sources require explicit approval
- Validators block by default

### 4. Signed Releases

Production deployments should verify package signatures:

```bash
# Verify signature (conceptual)
gpg --verify truthcert-1.0.0.tar.gz.sig truthcert-1.0.0.tar.gz
```

### 5. No Secrets in Bundles

Bundles must never contain:
- API keys
- Passwords
- Private keys
- Personal identifiers

### 6. Safe Mounts

When running in containers:
- Read-only source mounts
- Isolated bundle directory
- No host network access

## Attack Scenarios

### Scenario: Memory Leak Attack

1. Attacker stores fake "evidence" in memory
2. Creates claim citing `memory:fake-evidence`
3. Attempts certification

**Result**: MEMORY_LEAK validator blocks with REJECT bundle.

### Scenario: Signature Bypass

1. Attacker creates fake bundle
2. Signs with own keypair
3. Attempts to pass as legitimate

**Result**: Signature verification fails (wrong public key).

### Scenario: Hash Collision

1. Attacker finds content with same hash as legitimate evidence
2. Substitutes content

**Result**: SHA-256 collision is computationally infeasible (2^128 operations).

## Incident Response

If a security issue is discovered:

1. Do NOT commit secrets
2. Rotate any exposed keys immediately
3. Audit bundle logs for anomalies
4. Review memory for sensitive data
5. Consider `tc memory wipe --yes` if compromised

## Compliance Considerations

For regulated environments (GOLD profile):

- 3-witness requirement for critical fields
- Full audit trail in bundles
- Deterministic computation verification
- Evidence archival
