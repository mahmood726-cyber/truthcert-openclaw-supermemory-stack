"""
Tests for FTS5 query sanitization - prevents SQL injection attacks.
"""

from memory.fts5_sanitizer import (
    build_safe_fts5_query,
    escape_fts5_string,
    sanitize_fts5_query,
    validate_fts5_query,
)


class TestSanitizeFts5Query:
    """Test FTS5 query sanitization."""

    def test_simple_query_unchanged(self):
        """Test that simple queries pass through (hyphenated words get quoted for FTS5)."""
        assert sanitize_fts5_query("hello world") == "hello world"
        # Hyphenated words are quoted to prevent FTS5 misinterpretation
        assert sanitize_fts5_query("meta-analysis") == '"meta-analysis"'

    def test_boolean_operators_removed(self):
        """Test that boolean operators are replaced with spaces."""
        result = sanitize_fts5_query("hello OR world")
        assert "OR" not in result
        assert "hello" in result
        assert "world" in result

        result = sanitize_fts5_query("hello AND world")
        assert "AND" not in result

        result = sanitize_fts5_query("NOT secret")
        assert "NOT" not in result

    def test_near_operator_removed(self):
        """Test that NEAR operator is removed."""
        result = sanitize_fts5_query("hello NEAR world")
        assert "NEAR" not in result

    def test_quotes_escaped(self):
        """Test that quotes are properly escaped."""
        result = sanitize_fts5_query('hello "world"')
        assert '""' in result

        result = sanitize_fts5_query("it's a test")
        assert "''" in result

    def test_column_specifiers_removed(self):
        """Test that column specifiers are removed."""
        result = sanitize_fts5_query("text:secret")
        assert ":" not in result or "text secret" in result.replace(" ", "")

        result = sanitize_fts5_query("{text}:secret")
        assert "{" not in result
        assert "}" not in result

    def test_grouping_removed(self):
        """Test that grouping parentheses are removed."""
        result = sanitize_fts5_query("(hello OR world)")
        assert "(" not in result
        assert ")" not in result

    def test_wildcards_removed_by_default(self):
        """Test that wildcards are removed by default."""
        result = sanitize_fts5_query("hell*")
        assert "*" not in result

    def test_wildcards_preserved_when_allowed(self):
        """Test that trailing wildcards are preserved when allowed."""
        result = sanitize_fts5_query("hello*", allow_prefix_search=True)
        assert result == "hello*"

        # But not in middle of word
        result = sanitize_fts5_query("hel*lo", allow_prefix_search=True)
        assert "*" not in result

    def test_query_length_limited(self):
        """Test that queries are truncated."""
        long_query = "a" * 2000
        result = sanitize_fts5_query(long_query)
        assert len(result) <= 1000

    def test_empty_query_returns_safe_default(self):
        """Test that empty queries return safe default."""
        assert sanitize_fts5_query("") == ""
        assert sanitize_fts5_query("***") == '""'  # All special chars removed

    def test_whitespace_normalized(self):
        """Test that whitespace is normalized."""
        result = sanitize_fts5_query("hello    world")
        assert "    " not in result

        result = sanitize_fts5_query("hello\n\tworld")
        assert "\n" not in result
        assert "\t" not in result

    def test_hyphenated_words_preserved(self):
        """Test that hyphens in compound words are preserved (quoted for FTS5 safety)."""
        result = sanitize_fts5_query("meta-analysis")
        # Hyphenated words are quoted to prevent FTS5 interpreting as NOT operator
        assert result == '"meta-analysis"'
        # But the hyphen is preserved within the quotes
        assert "meta-analysis" in result

    def test_leading_hyphen_removed(self):
        """Test that leading hyphens (NOT operator) are removed."""
        result = sanitize_fts5_query("-excluded")
        assert result.strip() == "excluded"


class TestEscapeFts5String:
    """Test FTS5 string escaping."""

    def test_simple_string_quoted(self):
        """Test that simple strings are quoted."""
        assert escape_fts5_string("hello") == '"hello"'

    def test_internal_quotes_escaped(self):
        """Test that internal quotes are escaped."""
        assert escape_fts5_string('hello "world"') == '"hello ""world"""'

    def test_empty_string_handled(self):
        """Test that empty string returns empty quotes."""
        assert escape_fts5_string("") == '""'


class TestBuildSafeFts5Query:
    """Test safe FTS5 query building."""

    def test_multiple_terms_joined(self):
        """Test that multiple terms are joined."""
        result = build_safe_fts5_query(["hello", "world"])
        assert '"hello"' in result
        assert '"world"' in result
        assert "AND" in result

    def test_or_operator(self):
        """Test OR operator."""
        result = build_safe_fts5_query(["hello", "world"], operator="OR")
        assert "OR" in result

    def test_invalid_operator_defaults_to_and(self):
        """Test that invalid operator defaults to AND."""
        result = build_safe_fts5_query(["hello", "world"], operator="INVALID")
        assert "AND" in result

    def test_empty_terms_handled(self):
        """Test that empty terms are handled."""
        result = build_safe_fts5_query([])
        assert result == '""'

    def test_allowed_column_prefix(self):
        """Test that allowed columns are prefixed."""
        result = build_safe_fts5_query(["hello"], column="text")
        assert "text:" in result

    def test_disallowed_column_ignored(self):
        """Test that disallowed columns are ignored."""
        result = build_safe_fts5_query(["hello"], column="secret_column")
        assert "secret_column" not in result


class TestValidateFts5Query:
    """Test FTS5 query validation."""

    def test_valid_query_passes(self):
        """Test that valid queries pass."""
        valid, error = validate_fts5_query("hello world")
        assert valid
        assert error is None

    def test_empty_query_fails(self):
        """Test that empty queries fail."""
        valid, error = validate_fts5_query("")
        assert not valid
        assert "Empty" in error

    def test_long_query_fails(self):
        """Test that overly long queries fail."""
        valid, error = validate_fts5_query("a" * 2000)
        assert not valid
        assert "too long" in error

    def test_unbalanced_quotes_fail(self):
        """Test that unbalanced quotes fail."""
        valid, error = validate_fts5_query('hello "world')
        assert not valid
        assert "quote" in error.lower()

    def test_column_filter_syntax_fails(self):
        """Test that column filter syntax fails."""
        valid, _error = validate_fts5_query("{text}:secret")
        assert not valid


class TestSqlInjectionPrevention:
    """Test prevention of SQL injection attacks."""

    def test_drop_table_sanitized(self):
        """Test that DROP TABLE attempts are sanitized."""
        result = sanitize_fts5_query('"; DROP TABLE memory_items; --')
        assert "DROP" in result  # The word remains but is safe as search text
        assert '""' in result  # Quotes are escaped

    def test_union_select_sanitized(self):
        """Test that UNION SELECT attempts are sanitized."""
        result = sanitize_fts5_query("' UNION SELECT * FROM users --")
        assert "''" in result  # Quote escaped

    def test_nested_injection_sanitized(self):
        """Test that nested injection attempts are sanitized."""
        result = sanitize_fts5_query("a' OR '1'='1")
        assert "''" in result

    def test_column_injection_blocked(self):
        """Test that column injection is blocked."""
        result = sanitize_fts5_query("[rowid]:1")
        assert "[" not in result
        assert "]" not in result
