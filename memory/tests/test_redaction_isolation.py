"""Synthetic privacy regressions for independent redaction policies and deep metadata."""

import re

from memory.redaction import RedactionRule, Redactor


def test_enabling_optional_email_rule_does_not_change_default_redactor():
    """A prior opt-in must not silently mutate future redaction policies."""
    opted_in = Redactor(enable_email_redaction=True)
    default = Redactor()
    sample = "contact synthetic@example.org"
    assert "[EMAIL_REDACTED]" in opted_in.redact(sample)[0]
    assert default.redact(sample)[0] == sample


def test_disabling_instance_rule_cannot_disable_another_instances_secret_redaction():
    """Mutable class-level rule templates must never be shared by reference."""
    first = Redactor()
    password = next(rule for rule in first.rules if rule.name == "password")
    password.enabled = False
    fresh = Redactor()
    sample = "password=synthetic-secret-12345"
    assert sample in first.redact(sample)[0]
    assert "synthetic-secret-12345" not in fresh.redact(sample)[0]


def test_caller_mutation_cannot_disable_a_custom_policy_after_registration():
    """A custom rule must be copied both at construction and add_rule time."""
    rule = RedactionRule(
        name="private_marker",
        pattern=re.compile("SYNTHETIC_PRIVATE_MARKER"),
        replacement="[REDACTED_CUSTOM]",
    )
    at_init = Redactor(custom_rules=[rule])
    added = Redactor()
    added.add_rule(rule)
    rule.enabled = False

    assert "[REDACTED_CUSTOM]" in at_init.redact("SYNTHETIC_PRIVATE_MARKER")[0]
    assert "[REDACTED_CUSTOM]" in added.redact("SYNTHETIC_PRIVATE_MARKER")[0]


def test_nested_lists_and_dictionaries_redact_all_text_without_mutating_input():
    """Secret values at more than one list depth are scrubbed before storage."""
    secret = "api_key=" + "A" * 24
    original = {
        "outer": [
            ["ordinary", secret],
            {"middle": [[{"leaf": "password=syntheticsecret123"}]]},
        ],
    }
    redacted = Redactor().redact_dict(original)

    assert "A" * 24 not in str(redacted)
    assert "syntheticsecret123" not in str(redacted)
    assert "REDACTED" in str(redacted)
    assert secret in str(original)
    assert redacted["outer"][0][0] == "ordinary"
