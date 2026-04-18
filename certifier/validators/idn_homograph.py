"""
IDN Homograph Attack Detection Validator.

Detects Internationalized Domain Name (IDN) homograph attacks where
Unicode characters that look similar to ASCII are used in URIs to
create lookalike domains.

Examples:
- "аpple.com" (Cyrillic 'а') vs "apple.com" (Latin 'a')
- "g00gle.com" (zeros) vs "google.com" (letter 'o')
- "microsоft.com" (Cyrillic 'о') vs "microsoft.com" (Latin 'o')

SECURITY: This is a critical security validator that should run
before evidence is fetched to prevent SSRF and data exfiltration.
"""

import re
import unicodedata
from typing import Any, Optional
from urllib.parse import urlparse

from ..constants import Severity, CertificationProfile
from ..models import NumericClaim, ScopeLock, ValidatorResult, ValidatorConfig
from .base import Validator, ValidatorRegistry


# Homoglyph mappings: Unicode characters that look like ASCII
# Format: {lookalike_char: ascii_equivalent}
HOMOGLYPHS = {
    # Cyrillic lookalikes
    '\u0430': 'a',  # Cyrillic small a
    '\u0435': 'e',  # Cyrillic small ie
    '\u0456': 'i',  # Cyrillic small i
    '\u043e': 'o',  # Cyrillic small o
    '\u0440': 'p',  # Cyrillic small er
    '\u0441': 'c',  # Cyrillic small es
    '\u0443': 'y',  # Cyrillic small u
    '\u0445': 'x',  # Cyrillic small ha
    '\u0410': 'A',  # Cyrillic capital A
    '\u0412': 'B',  # Cyrillic capital Ve
    '\u0415': 'E',  # Cyrillic capital Ie
    '\u041a': 'K',  # Cyrillic capital Ka
    '\u041c': 'M',  # Cyrillic capital Em
    '\u041d': 'H',  # Cyrillic capital En
    '\u041e': 'O',  # Cyrillic capital O
    '\u0420': 'P',  # Cyrillic capital Er
    '\u0421': 'C',  # Cyrillic capital Es
    '\u0422': 'T',  # Cyrillic capital Te
    '\u0425': 'X',  # Cyrillic capital Ha

    # Greek lookalikes
    '\u03b1': 'a',  # Greek small alpha
    '\u03b5': 'e',  # Greek small epsilon
    '\u03b9': 'i',  # Greek small iota
    '\u03bf': 'o',  # Greek small omicron
    '\u03c1': 'p',  # Greek small rho
    '\u03c5': 'u',  # Greek small upsilon
    '\u0391': 'A',  # Greek capital Alpha
    '\u0392': 'B',  # Greek capital Beta
    '\u0395': 'E',  # Greek capital Epsilon
    '\u0397': 'H',  # Greek capital Eta
    '\u0399': 'I',  # Greek capital Iota
    '\u039a': 'K',  # Greek capital Kappa
    '\u039c': 'M',  # Greek capital Mu
    '\u039d': 'N',  # Greek capital Nu
    '\u039f': 'O',  # Greek capital Omicron
    '\u03a1': 'P',  # Greek capital Rho
    '\u03a4': 'T',  # Greek capital Tau
    '\u03a7': 'X',  # Greek capital Chi
    '\u03a5': 'Y',  # Greek capital Upsilon
    '\u0396': 'Z',  # Greek capital Zeta

    # Latin extended lookalikes
    '\u0101': 'a',  # Latin small a with macron
    '\u00e0': 'a',  # Latin small a with grave
    '\u00e1': 'a',  # Latin small a with acute
    '\u00e2': 'a',  # Latin small a with circumflex
    '\u00e3': 'a',  # Latin small a with tilde
    '\u00e4': 'a',  # Latin small a with diaeresis
    '\u00e8': 'e',  # Latin small e with grave
    '\u00e9': 'e',  # Latin small e with acute
    '\u00ea': 'e',  # Latin small e with circumflex
    '\u00eb': 'e',  # Latin small e with diaeresis
    '\u00ec': 'i',  # Latin small i with grave
    '\u00ed': 'i',  # Latin small i with acute
    '\u00ee': 'i',  # Latin small i with circumflex
    '\u00ef': 'i',  # Latin small i with diaeresis
    '\u00f2': 'o',  # Latin small o with grave
    '\u00f3': 'o',  # Latin small o with acute
    '\u00f4': 'o',  # Latin small o with circumflex
    '\u00f5': 'o',  # Latin small o with tilde
    '\u00f6': 'o',  # Latin small o with diaeresis
    '\u00f9': 'u',  # Latin small u with grave
    '\u00fa': 'u',  # Latin small u with acute
    '\u00fb': 'u',  # Latin small u with circumflex
    '\u00fc': 'u',  # Latin small u with diaeresis

    # Mathematical/fullwidth lookalikes
    '\uff41': 'a',  # Fullwidth a
    '\uff45': 'e',  # Fullwidth e
    '\uff49': 'i',  # Fullwidth i
    '\uff4f': 'o',  # Fullwidth o
    '\uff55': 'u',  # Fullwidth u

    # Number/letter substitutions
    '0': 'O',  # Zero for O (bidirectional)
    '1': 'l',  # One for l
    '\u2070': '0',  # Superscript zero
    '\u00b9': '1',  # Superscript one
    '\u00b2': '2',  # Superscript two
    '\u00b3': '3',  # Superscript three
}

# Reverse mapping for detection
ASCII_TO_HOMOGLYPHS = {}
for homoglyph, ascii_char in HOMOGLYPHS.items():
    if ascii_char not in ASCII_TO_HOMOGLYPHS:
        ASCII_TO_HOMOGLYPHS[ascii_char] = []
    ASCII_TO_HOMOGLYPHS[ascii_char].append(homoglyph)

# Known legitimate IDN TLDs (internationalized)
LEGITIMATE_IDN_TLDS = {
    '.xn--',  # Punycode prefix
    '.рф',    # Russian Federation
    '.中国',  # China
    '.日本',  # Japan
    '.한국',  # Korea
}

# RTL/bidi control characters to strip (security: prevent text direction attacks)
RTL_BIDI_CHARS = [
    '\u202a',  # LRE - Left-to-Right Embedding
    '\u202b',  # RLE - Right-to-Left Embedding
    '\u202c',  # PDF - Pop Directional Formatting
    '\u202d',  # LRO - Left-to-Right Override
    '\u202e',  # RLO - Right-to-Left Override
    '\u2066',  # LRI - Left-to-Right Isolate
    '\u2067',  # RLI - Right-to-Left Isolate
    '\u2068',  # FSI - First Strong Isolate
    '\u2069',  # PDI - Pop Directional Isolate
]


def strip_bidi_chars(text: str) -> str:
    """
    Strip RTL/bidi control characters from text.

    These characters can be used to visually reorder text while keeping
    the logical order different, enabling attacks where a URL appears
    safe but actually points elsewhere.

    Args:
        text: Input text that may contain bidi control characters

    Returns:
        Text with all bidi control characters removed
    """
    result = text
    for char in RTL_BIDI_CHARS:
        result = result.replace(char, '')
    return result


def normalize_unicode(text: str) -> str:
    """
    Apply consistent Unicode NFC normalization and strip dangerous characters.

    NFC (Canonical Decomposition, followed by Canonical Composition) ensures
    that equivalent Unicode sequences are represented identically.

    For example:
    - 'é' (U+00E9) and 'e' + combining acute (U+0065 U+0301) become 'é' (U+00E9)

    This prevents attacks where visually identical strings have different
    byte representations.

    Args:
        text: Input text to normalize

    Returns:
        NFC-normalized text with bidi characters stripped
    """
    # First strip bidi control characters
    text = strip_bidi_chars(text)

    # Apply NFC normalization
    return unicodedata.normalize('NFC', text)


def contains_mixed_scripts(text: str) -> tuple[bool, set[str]]:
    """
    Check if text contains characters from multiple Unicode scripts.

    Returns:
        Tuple of (is_mixed, set_of_scripts_found)
    """
    scripts = set()

    for char in text:
        if char.isalpha():
            script = unicodedata.name(char, '').split()[0]
            if script in ('LATIN', 'CYRILLIC', 'GREEK', 'ARMENIAN', 'HEBREW', 'ARABIC'):
                scripts.add(script)

    return len(scripts) > 1, scripts


def detect_homoglyphs(text: str) -> list[dict]:
    """
    Detect homoglyph characters in text.

    Returns:
        List of detected homoglyphs with positions and ASCII equivalents
    """
    detections = []

    for i, char in enumerate(text):
        if char in HOMOGLYPHS:
            detections.append({
                "position": i,
                "character": char,
                "unicode_name": unicodedata.name(char, "UNKNOWN"),
                "codepoint": f"U+{ord(char):04X}",
                "looks_like": HOMOGLYPHS[char],
            })

    return detections


def normalize_to_ascii(text: str) -> str:
    """
    Normalize text by replacing homoglyphs with ASCII equivalents.
    """
    result = []
    for char in text:
        if char in HOMOGLYPHS:
            result.append(HOMOGLYPHS[char])
        else:
            result.append(char)
    return ''.join(result)


def is_punycode_domain(domain: str) -> bool:
    """Check if domain uses punycode encoding."""
    return domain.startswith('xn--') or '.xn--' in domain


def decode_punycode(domain: str) -> str:
    """Decode punycode domain to Unicode."""
    try:
        return domain.encode('ascii').decode('idna')
    except (UnicodeError, UnicodeDecodeError):
        return domain


@ValidatorRegistry.register
class IDNHomographValidator(Validator):
    """
    Validates evidence URIs for IDN homograph attacks.

    CRITICAL SECURITY VALIDATOR:
    - Detects mixed-script attacks (Cyrillic + Latin)
    - Detects confusable character substitutions
    - Validates punycode domains
    - Blocks suspicious URI patterns
    """

    name = "idn_homograph"
    description = "Detects IDN homograph attacks in evidence URIs"
    default_severity = Severity.BLOCK

    def __init__(self, config: Optional[ValidatorConfig] = None):
        super().__init__(config)
        params = config.params if config else {}

        # Allow specific legitimate IDN domains
        self.allowed_idn_domains = set(params.get("allowed_idn_domains", []))

        # Strict mode blocks any non-ASCII in domains
        self.strict_mode = params.get("strict_mode", True)

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate evidence URIs for homograph attacks."""
        errors = []
        warnings = []
        validated_count = 0

        for claim in claims:
            for i, evidence in enumerate(claim.evidence):
                validated_count += 1
                uri = evidence.uri

                # Skip non-URL schemes
                if not uri.startswith(('http://', 'https://')):
                    continue

                uri_errors, uri_warnings = self._validate_uri(
                    uri, claim.claim_id, i
                )
                errors.extend(uri_errors)
                warnings.extend(uri_warnings)

        passed = len(errors) == 0

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=Severity.BLOCK if not passed else (Severity.WARN if warnings else Severity.INFO),
            message=(
                f"Validated {validated_count} URIs for homograph attacks"
                if passed
                else f"IDN homograph attack detected: {len(errors)} suspicious URIs"
            ),
            details={
                "errors": errors,
                "warnings": warnings,
                "validated_count": validated_count,
            },
        )

    def _validate_uri(
        self,
        uri: str,
        claim_id: str,
        evidence_index: int,
    ) -> tuple[list[dict], list[dict]]:
        """Validate a single URI for homograph attacks."""
        errors = []
        warnings = []

        try:
            # First normalize the URI to handle bidi attacks and Unicode normalization
            normalized_uri = normalize_unicode(uri)

            # Check if bidi characters were present (potential attack)
            if normalized_uri != uri:
                bidi_found = [c for c in uri if c in RTL_BIDI_CHARS]
                if bidi_found:
                    errors.append({
                        "claim_id": claim_id,
                        "evidence_index": evidence_index,
                        "uri": uri[:100],
                        "issue": "RTL/bidi control characters detected in URI",
                        "bidi_chars": [f"U+{ord(c):04X}" for c in bidi_found],
                        "security": "BIDI_ATTACK",
                    })
                    return errors, warnings

            parsed = urlparse(normalized_uri)
            domain = parsed.netloc.lower()

            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]

            # Apply NFC normalization to domain for consistent comparison
            domain = normalize_unicode(domain)

            # Check for homoglyphs in domain
            homoglyphs = detect_homoglyphs(domain)
            if homoglyphs:
                errors.append({
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "domain": domain,
                    "issue": "Homoglyph characters detected in domain",
                    "homoglyphs": homoglyphs,
                    "normalized_domain": normalize_to_ascii(domain),
                    "security": "IDN_HOMOGRAPH_ATTACK",
                })
                return errors, warnings

            # Check for mixed scripts
            is_mixed, scripts = contains_mixed_scripts(domain)
            if is_mixed:
                errors.append({
                    "claim_id": claim_id,
                    "evidence_index": evidence_index,
                    "uri": uri[:100],
                    "domain": domain,
                    "issue": f"Mixed Unicode scripts in domain: {scripts}",
                    "scripts": list(scripts),
                    "security": "MIXED_SCRIPT_ATTACK",
                })
                return errors, warnings

            # Check punycode domains
            if is_punycode_domain(domain):
                decoded = decode_punycode(domain)

                # Check if decoded domain is in allowed list
                if decoded not in self.allowed_idn_domains:
                    # Check decoded domain for homoglyphs
                    decoded_homoglyphs = detect_homoglyphs(decoded)
                    if decoded_homoglyphs:
                        errors.append({
                            "claim_id": claim_id,
                            "evidence_index": evidence_index,
                            "uri": uri[:100],
                            "domain": domain,
                            "decoded_domain": decoded,
                            "issue": "Punycode domain decodes to suspicious characters",
                            "homoglyphs": decoded_homoglyphs,
                            "security": "PUNYCODE_HOMOGRAPH",
                        })
                    elif self.strict_mode:
                        warnings.append({
                            "claim_id": claim_id,
                            "evidence_index": evidence_index,
                            "domain": domain,
                            "decoded_domain": decoded,
                            "issue": "Punycode domain detected (not in allowed list)",
                        })

            # Strict mode: flag any non-ASCII characters
            if self.strict_mode:
                non_ascii = [c for c in domain if ord(c) > 127]
                if non_ascii:
                    errors.append({
                        "claim_id": claim_id,
                        "evidence_index": evidence_index,
                        "uri": uri[:100],
                        "domain": domain,
                        "issue": "Non-ASCII characters in domain (strict mode)",
                        "non_ascii_chars": [f"U+{ord(c):04X}" for c in non_ascii],
                        "security": "NON_ASCII_DOMAIN",
                    })

        except Exception as e:
            errors.append({
                "claim_id": claim_id,
                "evidence_index": evidence_index,
                "uri": uri[:100],
                "issue": f"Failed to parse URI: {str(e)[:50]}",
            })

        return errors, warnings


def check_domain_homograph(domain: str) -> dict:
    """
    Standalone function to check a domain for homograph attacks.

    Returns:
        Dictionary with detection results
    """
    # Check for bidi characters first
    bidi_found = [c for c in domain if c in RTL_BIDI_CHARS]

    # Apply Unicode normalization and strip bidi chars
    normalized_domain = normalize_unicode(domain)

    result = {
        "domain": domain,
        "normalized_domain": normalized_domain,
        "is_safe": True,
        "issues": [],
    }

    # Flag bidi characters as security issue
    if bidi_found:
        result["is_safe"] = False
        result["issues"].append({
            "type": "bidi_attack",
            "bidi_chars": [f"U+{ord(c):04X}" for c in bidi_found],
        })

    # Check homoglyphs (on normalized domain)
    homoglyphs = detect_homoglyphs(normalized_domain)
    if homoglyphs:
        result["is_safe"] = False
        result["issues"].append({
            "type": "homoglyph",
            "details": homoglyphs,
            "normalized": normalize_to_ascii(normalized_domain),
        })

    # Check mixed scripts (on normalized domain)
    is_mixed, scripts = contains_mixed_scripts(normalized_domain)
    if is_mixed:
        result["is_safe"] = False
        result["issues"].append({
            "type": "mixed_script",
            "scripts": list(scripts),
        })

    # Check punycode (on normalized domain)
    if is_punycode_domain(normalized_domain):
        decoded = decode_punycode(normalized_domain)
        # Apply normalization to decoded domain as well
        decoded = normalize_unicode(decoded)
        result["punycode"] = True
        result["decoded"] = decoded

        decoded_homoglyphs = detect_homoglyphs(decoded)
        if decoded_homoglyphs:
            result["is_safe"] = False
            result["issues"].append({
                "type": "punycode_homograph",
                "decoded": decoded,
                "homoglyphs": decoded_homoglyphs,
            })

    return result
