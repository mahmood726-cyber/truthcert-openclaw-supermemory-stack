"""
Evidence Allowlist Validator

Validates that evidence URIs use approved schemes and domains.
Uses an ALLOWLIST approach (not blocklist) for security.

Approved schemes:
- doi: Digital Object Identifier
- pmid: PubMed ID
- pmcid: PubMed Central ID
- arxiv: arXiv preprint ID
- https: Secure web URLs (with domain restrictions)
- fixture: Test fixtures (BRONZE profile only)

SECURITY: file:// scheme is NEVER allowed - all evidence must be
remotely verifiable by independent parties.

This prevents:
- Memory references slipping through via URIs
- Unknown/untrusted evidence sources
- Insecure HTTP links
- Local file references
- Arbitrary protocol handlers
"""

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorConfig, ValidatorResult
from .base import Validator, ValidatorRegistry


@dataclass
class EvidenceScheme:
    """Configuration for an allowed evidence scheme."""

    name: str
    pattern: re.Pattern[str]
    requires_hash: bool = True
    allowed_profiles: list[CertificationProfile] = field(
        default_factory=lambda: [
            CertificationProfile.BRONZE,
            CertificationProfile.SILVER,
            CertificationProfile.GOLD,
        ]
    )
    description: str = ""


# Allowed URI schemes with validation patterns
# SECURITY: file:// is NEVER allowed in any profile - all evidence must be remotely verifiable
ALLOWED_SCHEMES = [
    EvidenceScheme(
        name="doi",
        pattern=re.compile(r"^doi:10\.\d{4,}/[^\s]+$", re.IGNORECASE),
        requires_hash=True,
        description="Digital Object Identifier",
    ),
    EvidenceScheme(
        name="pmid",
        pattern=re.compile(r"^pmid:\d+$", re.IGNORECASE),
        requires_hash=True,
        description="PubMed ID",
    ),
    EvidenceScheme(
        name="pmcid",
        pattern=re.compile(r"^pmcid:PMC\d+$", re.IGNORECASE),
        requires_hash=True,
        description="PubMed Central ID",
    ),
    EvidenceScheme(
        name="arxiv",
        pattern=re.compile(r"^arxiv:\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE),
        requires_hash=True,
        description="arXiv preprint ID",
    ),
    EvidenceScheme(
        name="https",
        pattern=re.compile(r"^https://[^\s]+$", re.IGNORECASE),
        requires_hash=True,
        description="Secure web URL",
    ),
    # NOTE: file:// scheme REMOVED for security - local files cannot be independently verified
    # All certified claims must reference externally accessible evidence
    EvidenceScheme(
        name="fixture",
        pattern=re.compile(r"^fixture:[a-zA-Z0-9_\-]+$", re.IGNORECASE),
        requires_hash=True,
        allowed_profiles=[CertificationProfile.BRONZE],  # Only for testing
        description="Test fixture reference (testing only)",
    ),
]

# Trusted domains for HTTPS URLs
TRUSTED_DOMAINS = {
    # Academic publishers
    "doi.org",
    "dx.doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "nature.com",
    "sciencedirect.com",
    "wiley.com",
    "springer.com",
    "elsevier.com",
    "tandfonline.com",
    "jamanetwork.com",
    "bmj.com",
    "thelancet.com",
    "nejm.org",
    "cochranelibrary.com",
    # Repositories
    "zenodo.org",
    "osf.io",
    "figshare.com",
    "github.com",
    "raw.githubusercontent.com",
    # Government/institutional
    "nih.gov",
    "cdc.gov",
    "who.int",
    "ema.europa.eu",
    "fda.gov",
    "clinicaltrials.gov",
    # Data repositories
    "datadryad.org",
    "dataverse.org",
    "pangaea.de",
}

# Blocked URI patterns (memory references that might slip through)
BLOCKED_PATTERNS = [
    re.compile(r"memory:", re.IGNORECASE),
    re.compile(r"mem:", re.IGNORECASE),
    re.compile(r"recall:", re.IGNORECASE),
    re.compile(r"supermemory:", re.IGNORECASE),
    re.compile(r"remembered:", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"data:", re.IGNORECASE),  # Data URIs can embed content
    re.compile(r"blob:", re.IGNORECASE),
    re.compile(r"about:", re.IGNORECASE),
]


@ValidatorRegistry.register
class EvidenceAllowlistValidator(Validator):
    """
    Validates evidence URIs against an allowlist of approved schemes.

    This is a CRITICAL security validator that:
    1. Blocks unknown URI schemes
    2. Validates URI format for known schemes
    3. Restricts HTTPS to trusted domains
    4. Blocks memory reference patterns
    5. Enforces profile-specific restrictions
    """

    name = "evidence_allowlist"
    description = "Validates evidence URIs against approved schemes"
    default_severity = Severity.BLOCK

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        super().__init__(config)
        self.schemes = {s.name: s for s in ALLOWED_SCHEMES}
        self.trusted_domains = set(TRUSTED_DOMAINS)
        self.blocked_patterns = list(BLOCKED_PATTERNS)
        self.strict_domains = False

        # Get custom params from config
        params = config.params if config else {}
        if params:
            # Allow adding custom trusted domains
            if "additional_domains" in params:
                self.trusted_domains.update(params["additional_domains"])

            # Allow stricter domain checking
            self.strict_domains = params.get("strict_domains", False)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate all evidence URIs."""
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        validated_count = 0
        profile = scope_lock.profile

        for claim in claims:
            for i, evidence in enumerate(claim.evidence):
                validated_count += 1
                uri = evidence.uri

                # Check for blocked patterns first (security critical)
                blocked = self._check_blocked_patterns(uri)
                if blocked:
                    errors.append(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_index": i,
                            "uri": uri[:100],  # Truncate for safety
                            "issue": f"Blocked URI pattern detected: {blocked}",
                            "rule": "MEMORY IS NEVER EVIDENCE",
                        }
                    )
                    continue

                # Validate against allowlist
                scheme_errors, scheme_warnings = self._validate_uri(uri, profile, claim.claim_id, i)
                errors.extend(scheme_errors)
                warnings.extend(scheme_warnings)

                # Validate content hash presence
                if evidence.content_hash is None or not evidence.content_hash.strip():
                    errors.append(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_index": i,
                            "uri": uri[:100],
                            "issue": "Missing content hash for evidence",
                        }
                    )

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK
            if not passed
            else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} evidence URIs"
                if passed
                else f"Evidence validation failed: {len(errors)} invalid URIs"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
                "allowed_schemes": list(self.schemes.keys()),
            },
        )

    def _check_blocked_patterns(self, uri: str) -> str | None:
        """Check if URI matches any blocked pattern."""
        for pattern in self.blocked_patterns:
            if pattern.search(uri):
                return pattern.pattern
        return None

    def _validate_uri(
        self,
        uri: str,
        profile: CertificationProfile,
        claim_id: str,
        evidence_index: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Validate a single URI against the allowlist."""
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        # Extract scheme
        if ":" not in uri:
            errors.append(
                {
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "issue": "Invalid URI: no scheme found",
                    "allowed_schemes": list(self.schemes.keys()),
                }
            )
            return errors, warnings

        scheme = uri.split(":")[0].lower()

        # Check if scheme is allowed
        if scheme not in self.schemes:
            errors.append(
                {
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "issue": f"Unknown URI scheme: {scheme}",
                    "allowed_schemes": list(self.schemes.keys()),
                }
            )
            return errors, warnings

        scheme_config = self.schemes[scheme]

        # Check profile restriction
        if profile not in scheme_config.allowed_profiles:
            errors.append(
                {
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "issue": f"Scheme '{scheme}' not allowed in {profile.value} profile",
                    "allowed_profiles": [p.value for p in scheme_config.allowed_profiles],
                }
            )
            return errors, warnings

        # Validate pattern
        if not scheme_config.pattern.match(uri):
            errors.append(
                {
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "issue": f"Invalid {scheme} URI format",
                    "expected_pattern": scheme_config.pattern.pattern,
                }
            )
            return errors, warnings

        # Additional validation for HTTPS
        if scheme == "https":
            domain_errors, domain_warnings = self._validate_https_domain(
                uri, claim_id, evidence_index
            )
            errors.extend(domain_errors)
            warnings.extend(domain_warnings)

        return errors, warnings

    def _validate_https_domain(
        self,
        uri: str,
        claim_id: str,
        evidence_index: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Validate HTTPS URL domain."""
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        try:
            parsed = urlparse(uri)
            domain = parsed.netloc.lower()

            # Remove port if present
            if ":" in domain:
                domain = domain.split(":")[0]

            # Remove www. prefix for comparison
            check_domain = domain
            check_domain = check_domain.removeprefix("www.")

            # Check against trusted domains with strict subdomain validation
            # SECURITY: Only allow exact matches or PROPER subdomains
            # e.g., "api.doi.org" is valid, but "evil-doi.org" or "evildoi.org" are NOT
            is_trusted = False
            for trusted in self.trusted_domains:
                if check_domain == trusted:
                    # Exact match
                    is_trusted = True
                    break
                elif check_domain.endswith("." + trusted):
                    # Valid subdomain - must have a dot before the trusted domain
                    # This prevents "evildoi.org" from matching "doi.org"
                    is_trusted = True
                    break

            # Additional check: prevent lookalike domains
            # e.g., "d0i.org" (with zero instead of 'o')
            if not is_trusted:
                suspicious_patterns = [
                    # Common lookalike substitutions
                    (r"d[0o]i\.org", "doi.org"),
                    (r"pub[mn]ed", "pubmed"),
                    (r"arx[1i]v", "arxiv"),
                    (r"n[1i]h\.gov", "nih.gov"),
                    (r"nc[8b][1i]", "ncbi"),
                ]
                for pattern, real_domain in suspicious_patterns:
                    if re.search(pattern, check_domain, re.IGNORECASE):
                        errors.append(
                            {
                                "claim_id": claim_id,
                                "evidence_index": evidence_index,
                                "uri": uri[:100],
                                "domain": domain,
                                "issue": f"Suspicious lookalike domain detected (similar to {real_domain})",
                                "security": "POTENTIAL_TYPOSQUATTING",
                            }
                        )
                        return errors, warnings

            if not is_trusted:
                if self.strict_domains:
                    errors.append(
                        {
                            "claim_id": claim_id,
                            "evidence_index": evidence_index,
                            "uri": uri[:100],
                            "domain": domain,
                            "issue": "Domain not in trusted list",
                            "trusted_domains": list(self.trusted_domains)[:10],  # Sample
                        }
                    )
                else:
                    warnings.append(
                        {
                            "claim_id": claim_id,
                            "evidence_index": evidence_index,
                            "domain": domain,
                            "issue": "Domain not in trusted list (strict mode off)",
                        }
                    )

        except ValueError as e:
            errors.append(
                {
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "issue": f"Failed to parse URL: {str(e)[:50]}",
                }
            )

        return errors, warnings


def is_valid_doi(doi: str) -> bool:
    """Check if a string is a valid DOI."""
    pattern = re.compile(r"^10\.\d{4,}/[^\s]+$")
    return bool(pattern.match(doi.replace("doi:", "")))


def is_valid_pmid(pmid: str) -> bool:
    """Check if a string is a valid PubMed ID."""
    pmid_num = pmid.replace("pmid:", "").strip()
    return pmid_num.isdigit()


def normalize_evidence_uri(uri: str) -> str:
    """
    Normalize an evidence URI to canonical form.

    Examples:
        - "DOI:10.1234/abc" -> "doi:10.1234/abc"
        - "https://doi.org/10.1234/abc" -> "doi:10.1234/abc"
        - "PMID: 12345" -> "pmid:12345"
    """
    uri = uri.strip()

    # Handle DOI via HTTPS
    doi_https_pattern = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,}/[^\s]+)", re.IGNORECASE)
    match = doi_https_pattern.match(uri)
    if match:
        return f"doi:{match.group(1)}"

    # Handle PubMed via HTTPS
    pmid_https_pattern = re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE)
    match = pmid_https_pattern.match(uri)
    if match:
        return f"pmid:{match.group(1)}"

    # Normalize scheme case
    if ":" in uri:
        scheme, rest = uri.split(":", 1)
        return f"{scheme.lower()}:{rest.strip()}"

    return uri
