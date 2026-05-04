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

# System tags that should never be stored (Kimi CLI internal context)
DEFAULT_SYSTEM_TAGS = [
    "system_instruction",
    "system-reminder",
    "system",
    "system_instruction_full",
]

# System content patterns (for non-tag system content)
SYSTEM_CONTENT_PATTERNS = [
    # Kimi CLI system reminders
    r"<system-reminder>.*?</system-reminder>",
    r"<system_instruction>.*?</system_instruction>",
    r"<system_instruction_full>.*?</system_instruction_full>",
    # Generic system blocks
    r"\[system\].*?\[/system\]",
    r"\{\{system:.*?\}\}",
    # Anthropic-style system
    r"<system>.*?</system>",
]

# Sensitive data patterns (PII / credentials)
SENSITIVE_PATTERNS = [
    # API keys
    (r"(?i)(api[_-]?key\s*[:=]\s*)['\"]?[a-zA-Z0-9_\-]{16,}['\"]?", r"\1[PRIVATE]"),
    (r"(?i)(bearer\s+)['\"]?[a-zA-Z0-9_\-\.]{20,}['\"]?", r"\1[PRIVATE]"),
    # AWS keys
    (r"(?i)(AKIA[0-9A-Z]{16})", r"[PRIVATE]"),
    # Private keys
    (
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        r"[PRIVATE_KEY]",
        re.DOTALL,
    ),
    # Passwords in URLs
    (r"(?i)([a-z][a-z0-9+.-]*://[^:]+:)[^@]+(@[^/]+)", r"\1[PRIVATE]\2"),
    # GitHub tokens
    (r"(?i)(gh[pousr]_[a-zA-Z0-9]{36,})", r"[PRIVATE]"),
    # Generic high-entropy secrets
    (r"(?i)(secret\s*[:=]\s*)['\"]?[a-zA-Z0-9_\-]{16,}['\"]?", r"\1[PRIVATE]"),
]


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


def strip_system_content(text: str) -> str:
    """Remove all system-level content that should never be stored.

    This includes Kimi CLI internal tags like <system_instruction>,
    <system-reminder>, and other system context that is ephemeral
    and should not persist in memory.

    Args:
        text: Raw text content.

    Returns:
        Text with all system content removed (not replaced — fully removed).
    """
    if not text:
        return text

    result = text

    # 1. Remove known system tags (with closing tags)
    for tag in DEFAULT_SYSTEM_TAGS:
        pattern = rf"<{tag}>.*?</{tag}>"
        result = re.sub(pattern, "", result, flags=re.DOTALL | re.IGNORECASE)
        # Also handle self-closing variants
        pattern_sc = rf"<{tag}\s*/?>"
        result = re.sub(pattern_sc, "", result, flags=re.IGNORECASE)

    # 2. Remove system content patterns
    for pattern in SYSTEM_CONTENT_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.DOTALL | re.IGNORECASE)

    # 3. Collapse multiple whitespace left by removals
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[ \t]+\n", "\n", result)
    # Collapse multiple spaces into single space
    result = re.sub(r" {2,}", " ", result)
    result = result.strip()

    return result


def redact_sensitive_patterns(text: str) -> str:
    """Redact sensitive patterns like API keys, tokens, private keys.

    Uses regex-based pattern matching to identify and replace
    high-entropy credentials and PII.

    Args:
        text: Raw text content.

    Returns:
        Text with sensitive patterns redacted.
    """
    if not text:
        return text

    result = text
    for pattern, replacement, *flags in SENSITIVE_PATTERNS:
        flag = flags[0] if flags else 0
        result = re.sub(pattern, replacement, result, flags=flag)

    return result


def deep_sanitize(
    text: str,
    exclude_tags: list[str] | None = None,
    strip_system: bool = True,
    redact_sensitive: bool = True,
) -> tuple[str, bool]:
    """Full privacy v2 sanitization pipeline.

    Applies all privacy filters in order:
    1. Strip system content (fully removed)
    2. Redact sensitive patterns (API keys, tokens, etc.)
    3. Sanitize privacy tags (<private>, <secret>)

    Args:
        text: Raw text content.
        exclude_tags: Privacy tags to sanitize.
        strip_system: Whether to remove system content.
        redact_sensitive: Whether to redact sensitive patterns.

    Returns:
        Tuple of (sanitized_text, was_modified).
    """
    if not text:
        return text, False

    original = text
    result = text

    if strip_system:
        result = strip_system_content(result)

    if redact_sensitive:
        result = redact_sensitive_patterns(result)

    # Apply legacy privacy tag sanitization
    result = sanitize_content(result, exclude_tags)

    was_modified = result != original
    return result, was_modified


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
    strip_system: bool = True,
    redact_sensitive: bool = True,
) -> tuple[str, bool]:
    """Full cleaning pipeline for an observation (Privacy v2).

    Args:
        text: Raw observation text.
        file_path: Associated file path.
        max_length: Maximum content length.
        exclude_tags: Privacy tags to remove.
        exclude_patterns: File patterns to exclude.
        strip_system: Whether to strip system content.
        redact_sensitive: Whether to redact sensitive patterns.

    Returns:
        Tuple of (cleaned_text, should_skip). If should_skip is True,
        the observation should not be stored at all.
    """
    # Check if file should be excluded entirely
    if file_path and should_exclude_file(file_path, exclude_patterns):
        return "", True

    # Privacy v2: deep sanitize
    cleaned, _ = deep_sanitize(
        text,
        exclude_tags=exclude_tags,
        strip_system=strip_system,
        redact_sensitive=redact_sensitive,
    )

    # Truncate if too long
    cleaned = truncate_content(cleaned, max_length)

    # Skip if content is empty after sanitization
    should_skip = not cleaned or cleaned.strip() == ""

    return cleaned, should_skip
