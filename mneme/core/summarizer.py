"""Fast local session summarizer — no AI needed."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from mneme.db.store import ObservationStore


class FastSummarizer:
    """Generate quick session summaries from observations."""

    # Module-level cache: {cwd: (timestamp, result)}
    _cache: dict[str, tuple[float, str | None]] = {}
    _cache_ttl_seconds: float = 300  # 5 minutes

    def __init__(self, store: ObservationStore | None = None) -> None:
        self.store = store if store is not None else ObservationStore()

    def get_project_brief(
        self, cwd: str, max_sessions: int = 3, current_session_id: str | None = None
    ) -> str | None:
        import time

        # Check cache
        now = time.time()
        cached = FastSummarizer._cache.get(cwd)
        if cached and (now - cached[0]) < FastSummarizer._cache_ttl_seconds:
            return cached[1]

        result = self._build_project_brief(cwd, max_sessions, current_session_id)
        FastSummarizer._cache[cwd] = (now, result)
        return result

    def _build_project_brief(
        self, cwd: str, max_sessions: int = 3, current_session_id: str | None = None
    ) -> str | None:
        """Get a brief summary of recent project activity.

        Args:
            cwd: Current working directory.
            max_sessions: Maximum number of past sessions to include.
            current_session_id: ID of the current session to exclude.

        Returns:
            Formatted markdown string or None if no relevant history.
        """
        # Get more sessions than needed since many may have no observations
        sessions = self.store.get_sessions_for_project(cwd, limit=max_sessions * 10)
        if not sessions:
            return None

        # Filter out sessions with no observations and current session
        sessions_with_obs = []
        for s in sessions:
            if current_session_id and s["id"] == current_session_id:
                continue
            obs = self.store.get_observations_for_session(s["id"], limit=1)
            if obs:
                sessions_with_obs.append(s)

        sessions = sorted(
            sessions_with_obs,
            key=lambda s: s.get("started_at", ""),
            reverse=True,
        )[:max_sessions]

        lines = ["## 📋 Что мы делали ранее"]
        lines.append("")

        for session in sessions:
            session_brief = self._summarize_session(session)
            if session_brief:
                lines.append(session_brief)
                lines.append("")

        if len(lines) <= 2:
            return None

        lines.append("---")
        return "\n".join(lines)

    def _summarize_session(self, session: dict[str, Any]) -> str | None:
        """Summarize a single session into 2-3 lines."""
        session_id = session["id"]
        started = session.get("started_at", "")

        # Get observations (don't trust observation_count, fetch directly)
        observations = self.store.get_observations_for_session(session_id, limit=50)
        if not observations:
            return None

        obs_count = len(observations)

        # Extract user prompts
        prompts = []
        for obs in observations:
            p = obs.get("prompt")
            if p and len(p) > 3:
                prompts.append(p)

        # Extract tools used
        tools = Counter()
        files_read = set()
        files_written = set()
        errors = []

        for obs in observations:
            tool = obs.get("tool_name")
            if tool and tool != "None":
                tools[tool] += 1

            fp = obs.get("file_path")
            if fp:
                files_read.add(fp)

            # Detect writes via tool input
            inp = obs.get("tool_input", "")
            if (
                inp
                and "WriteFile" in str(obs.get("event_type", ""))
                or inp
                and "StrReplaceFile" in str(obs.get("event_type", ""))
            ):
                try:
                    data = json.loads(inp) if isinstance(inp, str) else inp
                    path = data.get("path", "")
                    if path:
                        files_written.add(path)
                except Exception:
                    pass

            err = obs.get("error")
            if err:
                errors.append(err[:100])

        # Format time
        time_str = ""
        if started:
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                time_str = dt.strftime("%d.%m %H:%M")
            except Exception:
                time_str = started[:16]

        # Build summary
        parts = []

        # Key user prompts (most informative)
        if prompts:
            # Filter to meaningful prompts
            meaningful = [
                p
                for p in prompts
                if len(p) > 10 and not p.startswith("/") and not p.startswith("!")
            ]
            if meaningful:
                # Take last 2-3 prompts as they represent latest intent
                latest = meaningful[-3:]
                for p in latest:
                    # Truncate long prompts
                    short = p[:120] + "..." if len(p) > 120 else p
                    parts.append(f"• **Запрос:** {short}")

        # Tools used (if no good prompts)
        if not parts and tools:
            top_tools = tools.most_common(5)
            tool_str = ", ".join(f"{t}({c})" for t, c in top_tools)
            parts.append(f"• Инструменты: {tool_str}")

        # Files modified
        if files_written:
            modified = sorted(files_written)[-5:]  # Last 5 modified
            file_str = ", ".join("`{}`".format(f.split("/")[-1].split("\\")[-1]) for f in modified)
            parts.append(f"• **Изменено:** {file_str}")

        # Errors (brief)
        if errors:
            unique_errors = list(dict.fromkeys(errors))[:2]
            for e in unique_errors:
                parts.append(f"• ⚠️ Ошибка: {e}")

        if not parts:
            return None

        header = f"**Сессия** ({time_str}) — {obs_count} действий"
        return header + "\n" + "\n".join(parts)

    def get_quick_facts(self, cwd: str) -> list[str]:
        """Get quick facts about the project — files, patterns, decisions."""
        facts = []

        # Recent files modified
        sessions = self.store.get_sessions_for_project(cwd, limit=5)
        all_files = set()
        for s in sessions:
            obs = self.store.get_observations_for_session(s["id"], limit=20)
            for o in obs:
                fp = o.get("file_path")
                if fp:
                    all_files.add(fp)

        if all_files:
            recent = sorted(all_files)[-8:]
            facts.append(
                "Недавние файлы: {}".format(
                    ", ".join("`{}`".format(f.split("/")[-1].split("\\")[-1]) for f in recent)
                )
            )

        return facts
