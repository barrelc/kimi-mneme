"""AI provider for observation structuring using configurable LLM backends."""

from __future__ import annotations

from typing import Any

from loguru import logger

from mneme.core.heuristic_structuring import HeuristicStructuring
from mneme.core.llm_client import LLMMessage, create_llm_client
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


class ConfigurableAIProvider(AIProvider):
    """AI provider that uses any LLM client from config."""

    def __init__(
        self,
        provider: str = "kimi",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        self.client = create_llm_client(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            **kwargs,
        )
        self.enabled = enabled and (self.client is not None) and self.client.enabled

    async def structure_observation(
        self, tool_name: str, tool_input: Any, tool_output: str | None, error: str | None
    ) -> ParsedObservation | None:
        if not self.enabled or self.client is None:
            return None

        prompt = OBSERVATION_USER_PROMPT.format(
            tool_name=tool_name or "unknown",
            tool_input=str(tool_input)[:500] if tool_input else "",
            tool_output=str(tool_output)[:2000] if tool_output else "",
            error=str(error)[:500] if error else "",
            timestamp="",
        )

        try:
            response = await self.client.chat(
                messages=[
                    LLMMessage(role="system", content=OBSERVATION_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.3,
                max_tokens=800,
            )
            if response is None:
                return None

            return parse_observation_json(response.content)

        except Exception as e:
            logger.warning(f"AI structuring failed: {e}")
            return None


# Backward-compatible alias
KimiProvider = ConfigurableAIProvider


class HybridProvider(AIProvider):
    """Try AI first, fallback to heuristic."""

    def __init__(self, ai_provider: AIProvider | None = None) -> None:
        self.ai = ai_provider or ConfigurableAIProvider()
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
