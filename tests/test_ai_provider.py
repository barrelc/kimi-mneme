"""Tests for AI provider and heuristic structuring."""

from __future__ import annotations

from mneme.core.ai_provider import HybridProvider, _load_kimi_token
from mneme.core.heuristic_structuring import HeuristicStructuring
from mneme.core.prompts.json_parser import parse_observation_json


class TestLoadKimiToken:
    def test_load_without_credentials(self):
        # Should return None when credentials don't exist
        token = _load_kimi_token()
        # We can't know if user has credentials, but function shouldn't crash
        assert token is None or isinstance(token, str)


class TestHeuristicStructuring:
    def test_write_file_detection(self):
        h = HeuristicStructuring()
        obs = {
            "tool_name": "WriteFile",
            "tool_input": {"path": "src/main.py"},
            "tool_output": "File written successfully",
            "error": "",
        }
        result = h.structure(obs)
        # WriteFile without error → change (from TOOL_TYPE_MAP)
        assert result.type == "change"
        assert "main.py" in result.title or "WriteFile" in result.title
        assert "src/main.py" in result.files_modified

    def test_error_without_fix(self):
        h = HeuristicStructuring()
        obs = {
            "tool_name": "Shell",
            "tool_input": "python test.py",
            "tool_output": "just some output",
            "error": "ModuleNotFoundError: No module named 'foo'",
        }
        result = h.structure(obs)
        # Error without fix pattern in output → discovery
        assert result.type == "discovery"
        assert any("Error" in f for f in result.facts)

    def test_bugfix_pattern(self):
        h = HeuristicStructuring()
        obs = {
            "tool_name": "StrReplaceFile",
            "tool_input": {},
            "tool_output": "Fixed the null pointer issue",
            "error": "AttributeError: 'NoneType'",
        }
        result = h.structure(obs)
        assert result.type == "bugfix"


class TestParseObservationJson:
    def test_valid_json(self):
        text = '{"type": "feature", "title": "New login", "facts": ["Added OAuth"]}'
        result = parse_observation_json(text)
        assert result is not None
        assert result.type == "feature"
        assert result.title == "New login"
        assert result.facts == ["Added OAuth"]

    def test_with_code_fences(self):
        text = '```json\n{"type": "discovery", "title": "Found bug", "facts": []}\n```'
        result = parse_observation_json(text)
        assert result is not None
        assert result.type == "discovery"

    def test_skip_response(self):
        text = '{"skip": true, "reason": "too trivial"}'
        result = parse_observation_json(text)
        assert result is not None
        assert result.skip is True

    def test_invalid_json(self):
        result = parse_observation_json("not json at all")
        assert result is None

    def test_normalize_type(self):
        text = '{"type": "BUGFIX", "title": "Fix", "facts": []}'
        result = parse_observation_json(text)
        assert result.type == "bugfix"


class TestHybridProvider:
    def test_heuristic_fallback_when_ai_disabled(self):
        provider = HybridProvider()
        # If no Kimi token, should use heuristic
        if not provider.ai.enabled:
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                provider.structure_observation("WriteFile", {"path": "x.py"}, "ok", None)
            )
            assert result is not None
            assert result.source == "heuristic"
