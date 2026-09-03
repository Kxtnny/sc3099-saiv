"""
Input sanitisation for user-supplied text.

XSS prevention per docs/SECURITY-REQUIREMENTS.md: strip HTML markup from free
text fields so stored values can never be reflected back as live markup.
"""

import html
import re

# Matches any HTML/XML-looking tag, including unclosed ones such as "<script".
_TAG_RE = re.compile(r"<[^>]*>?")
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(value: str, max_length: int = 255) -> str:
    """
    Remove markup from a free-text field.

    Tags are stripped rather than escaped so the stored value stays readable,
    and any leftover angle brackets are escaped as a second line of defence.
    Ordinary names pass through untouched: quotes and apostrophes are
    preserved so "O'Brien" is not mangled into "O&#x27;Brien".
    """
    if not value:
        return value

    cleaned = _TAG_RE.sub("", value)
    cleaned = html.escape(cleaned, quote=False)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:max_length]


def escape_like(value: str) -> str:
    """
    Escape LIKE/ILIKE wildcards in a search term.

    SQLAlchemy parameterises the value, so this is not about injection - it
    stops a user's literal '%' from matching everything.
    """
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
