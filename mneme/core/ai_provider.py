"""AI provider for observation structuring using Kimi API (reuses OAuth token)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from mneme.core.heuristic_structuring import HeuristicStructuring
from mneme.core.prompts.json_parser import ParsedObservation, parse_observation_json
from mneme.core.prompts.observation_prompt import (
    OBSERVATION_SYSTEM_PROMPT,
    OBSERVATION_USER_PROMPT,
)


class AIProvider:
    """Abstract AI provider for structuring."""

    async def structure_observation(
        self, tool_name: str, tool_input: Any, tool_output: str | None, error: str | None
    ) -> ParsedObservation | None:
        """Send to LLM, parse JSON response."""
        raise NotImplementedError


def _load_kimi_token() -> str | None:
    """Load OAuth access token from kimi-cli credentials."""
    creds_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
    if not creds_path.exists():
        return None
    try:
        data = json.loads(creds_path.read_text())
        return data.get("access_token")
    except Exception:
        return None


class KimiProvider(AIProvider):
    """Kimi API provider for structuring — reuses OAuth token from kimi-cli."""

    def __init__(self) -> None:
        self.token = _load_kimi_token()
        self.model = "kimi-k2.5"
        self.enabled = bool(self.token)
        self.timeout = 30.0

    async def structure_observation(
        self, tool_name: str, tool_input: Any, tool_output: str | None, error: str | None
    ) -> ParsedObservation | None:
        if not self.enabled:
            return None

        prompt = OBSERVATION_USER_PROMPT.format(
            tool_name=tool_name or "unknown",
            tool_input=str(tool_input)[:500] if tool_input else "",
            tool_output=str(tool_output)[:2000] if tool_output else "",
            error=str(error)[:500] if error else "",
            timestamp="",
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    "https://api.kimi.com/coding/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": OBSERVATION_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 800,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                return parse_observation_json(content)

        except Exception as e:
            logger.warning(f"Kimi structuring failed: {e}")
            return None


class HybridProvider(AIProvider):
    """Try AI first, fallback to heuristic."""

    def __init__(self) -> None:
        self.ai = KimiProvider()
        self.heuristic = HeuristicStructuring()

    async def structure_observation(
        self, tool_name: str, tool_input: Any, tool_output: str | None, error: str | None
    ) -> ParsedObservation | None:
        # Try AI first for complex observations
        output_len = len(str(tool_output or ""))
        has_error = bool(error)

        if self.ai.enabled and (output_len > 300 or has_error):
            result = await self.ai.structure_observation(tool_name, tool_input, tool_output, error)
            if result and not result.skip:
                return result

        # Fallback to heuristic
        obs_dict = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            "error": error,
        }
        heuristic_result = self.heuristic.structure(obs_dict)

        return ParsedObservation(
            type=heuristic_result.type,
            title=heuristic_result.title,
            subtitle=heuristic_result.subtitle,
            facts=heuristic_result.facts,
            narrative=heuristic_result.narrative,
            concepts=heuristic_result.concepts,
            files_read=heuristic_result.files_read,
            files_modified=heuristic_result.files_modified,
            source="heuristic",
        )
