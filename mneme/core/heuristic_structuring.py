"""Heuristic structuring as fallback when AI is unavailable."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class HeuristicObservation:
    """Structured observation from heuristic analysis."""

    type: str
    title: str
    subtitle: str | None
    facts: list[str]
    narrative: str | None
    concepts: list[str]
    files_read: list[str]
    files_modified: list[str]


class HeuristicStructuring:
    """Extract structured data from raw observations without AI."""

    # Tool → type mapping
    TOOL_TYPE_MAP = {
        "WriteFile": "change",
        "StrReplaceFile": "change",
        "Shell": "discovery",
        "ReadFile": "discovery",
        "Grep": "discovery",
        "Glob": "discovery",
        "Agent": "feature",
    }

    # Error patterns → bugfix
    ERROR_FIX_PATTERNS = [
        r"fixed|fix|resolved|solved|corrected",
        r"bug|error|exception|failure|crash",
        r"patch|workaround|hotfix",
    ]

    # Concept detectors
    CONCEPT_PATTERNS = {
        "how-it-works": [r"how.*works|mechanism|architecture|internal"],
        "why-it-exists": [r"why|reason|rationale|purpose|design.*choice"],
        "what-changed": [r"changed|modified|updated|replaced|migrated"],
        "problem-solution": [r"problem|issue|bug.*fix|solution.*error"],
        "gotcha": [r"gotcha|pitfall|trap|unexpected|beware|caution"],
        "pattern": [r"pattern|convention|standard|best.*practice"],
        "trade-off": [r"trade.*off|pros?\s+and\s+cons|advantage|disadvantage|vs\.?"],
    }

    def structure(self, observation: dict[str, Any]) -> HeuristicObservation:
        """Convert raw observation to structured."""
        return HeuristicObservation(
            type=self._detect_type(observation),
            title=self._generate_title(observation),
            subtitle=self._generate_subtitle(observation),
            facts=self._extract_facts(observation),
            narrative=self._generate_narrative(observation),
            concepts=self._detect_concepts(observation),
            files_read=self._extract_files_read(observation),
            files_modified=self._extract_files_modified(observation),
        )

    def _detect_type(self, obs: dict[str, Any]) -> str:
        tool = obs.get("tool_name", "")
        output = str(obs.get("tool_output", ""))
        error = str(obs.get("error", ""))

        # Error + fix in output = bugfix
        if error and any(re.search(p, output, re.I) for p in self.ERROR_FIX_PATTERNS):
            return "bugfix"

        # Error without fix = discovery
        if error:
            return "discovery"

        # Known tool types
        if tool in self.TOOL_TYPE_MAP:
            return self.TOOL_TYPE_MAP[tool]

        return "discovery"

    def _generate_title(self, obs: dict[str, Any]) -> str:
        tool = obs.get("tool_name", "Unknown")
        file_path = obs.get("file_path", "")
        prompt = obs.get("prompt", "")

        if file_path:
            filename = file_path.replace("\\", "/").split("/")[-1]
            return f"{tool}: {filename}"

        if prompt:
            return f"{tool}: {self._truncate(prompt, 40)}"

        return tool

    def _generate_subtitle(self, obs: dict[str, Any]) -> str | None:
        error = obs.get("error", "")
        if error:
            return self._truncate(error, 80)

        output = str(obs.get("tool_output", ""))
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        if lines:
            return self._truncate(lines[0], 80)

        return None

    def _extract_facts(self, obs: dict[str, Any]) -> list[str]:
        facts = []
        error = obs.get("error", "")
        output = str(obs.get("tool_output", ""))

        if error:
            facts.append(f"Error: {self._truncate(error, 100)}")

        # Extract key lines from output
        lines = [l.strip() for l in output.split("\n") if l.strip() and not l.startswith(" ")]
        for line in lines[:3]:
            if len(line) > 10:
                facts.append(self._truncate(line, 120))

        # Extract file paths mentioned
        files = re.findall(
            r"[\w\-./]+\.(py|js|ts|go|rs|java|cpp|c|h|yaml|yml|json|toml|md)",
            output,
        )
        for f in set(files[:3]):
            facts.append(f"File: {f}")

        return facts

    def _generate_narrative(self, obs: dict[str, Any]) -> str | None:
        tool = obs.get("tool_name", "")
        file_path = obs.get("file_path", "")
        error = obs.get("error", "")

        parts = []
        if tool:
            parts.append(f"Used {tool}")
        if file_path:
            parts.append(f"on {file_path}")
        if error:
            parts.append(f"encountered error: {self._truncate(error, 50)}")
        else:
            output = str(obs.get("tool_output", ""))
            if output:
                parts.append(f"with result: {self._truncate(output, 50)}")

        return " ".join(parts) if parts else None

    def _detect_concepts(self, obs: dict[str, Any]) -> list[str]:
        text = " ".join(
            filter(
                None,
                [
                    str(obs.get("tool_output", "")),
                    str(obs.get("error", "")),
                    str(obs.get("prompt", "")),
                ],
            )
        ).lower()

        concepts = []
        for concept, patterns in self.CONCEPT_PATTERNS.items():
            if any(re.search(p, text) for p in patterns):
                concepts.append(concept)

        return concepts

    def _extract_files_read(self, obs: dict[str, Any]) -> list[str]:
        files = []
        if obs.get("tool_name") == "ReadFile":
            path = self._extract_path_from_input(obs.get("tool_input", {}))
            if path:
                files.append(path)
        return files

    def _extract_files_modified(self, obs: dict[str, Any]) -> list[str]:
        files = []
        tool = obs.get("tool_name", "")
        if tool in ("WriteFile", "StrReplaceFile"):
            path = self._extract_path_from_input(obs.get("tool_input", {}))
            if path:
                files.append(path)
        if obs.get("file_path"):
            files.append(obs["file_path"])
        return list(set(files))

    @staticmethod
    def _extract_path_from_input(tool_input: Any) -> str | None:
        if isinstance(tool_input, dict):
            for key in ["path", "file_path", "filename", "dest", "source"]:
                if key in tool_input and isinstance(tool_input[key], str):
                    return tool_input[key]
        elif isinstance(tool_input, str):
            try:
                data = json.loads(tool_input)
                return HeuristicStructuring._extract_path_from_input(data)
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if not text:
            return ""
        text = " ".join(text.split())
        return text[:max_len] + "..." if len(text) > max_len else text
