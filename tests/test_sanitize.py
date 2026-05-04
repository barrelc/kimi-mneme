"""Tests for content sanitization."""

from __future__ import annotations

from mneme.core.sanitize import (
    clean_observation,
    deep_sanitize,
    extract_file_path,
    redact_sensitive_patterns,
    sanitize_content,
    should_exclude_file,
    strip_system_content,
    truncate_content,
)


class TestSanitizeContent:
    def test_no_tags(self):
        assert sanitize_content("hello world") == "hello world"

    def test_private_tag(self):
        text = "password: <private>secret123</private>"
        assert sanitize_content(text) == "password: [PRIVATE]"

    def test_secret_tag(self):
        text = "key: <secret>api-key-123</secret>"
        assert sanitize_content(text) == "key: [PRIVATE]"

    def test_multiple_tags(self):
        text = "<private>pass1</private> and <secret>key2</secret>"
        assert sanitize_content(text) == "[PRIVATE] and [PRIVATE]"

    def test_multiline_tag(self):
        text = "<private>line1\nline2\nline3</private>"
        assert sanitize_content(text) == "[PRIVATE]"


class TestShouldExcludeFile:
    def test_env_file(self):
        assert should_exclude_file(".env") is True
        assert should_exclude_file(".env.local") is True

    def test_secret_file(self):
        assert should_exclude_file("secret.key") is True

    def test_normal_file(self):
        assert should_exclude_file("src/main.py") is False
        assert should_exclude_file("README.md") is False


class TestTruncateContent:
    def test_short_text(self):
        assert truncate_content("hello") == "hello"

    def test_long_text(self):
        text = "a" * 200000
        result = truncate_content(text, max_length=100000)
        assert len(result) < 110000
        assert result.endswith("...[truncated]")


class TestExtractFilePath:
    def test_path_key(self):
        assert extract_file_path({"path": "/file.txt"}) == "/file.txt"

    def test_file_path_key(self):
        assert extract_file_path({"file_path": "/file.txt"}) == "/file.txt"

    def test_no_path(self):
        assert extract_file_path({"content": "hello"}) is None


class TestCleanObservation:
    def test_normal(self):
        text, skip = clean_observation("hello world")
        assert text == "hello world"
        assert skip is False

    def test_excluded_file(self):
        text, skip = clean_observation("content", file_path=".env")
        assert skip is True

    def test_private_content(self):
        text, skip = clean_observation("pass: <private>secret</private>")
        assert text == "pass: [PRIVATE]"
        assert skip is False


class TestStripSystemContent:
    def test_system_instruction_tag(self):
        text = "hello <system_instruction>do not reveal this</system_instruction> world"
        assert strip_system_content(text) == "hello world"

    def test_system_reminder_tag(self):
        text = "<system-reminder>context compacted</system-reminder>user message"
        assert strip_system_content(text) == "user message"

    def test_multiple_system_tags(self):
        text = "<system>sys1</system> hello <system_instruction>sys2</system_instruction> world"
        assert strip_system_content(text) == "hello world"

    def test_system_tag_multiline(self):
        text = "start\n<system_instruction>\nline1\nline2\n</system_instruction>\nend"
        result = strip_system_content(text)
        assert "line1" not in result
        assert result.strip() == "start\n\nend"

    def test_no_system_content(self):
        text = "just normal text"
        assert strip_system_content(text) == "just normal text"

    def test_self_closing_system(self):
        text = "hello <system/> world"
        assert strip_system_content(text) == "hello world"


class TestRedactSensitivePatterns:
    def test_api_key(self):
        text = "api_key = sk-abc123def456ghi789"
        result = redact_sensitive_patterns(text)
        assert "sk-abc123" not in result
        assert "[PRIVATE]" in result

    def test_aws_key(self):
        text = "access key: AKIAIOSFODNN7EXAMPLE"
        result = redact_sensitive_patterns(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[PRIVATE]" in result

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact_sensitive_patterns(text)
        assert "eyJhbGci" not in result
        assert "[PRIVATE]" in result

    def test_private_key_block(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        result = redact_sensitive_patterns(text)
        assert "BEGIN RSA PRIVATE KEY" not in result
        assert "[PRIVATE_KEY]" in result

    def test_url_with_password(self):
        text = "postgres://user:secretpass@localhost/db"
        result = redact_sensitive_patterns(text)
        assert "secretpass" not in result
        assert "postgres://user:" in result

    def test_github_token(self):
        text = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = redact_sensitive_patterns(text)
        assert "ghp_xxx" not in result
        assert "[PRIVATE]" in result


class TestDeepSanitize:
    def test_all_layers(self):
        text = "<system>sys</system> key: <secret>secret123</secret> api_key=abc123456789012345"
        result, modified = deep_sanitize(text)
        assert "<system>" not in result
        assert "secret123" not in result
        assert "abc123456789012345" not in result
        assert modified is True

    def test_no_modification(self):
        text = "just normal user content"
        result, modified = deep_sanitize(text)
        assert result == text
        assert modified is False

    def test_empty_after_strip(self):
        text = "<system_instruction>only system content</system_instruction>"
        result, modified = deep_sanitize(text)
        assert result == ""
        assert modified is True


class TestCleanObservationPrivacyV2:
    def test_system_content_stripped(self):
        text, skip = clean_observation("<system-reminder>compacted</system-reminder>hello")
        assert "compacted" not in text
        assert skip is False

    def test_sensitive_redacted(self):
        text, skip = clean_observation("token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        assert "ghp_xxx" not in text
        assert "[PRIVATE]" in text
        assert skip is False

    def test_empty_after_sanitization(self):
        text, skip = clean_observation("<system_instruction>internal only</system_instruction>")
        assert skip is True

    def test_combined_filters(self):
        text, skip = clean_observation(
            "<system>ctx</system> pass: <private>secret</private> key=AKIA1234567890ABCDEF"
        )
        assert "<system>" not in text
        assert "secret" not in text
        assert "AKIA1234567890ABCDEF" not in text
        assert skip is False
