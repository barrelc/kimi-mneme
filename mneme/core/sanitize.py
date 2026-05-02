"""Content sanitization and privacy filtering."""

from __future__ import annotations

import re

from loguru import logger

# Default patterns to exclude
DEFAULT_EXCLUDE_PATTERNS = [
    r".*\.env.*",
    r".*secret.*",
    r".*password.*",
    r".*token.*",
    r".*api_key.*",
    r".*private_key.*",
]

# Privacy tags
DEFAULT_EXCLUDE_TAGS = ["private", "secret"]


def sanitize_content(text: str, exclude_tags: list[str] | None = None) -> str:
    """Remove privacy tags from content.

    Args:
        text: Raw text content.
        exclude_tags: List of tag names to exclude. Defaults to ["private", "secret"].

    Returns:
        Sanitized text with tags replaced by [PRIVATE].
    """
    if not text:
        return text

    tags = exclude_tags or DEFAULT_EXCLUDE_TAGS
    result = text

    for tag in tags:
        # Match <tag>...</tag> (multiline, case-insensitive)
        pattern = rf"<{tag}>.*?</{tag}>"
        result = re.sub(pattern, "[PRIVATE]", result, flags=re.DOTALL | re.IGNORECASE)

    return result


def should_exclude_file(file_path: str, exclude_patterns: list[str] | None = None) -> bool:
    """Check if a file should be excluded based on patterns.

    Args:
        file_path: Path to check.
        exclude_patterns: List of regex patterns. Uses defaults if None.

    Returns:
        True if file should be excluded.
    """
    if not file_path:
        return False

    patterns = exclude_patterns or DEFAULT_EXCLUDE_PATTERNS

    for pattern in patterns:
        if re.search(pattern, file_path, re.IGNORECASE):
            logger.debug(f"Excluding file matching pattern '{pattern}': {file_path}")
            return True

    return False


def truncate_content(text: str, max_length: int = 100000) -> str:
    """Truncate content to maximum length.

    Args:
        text: Text to truncate.
        max_length: Maximum length in characters.

    Returns:
        Truncated text with indicator.
    """
    if not text or len(text) <= max_length:
        return text

    return text[:max_length] + "\n...[truncated]"


def extract_file_path(tool_input: dict) -> str | None:
    """Extract file path from common tool input formats.

    Args:
        tool_input: Tool input dictionary.

    Returns:
        File path if found, None otherwise.
    """
    if not isinstance(tool_input, dict):
        return None

    for key in ["path", "file_path", "filename", "dest", "source"]:
        if key in tool_input and isinstance(tool_input[key], str):
            return tool_input[key]

    return None


def clean_observation(
    text: str,
    file_path: str | None = None,
    max_length: int = 100000,
    exclude_tags: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> tuple[str, bool]:
    """Full cleaning pipeline for an observation.

    Args:
        text: Raw observation text.
        file_path: Associated file path.
        max_length: Maximum content length.
        exclude_tags: Privacy tags to remove.
        exclude_patterns: File patterns to exclude.

    Returns:
        Tuple of (cleaned_text, should_skip). If should_skip is True,
        the observation should not be stored at all.
    """
    # Check if file should be excluded entirely
    if file_path and should_exclude_file(file_path, exclude_patterns):
        return "", True

    # Sanitize privacy tags
    cleaned = sanitize_content(text, exclude_tags)

    # Truncate if too long
    cleaned = truncate_content(cleaned, max_length)

    return cleaned, False
