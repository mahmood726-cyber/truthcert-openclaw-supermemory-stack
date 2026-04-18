# Usage Guide

## Quick Start

### Single Box Setup

```bash
# Clone and setup
git clone https://github.com/your-org/truthcert-openclaw-supermemory-stack.git
cd truthcert-openclaw-supermemory-stack

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
make setup

# Generate keys
tc keygen --output keys

# Set environment
export TRUTHCERT_SIGNING_KEY=$(cat keys/private.key)
export TRUTHCERT_PUBLIC_KEY=$(cat keys/public.key)

# Run tests
make test

# Start service
make run
```

### Docker Setup

```bash
# Build and run
docker-compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker-compose logs -f truthcert
```

## CLI Usage

### Certification Commands

```bash
# Plan a certification job
tc plan examples/job_dir/ --policy policies/silver.json

# Run certification
tc certify examples/fixtures/sample_claims.jsonl --policy silver

# Verify a bundle
tc verify bundles/bundle_abc123/

# Audit a bundle
tc audit bundles/bundle_abc123/ --deep

# Generate keypair
tc keygen --output keys/

# Test domain packs
tc pack test
```

### Memory Commands

```bash
# Remember information
tc memory remember "Key insight about heterogeneity methods" --tags methods,het

# Recall memories
tc memory recall "heterogeneity" --limit 5
tc memory recall "methods" --pack  # Get packed context

# Forget memories
tc memory forget --id abc123
tc memory forget --query "old project"

# Index codebase
tc memory index-codebase --path . --max-files 400

# Compact old memories
tc memory compact --strategy rolling --max-age-days 30

# Wipe all memory
tc memory wipe --yes

# Show profile
tc memory profile
```

## API Usage

### Health Check

```bash
curl http://localhost:8000/health
```

### Submit Certification

```bash
curl -X POST http://localhost:8000/certify \
  -H "Content-Type: application/json" \
  -d '{
    "claims": [{
      "claim_id": "test-001",
      "claim_type": "effect_size",
      "value": 0.45,
      "evidence": [{
        "source_type": "oa_document",
        "uri": "https://example.com/paper.pdf",
        "content_hash": "sha256:abc123..."
      }]
    }],
    "policy_id": "silver"
  }'
```

### Verify Bundle

```bash
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{
    "bundle_id": "sha256:...",
    "check_signature": true,
    "check_scope_lock": true
  }'
```

### List Bundles

```bash
curl "http://localhost:8000/bundles?limit=10&offset=0"
```

## Python Integration

```python
from certifier.models import NumericClaim, EvidenceLocator, EvidenceType, ClaimType
from gateway.openclaw.glue import TruthCertGlue

# Create claim
claim = NumericClaim(
    claim_id="study-001",
    claim_type=ClaimType.EFFECT_SIZE,
    value=0.45,
    unit="d",
    evidence=[
        EvidenceLocator(
            source_type=EvidenceType.OA_DOCUMENT,
            uri="https://example.com/paper.pdf",
            content_hash="sha256:...",
        )
    ],
)

# Certify
with TruthCertGlue() as glue:
    result = glue.certify_claims(
        claims=[claim.model_dump()],
        policy_id="silver",
    )

    if result.outcome == "PASS":
        print(f"Certified! Bundle: {result.bundle_id}")
    else:
        print(f"Rejected: {result.errors}")
```

## Cluster Setup

### Multi-Node Configuration

```yaml
# docker-compose.cluster.yml
version: '3.8'

services:
  truthcert-1:
    build: .
    environment:
      - TRUTHCERT_SIGNING_KEY=${TRUTHCERT_SIGNING_KEY}
      - TRUTHCERT_PORT=8001
    ports:
      - "8001:8001"
    volumes:
      - bundles:/app/bundles

  truthcert-2:
    build: .
    environment:
      - TRUTHCERT_SIGNING_KEY=${TRUTHCERT_SIGNING_KEY}
      - TRUTHCERT_PORT=8002
    ports:
      - "8002:8002"
    volumes:
      - bundles:/app/bundles

  nginx:
    image: nginx:alpine
    ports:
      - "8000:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - truthcert-1
      - truthcert-2

volumes:
  bundles:
```

### Shared Storage

For cluster deployments, bundles should be on shared storage:

```bash
# NFS mount example
mount -t nfs server:/bundles /app/bundles
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRUTHCERT_SIGNING_KEY` | (required) | Base64 Ed25519 private key |
| `TRUTHCERT_PUBLIC_KEY` | (derived) | Base64 Ed25519 public key |
| `TRUTHCERT_HOST` | 0.0.0.0 | Server bind address |
| `TRUTHCERT_PORT` | 8000 | Server port |
| `TRUTHCERT_BUNDLE_DIR` | ./bundles | Bundle storage directory |
| `TRUTHCERT_LOG_DIR` | ./logs/spans | Span log directory |
| `TRUTHCERT_MAX_CLAIMS` | 10000 | Max claims per request |
| `TRUTHCERT_MAX_REQUEST_MB` | 50 | Max request size |
| `TRUTHCERT_RATE_LIMIT_CERTIFY` | 10/minute | Certification rate limit |
| `TRUTHCERT_MEMORY_DB` | ./memory.db | Memory database path |

## Troubleshooting

### Common Issues

**"Signing key not configured"**
```bash
export TRUTHCERT_SIGNING_KEY=$(cat keys/private.key)
```

**"Memory leak detected"**
Your claim cites memory as evidence. Use OA documents or fixtures instead.

**"Rate limit exceeded"**
Wait for rate limit window or increase limits in configuration.

**"Bundle not found"**
Check bundle ID format and ensure bundle directory is accessible.
