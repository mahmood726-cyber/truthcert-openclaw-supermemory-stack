# Certification & Memory Profiles

## Certification Profiles

### BRONZE - Rapid Prototyping

**Use Case**: Quick iterations, exploratory analysis, development.

| Validator | Status | Severity |
|-----------|--------|----------|
| schema | ✓ Enabled | BLOCK |
| no_naked_numbers | ✓ Enabled | BLOCK |
| memory_leak | ✓ Enabled | BLOCK |
| scope_lock | ✗ Disabled | - |
| determinism | ✗ Disabled | - |
| multi_witness | ✗ Disabled | - |
| unit_drift | ✓ Enabled | INFO |
| memory_drift | ✓ Enabled | INFO |

**Requirements**:
- Basic schema compliance
- Evidence pointers (no caching required)
- Single witness sufficient

### SILVER - Publication Ready

**Use Case**: Research papers, preprints, team collaboration.

| Validator | Status | Severity |
|-----------|--------|----------|
| schema | ✓ Enabled | BLOCK |
| scope_lock | ✓ Enabled | BLOCK |
| no_naked_numbers | ✓ Enabled | BLOCK |
| memory_leak | ✓ Enabled | BLOCK |
| determinism | ✓ Enabled | BLOCK |
| multi_witness | ✓ Enabled | BLOCK |
| unit_drift | ✓ Enabled | WARN |
| memory_drift | ✓ Enabled | WARN |

**Requirements**:
- 2-witness rule for critical fields
- Deterministic computation
- Evidence caching with content hashes
- Scope lock verification

### GOLD - Regulatory Submission

**Use Case**: FDA submissions, clinical guidelines, regulatory filings.

| Validator | Status | Severity |
|-----------|--------|----------|
| schema | ✓ Enabled | BLOCK |
| scope_lock | ✓ Enabled | BLOCK |
| no_naked_numbers | ✓ Enabled | BLOCK |
| memory_leak | ✓ Enabled | BLOCK |
| determinism | ✓ Enabled | BLOCK |
| multi_witness | ✓ Enabled | BLOCK |
| unit_drift | ✓ Enabled | BLOCK |
| memory_drift | ✓ Enabled | BLOCK |

**Requirements**:
- 3-witness rule
- Full evidence archival
- Strict unit consistency
- No tolerance for drift
- Complete reproducibility

## Memory Profiles

### OFF - No Memory

```yaml
autoRecall: false
autoCapture: false
maxRecallResults: 0
maxInjectChars: 0
```

**Use Case**: Maximum privacy, stateless operation.

### LITE - Basic Memory

```yaml
autoRecall: true
autoCapture: true
maxRecallResults: 5
maxInjectChars: 2000
captureMode: selected
captureTools: [tc_certify, tc_verify]
```

**Use Case**: Short sessions, limited context needs.

### FULL - Supermemory

```yaml
autoRecall: true
autoCapture: true
maxRecallResults: 10
maxInjectChars: 4000
captureMode: all
profileFrequency: 5
```

**Use Case**: Long-running sessions, complex projects.

## Profile Combinations

| Certification | Memory | Recommended For |
|---------------|--------|-----------------|
| BRONZE | OFF | Quick tests |
| BRONZE | LITE | Development |
| SILVER | LITE | Team projects |
| SILVER | FULL | Research synthesis |
| GOLD | FULL | Regulatory work |

## Selecting a Profile

### CLI

```bash
# Certification
tc certify claims.jsonl --policy silver

# Memory profile (set in environment)
export TRUTHCERT_MEMORY_PROFILE=full
```

### API

```python
# Certification request
{"claims": [...], "policy_id": "silver"}
```

### Configuration

Create custom profiles by copying and modifying:

```bash
cp policies/silver.json policies/custom.json
cp policies/memory_profiles/full.yaml policies/memory_profiles/custom.yaml
```
