# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Security Model Overview

### Sandbox vs Tool Policy vs Elevated

```
┌─────────────────────────────────────────────────────────────────┐
│                        Permission Levels                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  SANDBOX (Default)                                               │
│  - No network access                                             │
│  - No file system writes outside /app                           │
│  - No environment variable access                                │
│  - Read-only source mounts                                       │
│                                                                  │
│  TOOL POLICY (Allowlist)                                         │
│  - Specific tools allowed per agent                              │
│  - Rate limited                                                  │
│  - Input validation enforced                                     │
│  - Output sanitized                                              │
│                                                                  │
│  ELEVATED (Never automatic)                                      │
│  - Requires explicit user consent                                │
│  - Audit logged                                                  │
│  - Time-limited sessions                                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Pairing-First Trust Bootstrap

For initial deployment:

1. **Generate Keys Offline**
   ```bash
   # On air-gapped machine
   tc keygen --output keys/
   ```

2. **Verify Key Integrity**
   ```bash
   # Compare public key hash
   sha256sum keys/public.key
   ```

3. **Distribute Public Key**
   - Include in bundle verification
   - Publish hash in documentation

4. **Secure Private Key**
   - Never commit to version control
   - Use secrets management (Vault, AWS Secrets Manager)
   - Rotate periodically

### Signed Releases Guidance

#### Verifying Releases

```bash
# Download release and signature
curl -LO https://github.com/your-org/truthcert/releases/download/v1.0.0/truthcert-1.0.0.tar.gz
curl -LO https://github.com/your-org/truthcert/releases/download/v1.0.0/truthcert-1.0.0.tar.gz.sig

# Import release signing key
gpg --keyserver keyserver.ubuntu.com --recv-keys <KEY_ID>

# Verify signature
gpg --verify truthcert-1.0.0.tar.gz.sig truthcert-1.0.0.tar.gz
```

#### Creating Signed Releases

```bash
# Sign the release
gpg --armor --detach-sign truthcert-1.0.0.tar.gz

# Verify locally
gpg --verify truthcert-1.0.0.tar.gz.sig
```

### Safe Mounts

When running in containers:

```yaml
# docker-compose.yml
services:
  truthcert:
    volumes:
      # Read-only source mount
      - ./policies:/app/policies:ro
      - ./schemas:/app/schemas:ro

      # Writable data directories (isolated)
      - bundles:/app/bundles
      - logs:/app/logs
```

**Never mount**:
- Host `/` or `/etc`
- User home directories
- SSH keys or credentials
- Host Docker socket

### No Secrets in Bundles

Bundles are designed for sharing and archival. They must never contain:

- API keys or tokens
- Passwords
- Private keys
- Database credentials
- Personal identifiers (unless anonymized)
- Session tokens

**Validation**: The MEMORY_LEAK validator helps catch accidental inclusion of sensitive content.

## Reporting a Vulnerability

If you discover a security vulnerability:

1. **Do NOT** create a public GitHub issue
2. Email security@your-org.com with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
   - Any suggested fixes

3. You will receive acknowledgment within 48 hours
4. We will work with you to understand and resolve the issue
5. Public disclosure will be coordinated after a fix is available

## Security Best Practices

### Deployment

- [ ] Run as non-root user
- [ ] Use read-only file systems where possible
- [ ] Enable rate limiting
- [ ] Configure firewall rules
- [ ] Use TLS for all connections
- [ ] Rotate keys periodically

### Operations

- [ ] Monitor audit logs
- [ ] Set up alerting for failed certifications
- [ ] Regular security scans
- [ ] Keep dependencies updated
- [ ] Backup bundle storage

### Development

- [ ] Never commit secrets
- [ ] Use `.env` files (gitignored)
- [ ] Run security linters
- [ ] Review dependencies for vulnerabilities
- [ ] Test with malicious inputs

## Audit Trail

All certification operations are logged:

```jsonl
{"timestamp": "2024-01-15T10:30:00Z", "event": "certify_request", "claims": 5, "policy": "silver"}
{"timestamp": "2024-01-15T10:30:01Z", "event": "validator_run", "name": "memory_leak", "passed": true}
{"timestamp": "2024-01-15T10:30:02Z", "event": "bundle_created", "id": "sha256:...", "outcome": "PASS"}
```

Logs are stored in:
- `logs/spans/spans-YYYYMMDD.jsonl` - Trace spans
- Bundle `audit.log.jsonl` - Bundle-specific audit trail

## Incident Response

If a security incident occurs:

1. **Contain**: Stop affected services
2. **Assess**: Review logs and identify scope
3. **Remediate**: Apply fixes
4. **Communicate**: Notify affected users
5. **Learn**: Update procedures
