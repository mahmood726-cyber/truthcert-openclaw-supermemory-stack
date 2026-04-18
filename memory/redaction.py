"""
Redaction module - scrubs secrets and PII before storage.
"""

import re
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class RedactionRule:
    """A single redaction rule."""
    name: str
    pattern: re.Pattern
    replacement: str = "[REDACTED]"
    enabled: bool = True


@dataclass
class RedactionResult:
    """Result of redaction operation."""
    original_length: int
    redacted_length: int
    redactions_made: int
    rules_applied: list[str] = field(default_factory=list)


class Redactor:
    """
    Redacts sensitive information from text before storage.

    Default rules include:
    - API keys and tokens
    - Authorization headers
    - Passwords
    - Email addresses (optional)
    - IP addresses (optional)
    - Credit card numbers
    - SSN patterns
    """

    # Default redaction patterns
    DEFAULT_RULES = [
        # API keys and tokens
        RedactionRule(
            name="api_key",
            pattern=re.compile(
                r'(?i)(api[_-]?key|apikey|api_secret|secret_key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{16,})["\']?',
                re.IGNORECASE
            ),
            replacement=r'\1=[API_KEY_REDACTED]',
        ),
        RedactionRule(
            name="bearer_token",
            pattern=re.compile(
                r'(?i)(bearer|token)\s+([a-zA-Z0-9_\-\.]{20,})',
                re.IGNORECASE
            ),
            replacement=r'\1 [TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="authorization_header",
            pattern=re.compile(
                r'(?i)(authorization)\s*[=:]\s*["\']?([^\s"\']{10,})["\']?',
                re.IGNORECASE
            ),
            replacement=r'\1=[AUTH_REDACTED]',
        ),

        # Passwords
        RedactionRule(
            name="password",
            pattern=re.compile(
                r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']{4,})["\']?',
                re.IGNORECASE
            ),
            replacement=r'\1=[PASSWORD_REDACTED]',
        ),

        # AWS credentials
        RedactionRule(
            name="aws_key",
            pattern=re.compile(r'AKIA[0-9A-Z]{16}'),
            replacement='[AWS_KEY_REDACTED]',
        ),
        RedactionRule(
            name="aws_secret",
            pattern=re.compile(r'(?i)(aws_secret|secret_access_key)\s*[=:]\s*["\']?([a-zA-Z0-9/+=]{40})["\']?'),
            replacement=r'\1=[AWS_SECRET_REDACTED]',
        ),

        # GitHub tokens (ghp_, gho_, ghs_, ghr_, github_pat_)
        RedactionRule(
            name="github_token",
            pattern=re.compile(r'ghp_[a-zA-Z0-9]{36}'),
            replacement='[GITHUB_TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="github_oauth_token",
            pattern=re.compile(r'gho_[a-zA-Z0-9]{36}'),
            replacement='[GITHUB_OAUTH_REDACTED]',
        ),
        RedactionRule(
            name="github_server_token",
            pattern=re.compile(r'ghs_[a-zA-Z0-9]{36}'),
            replacement='[GITHUB_SERVER_TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="github_refresh_token",
            pattern=re.compile(r'ghr_[a-zA-Z0-9]{36}'),
            replacement='[GITHUB_REFRESH_TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="github_fine_grained_pat",
            pattern=re.compile(r'github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}'),
            replacement='[GITHUB_PAT_REDACTED]',
        ),

        # JWT tokens (header.payload.signature)
        RedactionRule(
            name="jwt_token",
            pattern=re.compile(r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]+'),
            replacement='[JWT_REDACTED]',
        ),

        # Slack tokens
        RedactionRule(
            name="slack_bot_token",
            pattern=re.compile(r'xoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24}'),
            replacement='[SLACK_BOT_TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="slack_user_token",
            pattern=re.compile(r'xoxp-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}'),
            replacement='[SLACK_USER_TOKEN_REDACTED]',
        ),
        RedactionRule(
            name="slack_webhook",
            pattern=re.compile(r'https://hooks\.slack\.com/services/T[a-zA-Z0-9_]{8,}/B[a-zA-Z0-9_]{8,}/[a-zA-Z0-9_]{24}'),
            replacement='[SLACK_WEBHOOK_REDACTED]',
        ),

        # Google API keys
        RedactionRule(
            name="google_api_key",
            pattern=re.compile(r'AIza[0-9A-Za-z_-]{35}'),
            replacement='[GOOGLE_API_KEY_REDACTED]',
        ),
        RedactionRule(
            name="google_oauth_client_secret",
            pattern=re.compile(r'(?i)(client_secret)\s*[=:]\s*["\']?([a-zA-Z0-9_-]{24})["\']?'),
            replacement=r'\1=[GOOGLE_CLIENT_SECRET_REDACTED]',
        ),

        # Azure/Microsoft tokens
        RedactionRule(
            name="azure_storage_key",
            pattern=re.compile(r'(?i)(AccountKey|azure_storage_key)\s*[=:]\s*["\']?([a-zA-Z0-9/+=]{88})["\']?'),
            replacement=r'\1=[AZURE_KEY_REDACTED]',
        ),
        RedactionRule(
            name="azure_connection_string",
            pattern=re.compile(r'DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[a-zA-Z0-9/+=]{88}'),
            replacement='[AZURE_CONNECTION_STRING_REDACTED]',
        ),

        # Stripe keys
        RedactionRule(
            name="stripe_secret_key",
            pattern=re.compile(r'sk_live_[a-zA-Z0-9]{24,}'),
            replacement='[STRIPE_SECRET_KEY_REDACTED]',
        ),
        RedactionRule(
            name="stripe_publishable_key",
            pattern=re.compile(r'pk_live_[a-zA-Z0-9]{24,}'),
            replacement='[STRIPE_PUBLISHABLE_KEY_REDACTED]',
        ),

        # Twilio
        RedactionRule(
            name="twilio_api_key",
            pattern=re.compile(r'SK[a-f0-9]{32}'),
            replacement='[TWILIO_API_KEY_REDACTED]',
        ),

        # SendGrid
        RedactionRule(
            name="sendgrid_api_key",
            pattern=re.compile(r'SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}'),
            replacement='[SENDGRID_API_KEY_REDACTED]',
        ),

        # NPM tokens
        RedactionRule(
            name="npm_token",
            pattern=re.compile(r'npm_[a-zA-Z0-9]{36}'),
            replacement='[NPM_TOKEN_REDACTED]',
        ),

        # PyPI tokens
        RedactionRule(
            name="pypi_token",
            pattern=re.compile(r'pypi-[a-zA-Z0-9_-]{50,}'),
            replacement='[PYPI_TOKEN_REDACTED]',
        ),

        # Heroku API key
        RedactionRule(
            name="heroku_api_key",
            pattern=re.compile(r'(?i)(heroku[_-]?api[_-]?key)\s*[=:]\s*["\']?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})["\']?'),
            replacement=r'\1=[HEROKU_API_KEY_REDACTED]',
        ),

        # Credit card numbers (basic pattern)
        RedactionRule(
            name="credit_card",
            pattern=re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b'),
            replacement='[CARD_REDACTED]',
        ),

        # SSN pattern
        RedactionRule(
            name="ssn",
            pattern=re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            replacement='[SSN_REDACTED]',
        ),

        # Private keys
        RedactionRule(
            name="private_key",
            pattern=re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'),
            replacement='[PRIVATE_KEY_REDACTED]',
        ),

        # Connection strings
        RedactionRule(
            name="connection_string",
            pattern=re.compile(
                r'(?i)(mongodb|postgresql|mysql|redis|amqp|postgres)://[^\s<>"\']+',
                re.IGNORECASE
            ),
            replacement=r'[CONNECTION_STRING_REDACTED]',
        ),

        # Generic secret patterns
        RedactionRule(
            name="generic_secret",
            pattern=re.compile(
                r'(?i)(secret|private[_-]?key|access[_-]?token|auth[_-]?token)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?'
            ),
            replacement=r'\1=[SECRET_REDACTED]',
        ),

        # Base64 encoded secrets (common in configs)
        RedactionRule(
            name="base64_secret",
            pattern=re.compile(r'(?i)(secret|password|key|token)[_-]?base64\s*[=:]\s*["\']?([a-zA-Z0-9+/]{40,}={0,2})["\']?'),
            replacement=r'\1=[BASE64_SECRET_REDACTED]',
        ),
    ]

    # Optional rules (disabled by default)
    OPTIONAL_RULES = [
        RedactionRule(
            name="email",
            pattern=re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            replacement='[EMAIL_REDACTED]',
            enabled=False,
        ),
        RedactionRule(
            name="ip_address",
            pattern=re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            replacement='[IP_REDACTED]',
            enabled=False,
        ),
        RedactionRule(
            name="phone",
            pattern=re.compile(r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'),
            replacement='[PHONE_REDACTED]',
            enabled=False,
        ),
    ]

    def __init__(
        self,
        custom_rules: Optional[list[RedactionRule]] = None,
        enable_email_redaction: bool = False,
        enable_ip_redaction: bool = False,
        enable_phone_redaction: bool = False,
    ):
        """
        Initialize redactor with rules.

        Args:
            custom_rules: Additional custom rules
            enable_email_redaction: Enable email redaction
            enable_ip_redaction: Enable IP address redaction
            enable_phone_redaction: Enable phone number redaction
        """
        self.rules = list(self.DEFAULT_RULES)

        # Add optional rules if enabled
        for rule in self.OPTIONAL_RULES:
            if rule.name == "email" and enable_email_redaction:
                rule.enabled = True
            elif rule.name == "ip_address" and enable_ip_redaction:
                rule.enabled = True
            elif rule.name == "phone" and enable_phone_redaction:
                rule.enabled = True

            if rule.enabled:
                self.rules.append(rule)

        # Add custom rules
        if custom_rules:
            self.rules.extend(custom_rules)

    def redact(self, text: str) -> tuple[str, RedactionResult]:
        """
        Redact sensitive information from text.

        Args:
            text: Text to redact

        Returns:
            Tuple of (redacted_text, result)
        """
        original_length = len(text)
        redacted_text = text
        rules_applied = []
        total_redactions = 0

        for rule in self.rules:
            if not rule.enabled:
                continue

            matches = rule.pattern.findall(redacted_text)
            if matches:
                redacted_text = rule.pattern.sub(rule.replacement, redacted_text)
                rules_applied.append(rule.name)
                total_redactions += len(matches)

        result = RedactionResult(
            original_length=original_length,
            redacted_length=len(redacted_text),
            redactions_made=total_redactions,
            rules_applied=rules_applied,
        )

        return redacted_text, result

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively redact sensitive information from a dictionary.

        Args:
            data: Dictionary to redact

        Returns:
            Redacted dictionary
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                redacted, _ = self.redact(value)
                result[key] = redacted
            elif isinstance(value, dict):
                result[key] = self.redact_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.redact_dict(item) if isinstance(item, dict)
                    else (self.redact(item)[0] if isinstance(item, str) else item)
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def add_rule(self, rule: RedactionRule) -> None:
        """Add a custom redaction rule."""
        self.rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                return True
        return False


# Sensitive capture denylist - tools that should never have results captured
SENSITIVE_TOOL_DENYLIST = [
    "read_file",  # Might read arbitrary files
    "read_email",
    "get_credentials",
    "get_secrets",
    "decrypt",
    "ssh_exec",
    "exec_shell",
]


def should_capture_tool(tool_name: str, denylist: Optional[list[str]] = None) -> bool:
    """
    Check if a tool's output should be captured to memory.

    Args:
        tool_name: Name of the tool
        denylist: Custom denylist (uses default if None)

    Returns:
        True if tool output can be captured
    """
    deny = denylist or SENSITIVE_TOOL_DENYLIST
    return tool_name.lower() not in [t.lower() for t in deny]
