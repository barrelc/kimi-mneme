"""Tests for content sanitization."""

from __future__ import annotations

import pytest

from mneme.core.sanitize import (
    clean_observation,
    extract_file_path,
    sanitize_content,
    should_exclude_file,
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
