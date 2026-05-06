"""Heuristic structuring as fallback when AI is unavailable.

Location: mneme/core/heuristic_structuring.py

This module extracts structured observations from raw tool calls using
rule-based analysis. It's designed to be fast, deterministic, and produce
high-quality results comparable to AI structuring for common patterns.

Architecture:
    HeuristicStructuring
    ├── structure()           -- Main entry point
    ├── _detect_type()        -- Detects observation type from tool/error/prompt
    ├── _generate_title()     -- Generates human-readable title
    ├── _generate_subtitle()  -- Generates subtitle/summary
    ├── _extract_facts()      -- Extracts key facts (up to 5)
    ├── _generate_narrative() -- Generates narrative description
    ├── _detect_concepts()    -- Detects concept tags from patterns
    ├── _extract_files_*()    -- Extracts file paths
    └── _extract_file_paths() -- Regex-based file path extraction

Related modules:
    - mneme/core/ai_provider.py         -- HybridProvider falls back to this module
    - mneme/core/prompts/json_parser.py -- ParsedObservation dataclass (same fields)
    - mneme/db/structured_store.py      -- Stores HeuristicObservation results

Tests: tests/test_ai_provider.py (TestHeuristicStructuring)
"""

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
    """Extract structured data from raw observations without AI.

    Uses multi-layer analysis:
    1. Tool-specific parsers for known tools
    2. Content analysis for type detection
    3. Smart title/subtitle generation
    4. Fact extraction with filtering
    5. Concept detection from patterns
    """

    # Tool → type mapping
    TOOL_TYPE_MAP = {
        "WriteFile": "change",
        "StrReplaceFile": "change",
        "Shell": "discovery",
        "ReadFile": "discovery",
        "Grep": "discovery",
        "Glob": "discovery",
        "Agent": "feature",
        "FetchURL": "discovery",
        "SearchWeb": "discovery",
        "browser_navigate": "discovery",
        "browser_click": "discovery",
        "browser_type": "discovery",
        "browser_snapshot": "discovery",
        "EnterPlanMode": "feature",
        "ExitPlanMode": "feature",
    }

    # Error patterns → bugfix (error present + fix in output)
    ERROR_FIX_PATTERNS = [
        r"fixed|fix|resolved|solved|corrected|patched",
        r"bug.*(?:fix|resolved)|(?:fix|resolved).*bug",
        r"error.*(?:fix|resolved)|(?:fix|resolved).*error",
        r"exception.*(?:handled|caught|fixed)",
        r"workaround|hotfix|quickfix",
    ]

    # Test result patterns
    TEST_PATTERNS = {
        "test_passed": r"PASSED|passed|\bOK\b",
        "test_failed": r"FAILED|failed|ERROR\b",
        "test_summary": r"\d+ passed|\d+ failed|\d+ error",
    }

    # Concept detectors
    CONCEPT_PATTERNS = {
        "how-it-works": [
            r"how\s+(?:it\s+)?works",
            r"mechanism|architecture|internal|implementation",
            r"understand|comprehend|grasp",
        ],
        "why-it-exists": [
            r"why|reason\s+(?:for|behind)|rationale",
            r"purpose|intent|goal|objective",
            r"design\s+(?:choice|decision)",
        ],
        "what-changed": [
            r"changed|modified|updated|replaced|migrated",
            r"refactored|restructured|rewritten",
            r"added|removed|deleted|inserted",
        ],
        "problem-solution": [
            r"problem|issue|bug|error|exception|failure",
            r"solution|fix|resolution|workaround",
            r"debug|troubleshoot|diagnose",
        ],
        "gotcha": [
            r"gotcha|pitfall|trap|unexpected|surprising",
            r"beware|caution|warning|attention",
            r"edge\s+case|corner\s+case",
        ],
        "pattern": [
            r"pattern|convention|standard|best\s+practice",
            r"idiom|approach|strategy|methodology",
            r"template|blueprint|recipe",
        ],
        "trade-off": [
            r"trade[-\s]?off|pros?\s+and\s+cons",
            r"advantage|disadvantage|benefit|drawback",
            r"vs\.?|versus|compared\s+to|alternative",
        ],
        "performance": [
            r"performance|optimization|speed|latency",
            r"slow|fast|efficient|bottleneck",
            r"cache|memoiz|lazy\s+load|batch",
        ],
        "security": [
            r"security|auth|authenticat|authoriz",
            r"encrypt|decrypt|hash|salt|token",
            r"vulnerability|exploit|sanitize|escape",
        ],
        "testing": [
            r"test|spec|assert|mock|stub",
            r"pytest|unittest|jest|mocha",
            r"coverage|regression|integration",
        ],
    }

    # File extensions we care about
    CODE_EXTENSIONS = (
        r"py|js|ts|jsx|tsx|go|rs|java|kt|scala|cpp|c|h|hpp|cs|swift|rb|php|"
        r"lua|r|m|mm|pl|pm|t|scala|clj|cljs|ex|exs|elm|hs|lhs|erl|hrl|"
        r"yaml|yml|json|toml|ini|cfg|conf|xml|sql|md|rst|txt|"
        r"dockerfile|makefile|cmake|gradle|sbt|leiningen|"
        r"html|css|scss|sass|less|vue|svelte"
    )

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

    # ------------------------------------------------------------------
    # Type detection
    # ------------------------------------------------------------------

    def _detect_type(self, obs: dict[str, Any]) -> str:
        tool = obs.get("tool_name", "")
        output = str(obs.get("tool_output", ""))
        error = str(obs.get("error", ""))
        prompt = str(obs.get("prompt", ""))

        # Error + fix in output = bugfix
        if error and any(re.search(p, output, re.I) for p in self.ERROR_FIX_PATTERNS):
            return "bugfix"

        # Error without fix pattern = discovery (we're investigating)
        if error:
            return "discovery"

        # Check prompt for intent
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ("fix", "bug", "error", "debug", "solve")):
            return "bugfix"
        if any(w in prompt_lower for w in ("add", "create", "implement", "build")):
            return "feature"
        if any(w in prompt_lower for w in ("refactor", "restructure", "clean up")):
            return "refactor"
        if any(w in prompt_lower for w in ("test", "spec", "coverage")):
            return "test"
        if any(w in prompt_lower for w in ("doc", "readme", "comment")):
            return "docs"

        # Known tool types
        if tool in self.TOOL_TYPE_MAP:
            return self.TOOL_TYPE_MAP[tool]

        # Content-based detection
        if re.search(r"test.*(?:pass|fail)|(?:pass|fail).*test", output, re.I):
            return "test"

        return "discovery"

    # ------------------------------------------------------------------
    # Title generation
    # ------------------------------------------------------------------

    def _generate_title(self, obs: dict[str, Any]) -> str:
        tool = obs.get("tool_name") or "Action"
        file_path = obs.get("file_path", "")
        prompt = obs.get("prompt", "")
        tool_input = obs.get("tool_input", "")
        output = str(obs.get("tool_output", ""))

        # File-based tools: use filename
        if file_path:
            filename = file_path.replace("\\", "/").split("/")[-1]
            return f"{tool}: {filename}"

        # Try to extract meaningful info from tool_input
        input_info = self._extract_meaningful_input(tool_input)
        if input_info:
            return f"{tool}: {self._truncate(input_info, 50)}"

        # Try prompt
        if prompt:
            clean_prompt = self._clean_text(prompt)
            if len(clean_prompt) > 5:
                return f"{tool}: {self._truncate(clean_prompt, 50)}"

        # Try output first line
        output_first = self._first_meaningful_line(output)
        if output_first and len(output_first) > 5:
            return f"{tool}: {self._truncate(output_first, 50)}"

        return tool

    def _extract_meaningful_input(self, tool_input: Any) -> str | None:
        """Extract human-readable description from tool input."""
        if not tool_input:
            return None

        # Parse JSON/dict input
        data = None
        if isinstance(tool_input, dict):
            data = tool_input
        elif isinstance(tool_input, str):
            try:
                data = json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                # Not JSON — use raw string if meaningful
                clean = self._clean_text(tool_input)
                if len(clean) > 3 and not clean.startswith("{"):
                    return clean
                return None

        if not isinstance(data, dict):
            return None

        # Priority keys for different tools
        priority_keys = [
            "command",
            "query",
            "url",
            "path",
            "search",
            "text",
            "message",
            "question",
            "description",
        ]
        for key in priority_keys:
            if key in data and data[key]:
                val = str(data[key])
                clean = self._clean_text(val)
                if len(clean) > 2:
                    return clean

        # For code-related tools, extract function/class name
        if "content" in data and data["content"]:
            content = str(data["content"])
            # Extract function/class definition
            match = re.search(r"(?:def|class|function)\s+(\w+)", content)
            if match:
                return match.group(1)
            # Extract first meaningful line
            first = self._first_meaningful_line(content)
            if first:
                return self._truncate(first, 40)

        return None

    # ------------------------------------------------------------------
    # Subtitle generation
    # ------------------------------------------------------------------

    def _generate_subtitle(self, obs: dict[str, Any]) -> str | None:
        error = obs.get("error", "")
        output = str(obs.get("tool_output", ""))
        tool_input = obs.get("tool_input", "")

        # Error takes priority
        if error:
            return self._truncate(self._clean_text(str(error)), 100)

        # For file writes — show what changed
        tool = obs.get("tool_name", "")
        if tool in ("WriteFile", "StrReplaceFile"):
            if isinstance(tool_input, dict):
                content = tool_input.get("content", "")
                if content:
                    first_line = self._first_meaningful_line(str(content))
                    if first_line:
                        return f"Added: {self._truncate(first_line, 80)}"
            old = obs.get("old_string", "")
            new = obs.get("new_string", "")
            if old and new:
                return f"Replaced: {self._truncate(old, 40)} → {self._truncate(new, 40)}"

        # For shell/test output — show summary line
        if tool == "Shell":
            summary = self._extract_shell_summary(output)
            if summary:
                return summary

        # Best meaningful line from output
        meaningful = self._first_meaningful_line(output, min_len=15)
        if meaningful:
            return self._truncate(meaningful, 100)

        return None

    def _extract_shell_summary(self, output: str) -> str | None:
        """Extract summary from shell output (tests, git, etc.)."""
        lines = output.strip().split("\n")

        # Look for test summary
        for line in reversed(lines):
            if re.search(r"\d+\s+(passed|failed|error|skipped)", line, re.I):
                return self._clean_text(line)

        # Look for git status summary
        for line in lines:
            if re.search(r"\d+\s+files?\s+changed", line, re.I):
                return self._clean_text(line)

        # Look for pip/uv install summary
        for line in reversed(lines):
            if re.search(r"installed|updated|uninstalled", line, re.I):
                return self._clean_text(line)

        return None

    # ------------------------------------------------------------------
    # Facts extraction
    # ------------------------------------------------------------------

    def _extract_facts(self, obs: dict[str, Any]) -> list[str]:
        facts = []
        error = obs.get("error", "")
        output = str(obs.get("tool_output", ""))
        tool = obs.get("tool_name", "")
        tool_input = obs.get("tool_input", "")

        # Error fact
        if error:
            clean_error = self._clean_text(str(error))
            if len(clean_error) > 5:
                facts.append(f"Error: {self._truncate(clean_error, 150)}")

        # Tool-specific facts
        if tool == "Shell":
            facts.extend(self._extract_shell_facts(output))
        elif tool in ("WriteFile", "StrReplaceFile"):
            facts.extend(self._extract_file_facts(obs))
        elif tool == "ReadFile":
            facts.extend(self._extract_readfile_facts(output))
        elif tool in ("Grep", "Glob"):
            facts.extend(self._extract_search_facts(output, tool))
        else:
            facts.extend(self._extract_generic_facts(output))

        # File paths from input
        path = self._extract_path_from_input(tool_input)
        if path and path not in [f.replace("File: ", "") for f in facts if f.startswith("File: ")]:
            facts.append(f"File: {path}")

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for f in facts:
            key = f.lower()
            if key not in seen and len(f) > 5:
                seen.add(key)
                deduped.append(f)

        return deduped[:5]  # Max 5 facts

    def _extract_shell_facts(self, output: str) -> list[str]:
        facts = []
        lines = output.strip().split("\n")

        # Test results
        test_lines = [
            line for line in lines if re.search(r"PASSED|FAILED|ERROR|skipped", line, re.I)
        ]
        for line in test_lines[:2]:
            clean = self._clean_text(line)
            if len(clean) > 5:
                facts.append(clean)

        # Summary lines
        for line in reversed(lines):
            clean = self._clean_text(line)
            if (
                re.search(r"\d+\s+(passed|failed|error|changed|inserted|deleted)", clean, re.I)
                and clean not in facts
            ):
                facts.append(clean)
                break

        # File paths in output (up to 5 files)
        files = self._extract_file_paths(output)
        for f in files[:5]:
            facts.append(f"File: {f}")

        return facts

    def _extract_file_facts(self, obs: dict[str, Any]) -> list[str]:
        facts = []
        tool_input = obs.get("tool_input", {})

        if isinstance(tool_input, dict):
            path = tool_input.get("path", "")
            if path:
                facts.append(f"Modified: {path}")

            # Detect language/framework from content
            content = tool_input.get("content", "")
            if content:
                lang = self._detect_language(content, path)
                if lang:
                    facts.append(f"Language: {lang}")

                # Count lines
                lines = content.count("\n") + 1
                facts.append(f"Lines: {lines}")

        return facts

    def _extract_readfile_facts(self, output: str) -> list[str]:
        facts = []
        lines = output.strip().split("\n")

        # Extract imports/includes
        for line in lines[:20]:
            if re.match(r"^(import|from|require|include|using|#include)", line.strip()):
                clean = self._clean_text(line)
                if len(clean) > 5:
                    facts.append(f"Import: {self._truncate(clean, 80)}")
                    if len(facts) >= 2:
                        break

        # Extract function/class/struct definitions (skip #define macros)
        for line in lines[:30]:
            # Skip preprocessor directives (#define, #ifdef, etc.)
            if re.match(r"^\s*#", line):
                continue
            match = re.search(r"(?:def|class|function|interface|struct)\s+(\w+)", line)
            if match:
                facts.append(f"Defined: {match.group(1)}()")
                if len(facts) >= 3:
                    break

        return facts

    def _extract_search_facts(self, output: str, tool: str) -> list[str]:
        facts = []
        lines = output.strip().split("\n")

        # Count results
        non_empty = [line for line in lines if line.strip()]
        if non_empty:
            facts.append(f"{tool}: {len(non_empty)} results")

        # First few file paths
        files = self._extract_file_paths(output)
        for f in files[:2]:
            facts.append(f"Found in: {f}")

        return facts

    def _extract_generic_facts(self, output: str) -> list[str]:
        facts = []
        lines = output.strip().split("\n")

        # Key lines (not indented, not empty, reasonable length)
        for line in lines:
            stripped = line.strip()
            if (
                len(stripped) > 15
                and len(stripped) < 200
                and not stripped.startswith(" ")
                and not stripped.startswith("#")
                and not stripped.startswith("-")
            ):
                clean = self._clean_text(stripped)
                if clean and clean not in facts:
                    facts.append(clean)
                if len(facts) >= 3:
                    break

        # File paths
        files = self._extract_file_paths(output)
        for f in files[:2]:
            facts.append(f"File: {f}")

        return facts

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def _generate_narrative(self, obs: dict[str, Any]) -> str | None:
        tool = obs.get("tool_name", "")
        file_path = obs.get("file_path", "")
        error = obs.get("error", "")
        tool_input = obs.get("tool_input", "")
        output = str(obs.get("tool_output", ""))
        prompt = str(obs.get("prompt", ""))

        parts = []

        # Action description
        action = self._describe_action(tool, tool_input, prompt)
        if action:
            parts.append(action)

        # File context
        if file_path:
            parts.append(f"on `{file_path}`")

        # Error or result
        if error:
            clean_error = self._clean_text(str(error))
            parts.append(f"→ Error: {self._truncate(clean_error, 100)}")
        else:
            result = self._describe_result(tool, output, tool_input)
            if result:
                parts.append(f"→ {result}")

        return " ".join(parts) if parts else None

    def _describe_action(self, tool: str, tool_input: Any, prompt: str) -> str | None:
        """Generate human-readable action description."""
        if prompt:
            clean = self._clean_text(prompt)
            if len(clean) > 5:
                return self._truncate(clean, 60)

        tool_descriptions = {
            "WriteFile": "Created file",
            "StrReplaceFile": "Modified file",
            "ReadFile": "Read file",
            "Shell": "Executed command",
            "Grep": "Searched code",
            "Glob": "Listed files",
            "Agent": "Delegated task",
            "FetchURL": "Fetched URL",
            "SearchWeb": "Searched web",
        }

        desc = tool_descriptions.get(tool, f"Used {tool}")

        # Add input detail
        input_info = self._extract_meaningful_input(tool_input)
        if input_info:
            return f"{desc}: {self._truncate(input_info, 50)}"

        return desc

    def _describe_result(self, tool: str, output: str, tool_input: Any) -> str | None:
        """Generate human-readable result description."""
        if not output or not output.strip():
            return "No output"

        if tool == "Shell":
            summary = self._extract_shell_summary(output)
            if summary:
                return summary
            return f"Output: {self._truncate(self._first_meaningful_line(output) or output, 80)}"

        if tool in ("WriteFile", "StrReplaceFile"):
            if isinstance(tool_input, dict):
                content = tool_input.get("content", "")
                if content:
                    lines = content.count("\n") + 1
                    return f"Wrote {lines} lines"
            return "File updated"

        if tool == "ReadFile":
            lines = output.count("\n") + 1
            return f"Read {lines} lines"

        if tool in ("Grep", "Glob"):
            count = len([line for line in output.split("\n") if line.strip()])
            return f"Found {count} matches"

        # Generic
        first = self._first_meaningful_line(output)
        if first:
            return self._truncate(first, 100)

        return self._truncate(output.strip(), 100)

    # ------------------------------------------------------------------
    # Concept detection
    # ------------------------------------------------------------------

    def _detect_concepts(self, obs: dict[str, Any]) -> list[str]:
        text = " ".join(
            filter(
                None,
                [
                    str(obs.get("tool_output", "")),
                    str(obs.get("error", "")),
                    str(obs.get("prompt", "")),
                    str(obs.get("tool_input", "")),
                ],
            )
        ).lower()

        concepts = []
        for concept, patterns in self.CONCEPT_PATTERNS.items():
            if any(re.search(p, text) for p in patterns):
                concepts.append(concept)

        return concepts

    # ------------------------------------------------------------------
    # File extraction
    # ------------------------------------------------------------------

    def _extract_files_read(self, obs: dict[str, Any]) -> list[str]:
        files = []
        if obs.get("tool_name") == "ReadFile":
            path = self._extract_path_from_input(obs.get("tool_input", {}))
            if path:
                files.append(path)
        if obs.get("file_path"):
            files.append(obs["file_path"])
        return list(set(files))

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
            for key in ["path", "file_path", "filename", "dest", "source", "target"]:
                if key in tool_input and isinstance(tool_input[key], str):
                    return tool_input[key]
        elif isinstance(tool_input, str):
            try:
                data = json.loads(tool_input)
                return HeuristicStructuring._extract_path_from_input(data)
            except json.JSONDecodeError:
                pass
        return None

    # Special filenames without extensions (Makefile, Dockerfile, etc.)
    SPECIAL_FILENAMES = (
        r"Makefile|makefile|CMakeLists\.txt|Dockerfile|dockerfile|"
        r"\.dockerignore|\.gitignore|\.env|\.editorconfig|"
        r"README|LICENSE|CHANGELOG|CONTRIBUTING|CODE_OF_CONDUCT"
    )

    def _extract_file_paths(self, text: str) -> list[str]:
        """Extract file paths from text.

        Handles:
        - Regular paths: src/main.c, include/header.h
        - Git diff paths: a/src/main.c, b/src/main.c (deduplicated)
        - Git status: modified:   src/main.c
        - Special files: Makefile, Dockerfile, CMakeLists.txt
        - Various whitespace formats
        """
        # Match file paths with code extensions
        matches = re.findall(
            r"[\w\-./\\]+\.(?:" + self.CODE_EXTENSIONS + r")\b",
            text,
        )
        # Match special filenames without extensions
        special_matches = re.findall(
            r"(?:[\w\-./\\]+/)?(?:" + self.SPECIAL_FILENAMES + r")\b",
            text,
        )
        matches.extend(special_matches)

        seen = set()
        result = []
        for m in matches:
            clean = m.replace("\\", "/").strip("./")
            # Skip git diff prefixes (a/ and b/)
            if clean.startswith("a/") or clean.startswith("b/"):
                clean = clean[2:]
            # Skip duplicates
            if clean and clean not in seen and len(clean) > 2:
                seen.add(clean)
                result.append(clean)
        return result

    def _detect_language(self, content: str, path: str = "") -> str | None:
        """Detect programming language from content or path."""
        ext_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".jsx": "React JSX",
            ".tsx": "React TSX",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".cpp": "C++",
            ".c": "C",
            ".cs": "C#",
            ".rb": "Ruby",
            ".php": "PHP",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
            ".html": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".sql": "SQL",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".json": "JSON",
            ".toml": "TOML",
            ".md": "Markdown",
            ".dockerfile": "Dockerfile",
        }

        if path:
            for ext, lang in ext_map.items():
                if path.lower().endswith(ext):
                    return lang

        # Content-based detection
        if re.search(r"^\s*import\s+\w+|^\s*from\s+\w+\s+import", content, re.M) and (
            "typing" in content or "__init__" in content or "def " in content
        ):
            return "Python"
        if re.search(r"^\s*function\s+\w+|^\s*const\s+\w+\s*=|^\s*let\s+\w+", content, re.M):
            if ":" in content.split("\n")[0] if content else False:
                return "TypeScript"
            return "JavaScript"
        if re.search(r"^\s*package\s+\w+|^\s*func\s+\w+", content, re.M):
            return "Go"
        if re.search(r"^\s*fn\s+\w+|^\s*let\s+\w+.*=|^\s*use\s+\w+", content, re.M):
            return "Rust"

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean text for human readability."""
        if not text:
            return ""
        # Replace newlines/tabs with spaces
        text = text.replace("\n", " ").replace("\t", " ")
        # Remove excessive whitespace
        text = " ".join(text.split())
        # Remove JSON artifacts
        text = re.sub(r"^\{\s*", "", text)
        text = re.sub(r"\s*\}$", "", text)
        # Remove common wrapper text
        text = re.sub(r"^(Used|with input|with result|encountered error):\s*", "", text, flags=re.I)
        return text.strip()

    @staticmethod
    def _first_meaningful_line(text: str, min_len: int = 10) -> str | None:
        """Get first non-empty, meaningful line."""
        if not text:
            return None
        for line in text.split("\n"):
            stripped = line.strip()
            if len(stripped) >= min_len and not stripped.startswith(("#", "//", "--", "/*", "*")):
                return stripped
        return None

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if not text:
            return ""
        text = " ".join(text.split())
        return text[:max_len] + "..." if len(text) > max_len else text
