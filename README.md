# TruthCert + OpenClaw + Supermemory Stack v1.0

**A fail-closed certifier architecture with local-first memory for trustworthy numeric claims in research synthesis.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

This repository provides a complete reference implementation for:

- **TruthCert**: Fail-closed certification gate for numeric claims
- **OpenClaw**: Runtime/control plane integration (placeholders)
- **Supermemory**: Local-first memory subsystem with codebase indexing

### Core Principles

1. **Fail-Closed**: If any blocking validator fails, certification fails
2. **Memory is Never Evidence**: Memory content cannot certify claims
3. **OA-Only**: Open Access documents only, no paywall bypass
4. **Local-First**: SQLite/FTS5 memory, local bundles by default

## Key Features

- 🔒 **Fail-Closed Certification**: PASS/REJECT bundle outcomes
- 🔐 **Ed25519 Signing**: Cryptographic attestation
- 📦 **Content-Addressed Bundles**: SHA-256 bundle IDs
- 🧪 **Multi-Witness Support**: 2-witness (SILVER), 3-witness (GOLD)
- 🧠 **Supermemory**: FTS5 search, auto-recall, redaction
- 📊 **Codebase Indexing**: Index repos into memory
- 🔍 **Full Audit Trail**: OpenTelemetry-style spans
- ⚡ **Rate Limiting**: Per-endpoint limits
- 🐳 **Docker Support**: Single-box and cluster modes

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/truthcert-openclaw-supermemory-stack.git
cd truthcert-openclaw-supermemory-stack

# Setup
make setup

# Generate keys
make keygen

# Set environment
export TRUTHCERT_SIGNING_KEY=$(cat keys/private.key)
export TRUTHCERT_PUBLIC_KEY=$(cat keys/public.key)

# Run tests
make test

# Start service
make run

# Run demo
make demo
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    OpenClaw Runtime (Placeholder)                │
│  [Reader Agent] ─┬─ [Worker Agent] ─── [Tool Sandbox]           │
│                  │                                               │
│                  └─────────┬─────────────────────────────────────│
└────────────────────────────┼────────────────────────────────────┘
                             │ HTTP
┌────────────────────────────▼────────────────────────────────────┐
│                     TruthCert Certifier                          │
│  [Schema] → [ScopeLock] → [MemoryLeak] → [Determinism] → [...]  │
│                             │                                    │
│              ┌──────────────┼──────────────┐                    │
│              ▼              ▼              ▼                    │
│         [PASS]         [REJECT]        [WARN]                   │
│                                                                  │
│  ═══════════════════════════════════════════════════════════   │
│  │               Ed25519 Signing + Receipts                 │   │
│  ═══════════════════════════════════════════════════════════   │
└─────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    Supermemory Subsystem                         │
│  [SQLite+FTS5] ── [Redaction] ── [Codebase Indexer]             │
│  [Recall] ─────── [Capture] ──── [Compaction]                   │
│  ════════════════════════════════════════════════════════════   │
│  │  CRITICAL: Memory is NEVER evidence for certification    │   │
│  ════════════════════════════════════════════════════════════   │
└─────────────────────────────────────────────────────────────────┘
```

## Certification Profiles

| Profile | Determinism | Evidence | Multi-Witness | Use Case |
|---------|-------------|----------|---------------|----------|
| BRONZE  | Optional    | Pointers | No            | Rapid prototyping |
| SILVER  | Required    | Cached   | 2-witness     | Publication-ready |
| GOLD    | Required    | Full     | 3-witness     | Regulatory submission |

## CLI Usage

### Certification

```bash
# Certify claims
tc certify claims.jsonl --policy silver

# Verify bundle
tc verify bundles/bundle_abc123/

# Audit bundle
tc audit bundles/bundle_abc123/ --deep

# Test domain packs
tc pack test
```

### Memory

```bash
# Remember
tc memory remember "Important insight" --tags methods --type decision

# Recall
tc memory recall "methods" --pack

# Index codebase
tc memory index-codebase --path . --max-files 400

# Compact
tc memory compact --strategy rolling --max-age-days 30

# Wipe
tc memory wipe --yes
```

## API Endpoints

| Endpoint | Method | Description | Rate Limit |
|----------|--------|-------------|------------|
| `/health` | GET | Health check | Unlimited |
| `/jobs` | POST | Submit job | 100/min |
| `/jobs/{id}` | GET | Get job status | 100/min |
| `/certify` | POST | Certify claims | 10/min |
| `/verify` | POST | Verify bundle | 60/min |
| `/bundles` | GET | List bundles | 100/min |
| `/bundles/{id}` | GET | Get bundle | 100/min |
| `/audit/{id}` | GET | Get audit log | 100/min |

## Project Structure

```
truthcert-openclaw-supermemory-stack/
├── certifier/              # Core certification logic
│   ├── main.py            # FastAPI application
│   ├── models.py          # Pydantic models
│   ├── signing.py         # Ed25519 signing
│   ├── bundle.py          # Bundle generation
│   ├── validators/        # Validation pipeline
│   └── constants.py       # Configuration
├── memory/                 # Supermemory subsystem
│   ├── backend_local_sqlite.py  # SQLite+FTS5 backend
│   ├── capture.py         # Auto-capture hooks
│   ├── recall.py          # Search and ranking
│   ├── packer.py          # Context injection
│   ├── redaction.py       # Secret scrubbing
│   ├── compaction.py      # Memory summarization
│   └── codebase_indexer.py  # Repo indexing
├── cli/                    # Command-line interface
├── gateway/                # OpenClaw integration
│   └── openclaw/          # Tool definitions + glue
├── renderer/               # PCN renderer
├── policies/               # Certification policies
│   └── memory_profiles/   # Memory profiles
├── schemas/                # JSON schemas
├── tests/                  # Test suite
├── docs/                   # Documentation
└── examples/               # Example fixtures
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design
- [Threat Model](docs/THREAT_MODEL.md) - Security considerations
- [Profiles](docs/PROFILES.md) - BRONZE/SILVER/GOLD + memory
- [Usage Guide](docs/USAGE.md) - Deployment instructions
- [Memory](docs/MEMORY.md) - How memory works

## Environment Variables

```bash
# Required
TRUTHCERT_SIGNING_KEY=<base64-ed25519-private-key>

# Optional
TRUTHCERT_PUBLIC_KEY=<base64-ed25519-public-key>
TRUTHCERT_HOST=0.0.0.0
TRUTHCERT_PORT=8000
TRUTHCERT_BUNDLE_DIR=./bundles
TRUTHCERT_MEMORY_DB=./memory.db
TRUTHCERT_LOG_DIR=./logs/spans
TRUTHCERT_MAX_CLAIMS=10000
TRUTHCERT_RATE_LIMIT_CERTIFY=10/minute
```

## The Memory-Evidence Boundary

**Memory is NEVER evidence.**

- ✅ Memory CAN: inform planning, track decisions, provide context
- ❌ Memory CANNOT: certify claims, provide content hashes, replace OA verification

The `memory_leak` validator blocks any claim that cites memory as evidence.

## Testing

```bash
# Run all tests
make test

# With coverage
make test-cov

# Specific test file
pytest tests/test_validators.py -v
```

## Contributing

Contributions welcome. Please read the [threat model](docs/THREAT_MODEL.md) before submitting PRs that touch validation logic.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Security

See [SECURITY.md](SECURITY.md) for security policy and reporting vulnerabilities.
