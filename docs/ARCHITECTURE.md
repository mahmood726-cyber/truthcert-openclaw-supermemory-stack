# Architecture

## System Overview

The TruthCert + OpenClaw + Supermemory stack provides a complete solution for trustworthy numeric claims in research synthesis.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User / Orchestrator                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OpenClaw Runtime (Placeholder)                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │ Reader Agent  │  │ Worker Agent  │  │  Tool Sandbox │                   │
│  │  (no tools)   │  │  (allowlist)  │  │   (isolated)  │                   │
│  └───────┬───────┘  └───────┬───────┘  └───────────────┘                   │
│          │                  │                                               │
│          └──────────┬───────┘                                               │
│                     ▼                                                       │
│            ┌───────────────┐                                                │
│            │    Gateway    │◄─────────── Memory Recall (planning only)      │
│            │   (Glue.py)   │                                                │
│            └───────┬───────┘                                                │
└────────────────────┼────────────────────────────────────────────────────────┘
                     │ HTTP
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TruthCert Certifier (truthcertd)                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Validation Pipeline                             │   │
│  │  [Schema] → [ScopeLock] → [NoNakedNumbers] → [MemoryLeak] → [...]   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│           ┌──────────────────┼──────────────────┐                          │
│           ▼                  ▼                  ▼                          │
│      ┌─────────┐       ┌───────────┐      ┌──────────┐                    │
│      │  PASS   │       │  REJECT   │      │  WARN    │                    │
│      │ Bundle  │       │  Bundle   │      │ (logged) │                    │
│      └─────────┘       └───────────┘      └──────────┘                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Ed25519 Signing + Receipts                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Supermemory Subsystem                                │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │   SQLite +    │  │   Redaction   │  │   Codebase    │                   │
│  │    FTS5       │  │    Engine     │  │    Indexer    │                   │
│  └───────────────┘  └───────────────┘  └───────────────┘                   │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │    Recall     │  │    Capture    │  │   Compaction  │                   │
│  └───────────────┘  └───────────────┘  └───────────────┘                   │
│                                                                              │
│  ══════════════════════════════════════════════════════════════════════    │
│  │ CRITICAL: Memory is NEVER evidence. Cannot be used for certification │   │
│  ══════════════════════════════════════════════════════════════════════    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Separation

### TruthCert Certifier

The certifier is the **trust anchor**. It:

1. **Validates** claims against a policy
2. **Blocks** claims that cite memory as evidence
3. **Signs** passing bundles with Ed25519
4. **Produces** content-addressed bundles

Key principle: **Fail-closed**. If any blocking validator fails, the entire certification fails.

### OpenClaw Runtime (Placeholder)

The runtime orchestrates agents and tools. Key features:

- **Reader Agent**: Can read but not execute tools
- **Worker Agent**: Limited tool allowlist
- **Tool Sandbox**: Isolated execution environment

### Supermemory Subsystem

Local-first memory for planning and context:

- **SQLite + FTS5**: Full-text search
- **Redaction**: Scrubs secrets before storage
- **Codebase Indexer**: Indexes repository structure
- **Compaction**: Summarizes old items

**Critical Rule**: Memory content is planning-only. It can never be cited as evidence.

## Data Flow

### Certification Flow

```
Claims (with evidence) → Validation Pipeline → PASS/REJECT → Signed Bundle
```

### Memory Flow

```
Chat/Tool Output → Redaction → SQLite Storage
Query → FTS5 Search → Ranked Results → Context Packer → Prompt Injection
```

### Memory-Evidence Boundary

```
Memory ──╳──► Evidence Locator
         │
         └── MEMORY_LEAK validator blocks this
```

## Bundle Format

```
bundle/
├── manifest.json        # Bundle metadata + validation summary
├── scope_lock.json      # Certification constraints
├── claims.jsonl         # Certified claims
├── provenance.jsonl     # PROV-like provenance records
├── audit.log.jsonl      # Audit trail
├── telemetry.jsonl      # Performance metrics
├── outputs/             # Generated artifacts
├── capsule/             # Reproducibility capsule
│   └── deps.lock        # Pinned dependencies
└── attest/
    ├── signature.ed25519
    ├── public_key.txt
    └── receipt.json
```

## Security Model

1. **Deny by default**: Tools require explicit allowlisting
2. **Sandbox isolation**: Tools run in restricted environments
3. **Memory boundary**: Memory cannot contaminate evidence
4. **Fail-closed**: Blocking validators stop certification
5. **Signed bundles**: Ed25519 attestation

## Profiles

| Component | BRONZE | SILVER | GOLD |
|-----------|--------|--------|------|
| TruthCert | Basic validation | Determinism + 2-witness | Full + 3-witness |
| Memory | Lite | Full | Full |
| Evidence | Pointers | Cached | Full archive |
