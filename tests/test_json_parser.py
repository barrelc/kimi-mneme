"""Tests for JSON parser."""

from __future__ import annotations

import pytest

from mneme.core.prompts.json_parser import (
    ParsedObservation,
    _ensure_list,
    _normalize_type,
    _strip_code_fences,
    parse_observation_json,
)


class TestStripCodeFences:
    def test_basic_fence(self):
        text = "```json\n{\"a\": 1}\n```"
        assert _strip_code_fences(text) == '{"a": 1}'

    def test_no_fence(self):
        text = '{"a": 1}'
        assert _strip_code_fences(text) == '{"a": 1}'

    def test_plain_fence(self):
        text = "```\nhello\n```"
        assert _strip_code_fences(text) == "hello"


class TestNormalizeType:
    def test_valid_types(self):
        assert _normalize_type("bugfix") == "bugfix"
        assert _normalize_type("feature") == "feature"
        assert _normalize_type("discovery") == "discovery"

    def test_invalid_type(self):
        assert _normalize_type("unknown") == "discovery"
        assert _normalize_type("") == "discovery"

    def test_case_insensitive(self):
        assert _normalize_type("BUGFIX") == "bugfix"
        assert _normalize_type("Feature") == "feature"


class TestEnsureList:
    def test_list_input(self):
        assert _ensure_list(["a", "b"]) == ["a", "b"]

    def test_string_input(self):
        assert _ensure_list("hello") == ["hello"]

    def test_none_input(self):
        assert _ensure_list(None) == []

    def test_int_input(self):
        assert _ensure_list(42) == ["42"]


class TestParseObservationJson:
    def test_full_object(self):
        text = """{
            "type": "feature",
            "title": "Add user auth",
            "subtitle": "OAuth2 integration",
            "facts": ["Added JWT middleware", "Created login endpoint"],
            "narrative": "Implemented full OAuth2 flow",
            "concepts": ["auth", "jwt", "oauth"],
            "files_read": ["docs/oauth.md"],
            "files_modified": ["src/auth.py", "src/routes.py"]
        }"""
        result = parse_observation_json(text)
        assert result is not None
        assert result.type == "feature"
        assert result.title == "Add user auth"
        assert result.subtitle == "OAuth2 integration"
        assert len(result.facts) == 2
        assert result.narrative == "Implemented full OAuth2 flow"
        assert result.source == "ai"

    def test_minimal_object(self):
        text = '{"type": "discovery", "title": "Found issue"}'
        result = parse_observation_json(text)
        assert result is not None
        assert result.type == "discovery"
        assert result.facts == []

    def test_empty_response(self):
        assert parse_observation_json("") is None
        assert parse_observation_json("   ") is None

    def test_non_json_text(self):
        assert parse_observation_json("Just some text") is None
