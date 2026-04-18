"""
FTS5 Query Sanitizer - prevents injection attacks in SQLite FTS5 queries.

FTS5 has a query syntax that includes special operators that could be
exploited if user input is passed directly to MATCH clauses.
"""

import re
from typing import Optional


# FTS5 special characters and operators that need escaping
FTS5_SPECIAL_CHARS = {
    '"': '""',  # Double quotes need doubling
    "'": "''",  # Single quotes need doubling
    '*': '',    # Wildcard - remove
    '^': '',    # Column start - remove
    '-': ' ',   # NOT operator - replace with space
    '+': ' ',   # AND operator - replace with space
    '(': '',    # Grouping - remove
    ')': '',    # Grouping - remove
    ':': '',    # Column specifier - remove
    'OR': ' ',  # Boolean operator
    'AND': ' ', # Boolean operator
    'NOT': ' ', # Boolean operator
    'NEAR': '', # Proximity operator - remove
}

# Pattern to match FTS5 operators
FTS5_OPERATOR_PATTERN = re.compile(
    r'\b(OR|AND|NOT|NEAR)\b',
    re.IGNORECASE
)

# Pattern for dangerous constructs
FTS5_DANGEROUS_PATTERN = re.compile(
    r'(\{[^}]*\}|\[[^\]]*\])',  # Column filters like {col} or [col]
    re.IGNORECASE
)


def sanitize_fts5_query(query: str, allow_prefix_search: bool = False) -> str:
    """
    Sanitize a user query for safe use in FTS5 MATCH clause.

    This function:
    1. Removes or escapes FTS5 special operators
    2. Prevents column injection
    3. Normalizes whitespace
    4. Optionally preserves prefix search (*) at end of words

    Args:
        query: Raw user input query
        allow_prefix_search: If True, preserves trailing * for prefix matching

    Returns:
        Sanitized query safe for FTS5 MATCH
    """
    if not query:
        return ""

    # Limit query length to prevent DoS
    query = query[:1000]

    # Remove dangerous column filter constructs
    query = FTS5_DANGEROUS_PATTERN.sub(' ', query)

    # Replace FTS5 boolean operators with spaces
    query = FTS5_OPERATOR_PATTERN.sub(' ', query)

    result = []
    i = 0

    while i < len(query):
        char = query[i]

        if char == '"':
            # Escape double quotes by doubling
            result.append('""')
        elif char == "'":
            # Escape single quotes by doubling
            result.append("''")
        elif char == '*':
            # Optionally preserve prefix search
            if allow_prefix_search and i > 0 and query[i-1].isalnum():
                # Only allow * at end of words
                if i == len(query) - 1 or not query[i+1].isalnum():
                    result.append(char)
            # Otherwise strip it
        elif char in '(){}[]^:':
            # Remove grouping and column specifiers
            result.append(' ')
        elif char == '-':
            # Replace NOT operator with space (unless it's a hyphenated word)
            if i > 0 and i < len(query) - 1:
                if query[i-1].isalnum() and query[i+1].isalnum():
                    # Hyphenated word - keep it
                    result.append(char)
                else:
                    result.append(' ')
            else:
                result.append(' ')
        elif char == '+':
            # Replace AND operator with space
            result.append(' ')
        elif char == '\n' or char == '\r' or char == '\t':
            # Normalize whitespace
            result.append(' ')
        else:
            result.append(char)

        i += 1

    # Join and normalize whitespace
    sanitized = ''.join(result)
    sanitized = ' '.join(sanitized.split())

    # If empty after sanitization, return a safe default
    if not sanitized.strip():
        return '""'  # Empty string literal for FTS5

    # Quote hyphenated words to prevent FTS5 misinterpretation
    # FTS5 treats bare "word-word" as "word NOT word" which fails
    # Quoting makes it a phrase search which works correctly
    words = sanitized.split()
    quoted_words = []
    for word in words:
        if '-' in word and not word.startswith('"'):
            # Quote the hyphenated word, escaping any internal quotes
            escaped = word.replace('"', '""')
            quoted_words.append(f'"{escaped}"')
        else:
            quoted_words.append(word)

    return ' '.join(quoted_words)


def escape_fts5_string(value: str) -> str:
    """
    Escape a string for use as a literal in FTS5.

    Wraps the value in double quotes and escapes internal quotes.

    Args:
        value: String to escape

    Returns:
        Quoted and escaped string
    """
    if not value:
        return '""'

    # Escape double quotes
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def build_safe_fts5_query(
    terms: list[str],
    operator: str = "AND",
    column: Optional[str] = None,
) -> str:
    """
    Build a safe FTS5 query from multiple terms.

    Args:
        terms: List of search terms
        operator: Boolean operator (AND or OR)
        column: Optional column to search (must be in allowed list)

    Returns:
        Safe FTS5 query string
    """
    # Validate operator
    if operator.upper() not in ("AND", "OR"):
        operator = "AND"

    # Sanitize and quote each term
    safe_terms = []
    for term in terms:
        if term:
            # Remove any special characters
            clean_term = sanitize_fts5_query(term)
            if clean_term and clean_term != '""':
                safe_terms.append(escape_fts5_string(clean_term))

    if not safe_terms:
        return '""'

    # Join with operator
    query = f" {operator.upper()} ".join(safe_terms)

    # Add column prefix if specified (only for allowed columns)
    allowed_columns = {"text", "tags", "id"}
    if column and column.lower() in allowed_columns:
        query = f"{column.lower()}: ({query})"

    return query


def validate_fts5_query(query: str) -> tuple[bool, Optional[str]]:
    """
    Validate an FTS5 query for safety.

    Args:
        query: Query to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not query:
        return False, "Empty query"

    if len(query) > 1000:
        return False, "Query too long (max 1000 characters)"

    # Check for unbalanced quotes
    quote_count = query.count('"') - query.count('""') * 2
    if quote_count % 2 != 0:
        return False, "Unbalanced quotes in query"

    # Check for dangerous patterns
    dangerous_patterns = [
        (r'\bNEAR/\d+', "NEAR operator with distance not allowed"),
        (r'\{[^}]+\}', "Column filter syntax not allowed"),
        (r'\[[^\]]+\]', "Column filter syntax not allowed"),
    ]

    for pattern, message in dangerous_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return False, message

    return True, None
