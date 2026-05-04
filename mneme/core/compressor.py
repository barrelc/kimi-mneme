"""AI-powered compression of observations into semantic summaries."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from mneme.core.ai_provider import _load_kimi_token

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
    """Compress observations into semantic summaries using Kimi API."""

    def __init__(self) -> None:
        self.token = _load_kimi_token()
        self.enabled = bool(self.token)
        self.model = "kimi-k2.5"
        self.batch_size = 50

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

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.kimi.com/coding/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a helpful coding session summarizer.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1000,
                    },
                )
                response.raise_for_status()
                data = response.json()

            summary = data["choices"][0]["message"]["content"]
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
        import re

        # File paths
        files = re.findall(
            r"[\w\-./]+\.(py|js|ts|jsx|tsx|go|rs|java|cpp|c|h|yaml|yml|json|toml|md)", text
        )

        # CamelCase / snake_case identifiers
        identifiers = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text)

        # Combine and deduplicate
        keywords = list(set(files + [i for i in identifiers if len(i) > 3]))

        return keywords[:20]
