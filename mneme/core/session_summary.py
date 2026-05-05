"""AI-powered structured session summary generation."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger

from mneme.config import load_config
from mneme.core.ai_provider import ConfigurableAIProvider
from mneme.core.llm_client import LLMMessage

SESSION_SUMMARY_PROMPT = """You are a coding session analyst. Analyze the following session observations and produce a structured summary in Russian language.

Format your response EXACTLY as JSON with these fields:
- "title": A concise 1-sentence summary of what the session was about (max 120 chars)
- "request": What the user asked for or what the session goal was
- "investigated": What was researched, explored, or investigated during the session (2-4 sentences)
- "learned": What new information was discovered or what knowledge was gained (2-4 sentences)
- "completed": What was accomplished, built, or completed (2-4 sentences)
- "next_steps": What remains to be done or what the next steps should be (1-3 sentences)
- "files_read": List of files that were read (array of strings, just filenames)
- "files_edited": List of files that were modified or created (array of strings, just filenames)
- "notes": Any additional notes or observations (optional, 1-2 sentences)

Rules:
- Write in Russian language
- Be specific and factual, not vague
- Mention concrete files, tools, and decisions
- If a section has no relevant content, use an empty string or empty array
- Keep each text field under 300 characters
- The title should be informative, not generic

Session Observations:
{observations}

Respond ONLY with valid JSON. No markdown, no explanations."""


class SessionSummaryGenerator:
    """Generate structured session summaries using configured LLM provider."""

    def __init__(self) -> None:
        config = load_config()
        llm_cfg = config.get("llm", {})

        self.provider = ConfigurableAIProvider(
            provider=llm_cfg.get("provider", "kimi"),
            model=llm_cfg.get("model"),
            base_url=llm_cfg.get("base_url"),
            api_key=llm_cfg.get("api_key"),
            timeout=llm_cfg.get("timeout", 60.0),
            enabled=True,
        )
        self.enabled = self.provider.enabled

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
                content = content[:400] + "..." if len(content) > 400 else content
                line += f": {content}"

            lines.append(line)

        return "\n".join(lines)

    def generate(self, observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Generate a structured session summary.

        Args:
            observations: List of observation dictionaries.

        Returns:
            Dictionary with structured summary fields, or None if disabled/failed.
        """
        if not self.enabled:
            logger.debug("Session summary generation disabled")
            return None

        if len(observations) < 3:
            logger.debug("Too few observations to generate summary")
            return None

        try:
            formatted = self._format_observations(observations)
            prompt = SESSION_SUMMARY_PROMPT.format(observations=formatted)

            if self.provider.client is None:
                return None

            # Run async chat call synchronously
            response = asyncio.run(
                self.provider.client.chat(
                    messages=[
                        LLMMessage(
                            role="system",
                            content="You are a precise coding session analyst. Always respond with valid JSON only.",
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                )
            )

            if response is None:
                return None

            return self._parse_summary(response.content)

        except Exception as e:
            logger.error(f"Session summary generation failed: {e}")
            return None

    def _parse_summary(self, content: str) -> dict[str, Any] | None:
        """Parse LLM response into structured summary."""
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)

        # Try to find raw JSON object
        if not content.strip().startswith("{"):
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse summary JSON: {e}")
            # Fallback: treat entire response as raw summary
            return {
                "title": "Сессия",
                "request": "",
                "investigated": "",
                "learned": "",
                "completed": content[:500],
                "next_steps": "",
                "files_read": [],
                "files_edited": [],
                "notes": "",
                "raw_summary": content,
            }

        # Normalize fields
        return {
            "title": str(parsed.get("title", "Сессия"))[:120],
            "request": str(parsed.get("request", ""))[:500],
            "investigated": str(parsed.get("investigated", ""))[:500],
            "learned": str(parsed.get("learned", ""))[:500],
            "completed": str(parsed.get("completed", ""))[:500],
            "next_steps": str(parsed.get("next_steps", ""))[:500],
            "files_read": (
                parsed.get("files_read", []) if isinstance(parsed.get("files_read"), list) else []
            ),
            "files_edited": (
                parsed.get("files_edited", [])
                if isinstance(parsed.get("files_edited"), list)
                else []
            ),
            "notes": str(parsed.get("notes", ""))[:500],
            "raw_summary": content,
        }
