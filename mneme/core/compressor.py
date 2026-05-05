"""AI-powered compression of observations into semantic summaries."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from mneme.core.llm_client import LLMMessage, create_llm_client

COMPRESSION_PROMPT = """You are a coding session summarizer. Your task is to create a concise,
semantic summary of the following coding session observations.

Include:
1. What was accomplished (main goals)
2. Key files modified
3. Important decisions or architectural choices
4. Any errors encountered and how they were resolved
5. Open questions or next steps (if any)

Keep the summary under 500 words. Use bullet points for clarity.

Observations:
{observations}

Summary:"""


class Compressor:
    """Compress observations into semantic summaries using configurable LLM."""

    def __init__(
        self,
        provider: str = "kimi",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        batch_size: int = 50,
        **kwargs: Any,
    ) -> None:
        self.client = create_llm_client(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            **kwargs,
        )
        self.enabled = (self.client is not None) and self.client.enabled
        self.batch_size = batch_size

    def _format_observations(self, observations: list[dict[str, Any]]) -> str:
        """Format observations for the LLM prompt."""
        lines = []
        for obs in observations:
            line = f"[{obs.get('event_type')}"
            if obs.get("tool_name"):
                line += f" → {obs['tool_name']}"
            line += "]"

            if obs.get("file_path"):
                line += f" {obs['file_path']}"

            content = obs.get("tool_output") or obs.get("error") or obs.get("prompt") or ""
            if content:
                # Truncate long content
                content = content[:500] + "..." if len(content) > 500 else content
                line += f": {content}"

            lines.append(line)

        return "\n".join(lines)

    async def compress(self, observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Compress observations into a summary.

        Args:
            observations: List of observation dictionaries.

        Returns:
            Dictionary with 'summary' and 'keywords', or None if disabled/failed.
        """
        if not self.enabled:
            return None

        if len(observations) < 5:
            logger.debug("Too few observations to compress")
            return None

        try:
            formatted = self._format_observations(observations)
            prompt = COMPRESSION_PROMPT.format(observations=formatted)

            response = await self.client.chat(  # type: ignore[union-attr]
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a helpful coding session summarizer.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            if response is None:
                return None

            summary = response.content
            keywords = self._extract_keywords(summary)

            return {
                "summary": summary,
                "keywords": keywords,
            }

        except Exception as e:
            logger.error(f"Compression failed: {e}")
            return None

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from summary using simple heuristics."""
        # File paths
        files = re.findall(
            r"[\w\-./]+\.(py|js|ts|jsx|tsx|go|rs|java|cpp|c|h|yaml|yml|json|toml|md)", text
        )

        # CamelCase / snake_case identifiers
        identifiers = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text)

        # Combine and deduplicate
        keywords = list(set(files + [i for i in identifiers if len(i) > 3]))

        return keywords[:20]
