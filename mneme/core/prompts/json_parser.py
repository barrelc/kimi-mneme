"""Parse JSON responses from AI structuring.

Location: mneme/core/prompts/json_parser.py

This module is part of the AI structuring pipeline. It parses raw JSON responses
from LLMs into structured ParsedObservation objects.

Related modules:
    - mneme/core/ai_provider.py        -- Uses parse_observation_json() via HybridProvider / ConfigurableAIProvider
    - mneme/core/prompts/observation_prompt.py  -- Prompt templates sent to LLM
    - mneme/core/heuristic_structuring.py       -- Fallback when AI is disabled
    - mneme/core/worker.py             -- Background worker that orchestrates structuring
    - mneme/db/structured_store.py     -- Stores the resulting ParsedObservation

Tests: tests/test_json_parser.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class ParsedObservation:
    """Structured observation from AI or heuristic."""

    type: str
    title: str
    subtitle: str | None
    facts: list[str]
    narrative: str | None
    concepts: list[str]
    files_read: list[str]
    files_modified: list[str]
    skip: bool = False
    skip_reason: str | None = None
    source: str = "ai"  # 'ai', 'heuristic', 'manual'


def parse_observation_json(text: str) -> ParsedObservation | None:
    """Parse AI JSON response into ParsedObservation.

    Args:
        text: Raw AI response text.

    Returns:
        ParsedObservation or None if parsing fails.
    """
    if not text or not text.strip():
        return None

    # Strip markdown code fences
    text = _strip_code_fences(text)

    # Try to find JSON object
    if not text.strip().startswith("{"):
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            logger.warning("No JSON found in AI response")
            return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI JSON: {e}")
        return None

    # Check skip
    if parsed.get("skip"):
        return ParsedObservation(
            type="discovery",
            title="Skipped",
            subtitle=None,
            facts=[],
            narrative=None,
            concepts=[],
            files_read=[],
            files_modified=[],
            skip=True,
            skip_reason=parsed.get("reason"),
            source="ai",
        )

    # Normalize fields
    return ParsedObservation(
        type=_normalize_type(parsed.get("type", "discovery")),
        title=str(parsed.get("title", "Untitled"))[:80],
        subtitle=str(parsed.get("subtitle", ""))[:200] or None,
        facts=_ensure_list(parsed.get("facts", [])),
        narrative=str(parsed.get("narrative", ""))[:500] or None,
        concepts=_ensure_list(parsed.get("concepts", [])),
        files_read=_ensure_list(parsed.get("files_read", [])),
        files_modified=_ensure_list(parsed.get("files_modified", [])),
        source="ai",
    )


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if entire text is wrapped."""
    text = text.strip()
    fence_pattern = r"^```(?:\w+)?\s*\n?([\s\S]*?)\n?```\s*$"
    match = re.match(fence_pattern, text)
    return match.group(1).strip() if match else text


def _normalize_type(t: str) -> str:
    """Normalize observation type to valid value."""
    valid = {"bugfix", "feature", "refactor", "change", "discovery", "decision"}
    t = t.lower().strip()
    return t if t in valid else "discovery"


def _ensure_list(value: Any) -> list[str]:
    """Ensure value is a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and v != ""]
    if isinstance(value, str):
        return [value]
    if value is not None:
        return [str(value)]
    return []
