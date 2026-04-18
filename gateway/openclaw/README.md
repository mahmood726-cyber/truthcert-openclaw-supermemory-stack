# OpenClaw Integration

This directory contains integration points for connecting OpenClaw runtime with TruthCert certifier.

## Overview

OpenClaw is the runtime/control plane that orchestrates model agents and tool execution. TruthCert is the certification gate that validates and signs numeric claims.

**Key Principle**: OpenClaw agents can discover and process data, but ONLY TruthCert can publish certified numbers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        OpenClaw Runtime                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Reader Agent│  │Worker Agent │  │ Tool Sandbox│              │
│  │ (no tools)  │  │ (allowlist) │  │ (isolated)  │              │
│  └──────┬──────┘  └──────┬──────┘  └─────────────┘              │
│         │                │                                       │
│         └────────┬───────┘                                       │
│                  ▼                                               │
│         ┌───────────────┐                                        │
│         │ Candidate     │                                        │
│         │ Claims Queue  │                                        │
│         └───────┬───────┘                                        │
└─────────────────┼───────────────────────────────────────────────┘
                  │ HTTP (POST /certify)
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     TruthCert Certifier                          │
│                 (Fail-closed validation gate)                    │
└─────────────────────────────────────────────────────────────────┘
```

## Tool Definitions

The `tools/` directory contains JSON schema definitions for tools that OpenClaw can expose to agents:

- `truthcert_run_job.json` - Submit certification jobs
- `truthcert_memory_recall.json` - Recall from memory (planning only)
- `truthcert_memory_remember.json` - Store to memory

## Usage

### Glue Script

The `glue.py` script demonstrates how to:

1. Initialize connection to TruthCert service
2. Submit claims for certification
3. Handle PASS/REJECT responses
4. Store certification results to memory

```python
from gateway.openclaw.glue import TruthCertGlue

glue = TruthCertGlue(base_url="http://localhost:8000")

# Certify claims
result = glue.certify_claims(claims, policy_id="silver")
if result.outcome == "PASS":
    print(f"Certified: {result.bundle_id}")
else:
    print(f"Rejected: {result.errors}")
```

### Cron Job Example

See `cron_daily_methods.sh` for an example of automated daily certification runs.

## Security Model

1. **Agent Separation**: Reader agents cannot execute tools. Worker agents have an allowlist.
2. **Tool Sandbox**: Tools run in isolated environments with limited permissions.
3. **Memory Boundary**: Memory content is NEVER evidence. Claims citing memory are blocked.
4. **Fail-Closed**: If any blocking validator fails, certification is rejected.

## Configuration

Environment variables:

```bash
TRUTHCERT_URL=http://localhost:8000  # TruthCert service URL
TRUTHCERT_TIMEOUT=30                  # Request timeout in seconds
```
