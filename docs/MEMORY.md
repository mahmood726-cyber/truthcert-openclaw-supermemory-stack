# Memory Subsystem

## Overview

The Supermemory subsystem provides local-first persistent memory for planning and context across sessions.

**CRITICAL RULE**: Memory is NEVER evidence. Memory content cannot be used to certify numeric claims.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Supermemory Subsystem                        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Capture    │  │   Recall     │  │   Packer     │          │
│  │  (auto-save) │  │  (search)    │  │  (inject)    │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         └────────────┬────┴─────────────────┘                   │
│                      ▼                                          │
│         ┌────────────────────────┐                              │
│         │   SQLite + FTS5        │                              │
│         │   (local-first)        │                              │
│         └────────────────────────┘                              │
│                      │                                          │
│         ┌────────────┴────────────┐                             │
│         ▼                         ▼                             │
│  ┌──────────────┐        ┌──────────────┐                      │
│  │  Redaction   │        │  Compaction  │                      │
│  │  (secrets)   │        │  (summaries) │                      │
│  └──────────────┘        └──────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

## Memory Types

| Type | Description | Use Case |
|------|-------------|----------|
| `note` | General notes | Planning, context |
| `decision` | Decisions made | Tracking choices |
| `runbook` | Procedures | Repeatable workflows |
| `codebase_index` | Repository structure | Code navigation |
| `trace` | Tool execution logs | Debugging |
| `summary` | Compacted memories | Long-term storage |

## CLI Commands

```bash
# Remember something
tc memory remember "Effect size extraction uses Hedges' g" --tags methods,effect-size --type decision

# Recall memories
tc memory recall "effect size methods" --pack
tc memory recall "heterogeneity" --limit 5

# Forget memories
tc memory forget --id <memory-id>
tc memory forget --query "old project"

# Wipe all memory
tc memory wipe --yes

# Index codebase
tc memory index-codebase --path . --max-files 400

# Compact old memories
tc memory compact --strategy rolling --max-age-days 30

# Show profile and stats
tc memory profile
```

## Memory Profiles

### OFF (`off.yaml`)
- No auto-recall or auto-capture
- Minimal footprint

### LITE (`lite.yaml`)
- Basic auto-recall (5 results)
- Selective capture (certification tools only)
- 2000 char injection limit

### FULL (`full.yaml`)
- Full auto-recall (10 results)
- Comprehensive capture
- 4000 char injection limit

## Privacy & Redaction

Sensitive content is automatically redacted before storage:

- API keys and tokens
- Passwords
- Bearer tokens
- AWS credentials
- Credit card numbers
- Private keys
- Connection strings

### Sensitive Tool Denylist

These tools never have their output captured:

- `read_file` (arbitrary file access)
- `read_email`
- `get_credentials`
- `ssh_exec`
- `exec_shell`

## The Memory-Evidence Boundary

### What Memory CAN Be Used For

✅ Planning certification strategy
✅ Remembering past decisions
✅ Context about codebase structure
✅ Notes about methodology
✅ Tracking certification history

### What Memory CANNOT Be Used For

❌ Evidence for numeric claims
❌ Source citations
❌ Content hashes
❌ Replacing OA document verification

### How the Boundary is Enforced

1. **MEMORY_LEAK Validator**: Blocks claims citing `memory:` URIs
2. **Source Type Validation**: Evidence must be `oa_document`, `fixture`, or `computed`
3. **Context Packer Warning**: Injected memory includes explicit warning
4. **Capture Metadata**: Memory items are tagged with source

### Packed Memory Context

When memory is injected into prompts, it includes:

```
╔══════════════════════════════════════════════════════════════╗
║ MEMORY CONTEXT (untrusted; planning-only; NOT evidence)       ║
║ This content is from memory and CANNOT be used as evidence.  ║
╚══════════════════════════════════════════════════════════════╝

[Memory content here]

Provenance: db_hash=sha256:abc123, rule='FTS5 match, limit=10'

╔══════════════════════════════════════════════════════════════╗
║ END MEMORY CONTEXT - Remember: Memory is NEVER evidence       ║
╚══════════════════════════════════════════════════════════════╝
```

## Compaction Strategy

Old memories are compacted into summaries:

1. **Rolling**: Summarize items older than N days
2. **Threshold**: Summarize when count exceeds limit

Summaries preserve key information while reducing storage.

## Database Schema

```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    tags TEXT NOT NULL,  -- JSON array
    text TEXT NOT NULL,
    metadata TEXT NOT NULL,  -- JSON object
    sensitivity TEXT NOT NULL,
    retention TEXT NOT NULL,  -- JSON object
    content_hash TEXT NOT NULL,
    deleted INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
    id, text, tags,
    content='memory_items'
);
```

## API Integration

```python
from memory.commands import MemoryCommands

cmd = MemoryCommands()

# Remember
result = cmd.remember("Important note", tags=["project"], memory_type="note")

# Recall
result = cmd.recall_memories("search query", pack=True)

# Index codebase
result = cmd.index_codebase(path=".", max_files=400)
```

### Project-scoped memory state fingerprints

The `db_hash` supplied in recall and context provenance is a **noncertifying**
SHA-256 fingerprint of the active records in that backend's selected project.
The v2 calculation covers persisted source/provenance metadata, sensitivity,
retention, timestamps, content and identity; modifying these fields invalidates
the fingerprint even when memory text and its historical content hash are
unchanged. Prior v1 short fingerprints are not interchangeable with v2 full
digests. Other projects' record changes must not alter the selected project's
fingerprint. This does **not** authenticate the underlying source, prove that
the memory is current, or establish a signed evidence certificate. Recheck the
source itself before making any authoritative scientific claim.

Packed recall now carries the **same** unsigned `db_hash` that was captured
with its search results, even if the database changes before context rendering.
The packer must not recompute a later live hash and misattribute it to stale
items. Nonempty recalls lacking a well-formed snapshot fingerprint are refused.
Directly packing an arbitrary item list is labelled `NOT_SNAPSHOT_BOUND` and
has an empty `db_hash`; no source-state binding or scientific validation is
claimed. Neither format authenticates a source or a model call.
