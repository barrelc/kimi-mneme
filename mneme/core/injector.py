"""Context injection for new sessions."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from mneme.config import load_config
from mneme.db.store import ObservationStore
from mneme.db.structured_store import StructuredObservationStore
from mneme.db.vector import SQLiteVecStore, VectorStore


class Injector:
    """Inject relevant past context into new sessions."""

    def __init__(
        self, store: ObservationStore | None = None, use_vector: bool | None = None
    ) -> None:
        config = load_config()
        self.enabled = config["injection"]["enabled"]
        self.max_tokens = config["injection"]["max_tokens"]
        self.min_relevance = config["injection"]["min_relevance"]
        self.max_results = config["injection"]["max_results"]
        self.recency_boost_days = config["injection"]["recency_boost_days"]
        self.format = config["injection"]["format"]
        self.use_vector = (
            use_vector if use_vector is not None else config["injection"].get("use_vector", False)
        )
        self.store = store if store is not None else ObservationStore()
        self.structured_store = StructuredObservationStore()
        self.vector_store = VectorStore()
        self.sqlite_vec = SQLiteVecStore()

    def get_context(self, cwd: str, current_session_id: str | None = None) -> str | None:
        """Get relevant context for a new session.

        Args:
            cwd: Current working directory (project context).
            current_session_id: ID of current session to exclude.

        Returns:
            Formatted context string or None if disabled/no results.
        """
        if not self.enabled:
            return None

        try:
            context_parts = []
            total_tokens = 0
            max_tokens = self.max_tokens

            # 1. Inject cross-session patterns (errors, fixes, decisions)
            patterns = self._get_relevant_patterns(cwd)
            if patterns:
                patterns_context = self._format_patterns(patterns)
                context_parts.append(patterns_context)
                total_tokens += self._estimate_tokens(patterns_context)

            # 2. Get recent sessions for this project
            project_sessions = self.store.get_sessions_for_project(
                cwd=cwd,
                limit=20,
                recency_days=self.recency_boost_days,
            )

            if not project_sessions:
                # Fall back to any recent sessions within recency window
                project_sessions = self.store.get_sessions(limit=self.max_results)

            # Exclude current session
            if current_session_id:
                project_sessions = [s for s in project_sessions if s["id"] != current_session_id]

            if project_sessions:
                # Rank sessions by relevance
                ranked_sessions = self._rank_sessions(project_sessions, cwd)

                # Also try semantic search via sqlite-vec (B.5)
                if self.use_vector:
                    semantic_results = self._semantic_search_project(cwd)
                    if semantic_results:
                        # Merge semantic results, avoiding duplicates
                        existing_ids = {s["id"] for s in ranked_sessions}
                        for sr in semantic_results:
                            if sr["id"] not in existing_ids:
                                ranked_sessions.append(sr)

                # Get structured observations from top sessions
                for session in ranked_sessions[: self.max_results]:
                    session_id = session["id"]
                    # Try structured observations first (AI-structured)
                    structured = self.structured_store.get_by_session(session_id, limit=3)
                    if structured:
                        session_context = self._format_structured_session(session, structured)
                    else:
                        # Fallback to raw observations
                        observations = self.store.get_observations_for_session(session_id, limit=3)
                        if not observations:
                            continue
                        session_context = self._format_session(session, observations)

                    session_tokens = self._estimate_tokens(session_context)

                    if total_tokens + session_tokens > max_tokens:
                        break

                    context_parts.append(session_context)
                    total_tokens += session_tokens

            # Also inject recent structured observations for this project directly
            project_name = os.path.basename(cwd.rstrip("/\\"))
            project_structured = self.structured_store.get_for_injection(
                project=project_name, limit=5
            )
            if project_structured:
                structured_context = self._format_project_structured(project_structured)
                structured_tokens = self._estimate_tokens(structured_context)
                if total_tokens + structured_tokens <= max_tokens:
                    context_parts.insert(0, structured_context)
                    total_tokens += structured_tokens

            if not context_parts:
                return None

            return self._wrap_context(context_parts)

        except Exception as e:
            logger.error(f"Context injection failed: {e}")
            return None

    def _get_relevant_patterns(self, cwd: str) -> list[dict[str, Any]]:
        """Get patterns relevant to the current project."""
        try:
            # Get patterns for this project
            project_patterns = self.store.get_patterns_for_project(cwd, limit=5)

            # Also get high-occurrence global patterns
            global_patterns = self.store.find_patterns(
                min_occurrences=2,
                limit=5,
            )

            # Merge, deduplicate by hash
            seen_hashes = set()
            combined = []
            for p in project_patterns + global_patterns:
                h = p.get("pattern_hash")
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    combined.append(p)

            return combined[:5]
        except Exception as e:
            logger.debug(f"Pattern retrieval failed: {e}")
            return []

    def _format_patterns(self, patterns: list[dict[str, Any]]) -> str:
        """Format patterns for injection."""
        lines = ["## 🔁 Recurring Patterns"]

        for p in patterns:
            ptype = p.get("pattern_type", "unknown")
            title = p.get("title", "Untitled")
            desc = p.get("description", "")
            count = p.get("occurrence_count", 1)

            emoji = {
                "error": "❌",
                "fix": "✅",
                "decision": "📝",
                "preference": "⚙️",
                "architecture": "🏗️",
            }.get(ptype, "•")
            lines.append(f"{emoji} **{title}** ({count}×)")
            if desc:
                lines.append(f"   {desc[:150]}")

        return "\n".join(lines)

    def _semantic_search_project(self, cwd: str) -> list[dict[str, Any]]:
        """Find semantically relevant structured observations via sqlite-vec (B.5).

        Uses the project name as query to find the most relevant past
        structured observations for proactive context injection.
        """
        try:
            import os

            project_name = os.path.basename(cwd.rstrip("/\\"))
            query = f"{project_name} project development"

            # Search sqlite-vec for semantic matches
            results = self.sqlite_vec.search_with_content(
                query=query,
                project=project_name,
                limit=5,
            )

            if not results:
                return []

            # Convert to session-like objects for merging with ranked_sessions
            sessions = []
            seen_ids = set()
            for r in results:
                obs = r.get("observation", {})
                session_id = obs.get("session_id")
                if not session_id or session_id in seen_ids:
                    continue
                seen_ids.add(session_id)

                # Fetch session data
                all_sessions = self.store.get_sessions(limit=100)
                session_map = {s["id"]: s for s in all_sessions}

                if session_id in session_map:
                    session = session_map[session_id]
                    session["_relevance_score"] = 1.0 - (r.get("distance", 0.5) * 0.5)
                    session["_semantic_match"] = {
                        "field": r.get("matched_field", "unknown"),
                        "title": obs.get("title", ""),
                    }
                    sessions.append(session)

            return sessions
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
            return []

    def _vector_search_sessions(self, cwd: str) -> list[dict[str, Any]]:
        """Find semantically similar sessions via vector search (legacy Chroma fallback).

        Searches for sessions related to the current project context.
        """
        try:
            import os

            project_name = os.path.basename(cwd.rstrip("/\\"))
            query = f"project {project_name} coding session"

            vector_results = self.vector_store.search(query, limit=10)
            if not vector_results:
                return []

            session_ids = list({vr["session_id"] for vr in vector_results if vr.get("session_id")})

            if not session_ids:
                return []

            all_sessions = self.store.get_sessions(limit=100)
            session_map = {s["id"]: s for s in all_sessions}

            results = []
            for sid in session_ids:
                if sid in session_map:
                    session = session_map[sid]
                    session["_relevance_score"] = 0.6
                    results.append(session)

            return results
        except Exception as e:
            logger.debug(f"Vector session search failed: {e}")
            return []

    def _rank_sessions(self, sessions: list[dict[str, Any]], cwd: str) -> list[dict[str, Any]]:
        """Rank sessions by relevance to current project.

        Scoring:
        - Exact CWD match: +1.0
        - Same project name: +0.8
        - Parent path match: +0.5
        - Recent sessions get small boost
        - Sessions with more observations get small boost
        """

        project_name = os.path.basename(cwd.rstrip("/\\"))
        parent_dir = os.path.dirname(cwd)
        now = datetime.now(timezone.utc)

        scored = []
        for session in sessions:
            score = 0.0
            session_cwd = session.get("cwd", "")
            session_name = os.path.basename(session_cwd.rstrip("/\\"))

            # Path matching
            if session_cwd == cwd:
                score += 1.0
            elif session_name == project_name:
                score += 0.8
            elif parent_dir and session_cwd.startswith(parent_dir):
                score += 0.5
            elif cwd in session_cwd or session_cwd in cwd:
                score += 0.3

            # Observation count boost (more activity = more relevant)
            obs_count = session.get("observation_count", 0)
            score += min(obs_count / 100, 0.2)  # Max 0.2 boost

            # Recency boost (exponential decay)
            started_at = session.get("started_at")
            if started_at:
                try:
                    # Parse SQLite timestamp
                    if isinstance(started_at, str):
                        session_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    else:
                        session_time = started_at
                    days_old = (now - session_time).total_seconds() / 86400
                    recency_score = max(0, 1.0 - (days_old / self.recency_boost_days))
                    score += recency_score * 0.3  # Max 0.3 boost
                except Exception:
                    pass

            session["_relevance_score"] = score
            scored.append(session)

        # Sort by score descending
        scored.sort(key=lambda s: s["_relevance_score"], reverse=True)

        # Filter by min_relevance AND exact project match
        # Only include sessions from the same project (exact CWD or same project name)
        filtered = [
            s for s in scored
            if s["_relevance_score"] >= self.min_relevance
            and (
                s.get("cwd", "") == cwd
                or os.path.basename(s.get("cwd", "").rstrip("/\\")) == project_name
            )
        ]

        # If filtering leaves nothing, return top results anyway
        return filtered if filtered else scored[: self.max_results]

    def _format_session(self, session: dict[str, Any], observations: list[dict[str, Any]]) -> str:
        """Format a session and its raw observations."""
        lines = []
        session_id_short = session["id"][:8]
        started = session.get("started_at", "unknown")
        score = session.get("_relevance_score", 0.0)

        lines.append(
            f"### Session {session_id_short} ({started})"
            + (f" — relevance: {score:.2f}" if score > 0 else "")
        )

        for obs in observations:
            event = obs.get("event_type", "Unknown")
            tool = obs.get("tool_name", "")
            file_path = obs.get("file_path", "")

            detail = ""
            if tool:
                detail += f" → {tool}"
            if file_path:
                detail += f" `{file_path}`"

            content = obs.get("tool_output") or obs.get("error") or obs.get("prompt") or ""
            if content:
                # Normalize: collapse newlines and whitespace to single spaces
                content = " ".join(content.split())
                content = content[:60] + "..." if len(content) > 60 else content
                detail += f": {content}"

            lines.append(f"- **{event}**{detail}")

        return "\n".join(lines)

    def _format_structured_session(
        self, session: dict[str, Any], structured: list[dict[str, Any]]
    ) -> str:
        """Format a session with structured observations."""
        lines = []
        session_id_short = session["id"][:8]
        started = session.get("started_at", "unknown")
        score = session.get("_relevance_score", 0.0)

        lines.append(
            f"### Session {session_id_short} ({started})"
            + (f" — relevance: {score:.2f}" if score > 0 else "")
        )

        for obs in structured:
            obs_type = obs.get("type", "discovery")
            title = obs.get("title", "Untitled")
            subtitle = obs.get("subtitle", "")
            source = obs.get("source", "heuristic")
            source_emoji = {"ai": "🤖", "heuristic": "⚡", "manual": "✋"}.get(source, "•")

            type_emoji = {
                "bugfix": "🐛",
                "feature": "✨",
                "refactor": "♻️",
                "change": "📝",
                "discovery": "🔍",
                "decision": "🎯",
            }.get(obs_type, "•")

            lines.append(f"- {source_emoji} {type_emoji} **{title}**")
            if subtitle:
                lines.append(f"  _{subtitle}_")

            facts = obs.get("facts", [])
            for fact in facts[:2]:
                lines.append(f"  • {fact}")

            files = (obs.get("files_modified", []) + obs.get("files_read", []))[:2]
            if files:
                lines.append(f"  📁 {', '.join(files)}")

        return "\n".join(lines)

    def _format_project_structured(self, structured: list[dict[str, Any]]) -> str:
        """Format recent structured observations for the project."""
        lines = ["## 📚 Recent Knowledge"]

        for obs in structured:
            obs_type = obs.get("type", "discovery")
            title = obs.get("title", "Untitled")
            narrative = obs.get("narrative", "")
            source = obs.get("source", "heuristic")
            source_emoji = {"ai": "🤖", "heuristic": "⚡", "manual": "✋"}.get(source, "•")

            type_emoji = {
                "bugfix": "🐛",
                "feature": "✨",
                "refactor": "♻️",
                "change": "📝",
                "discovery": "🔍",
                "decision": "🎯",
            }.get(obs_type, "•")

            lines.append(f"- {source_emoji} {type_emoji} **{title}**")
            if narrative:
                narrative = " ".join(narrative.split())
                narrative = narrative[:100] + "..." if len(narrative) > 100 else narrative
                lines.append(f"  {narrative}")

            facts = obs.get("facts", [])
            for fact in facts[:2]:
                lines.append(f"  • {fact}")

        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count for mixed text (code + natural language).

        Uses a character-category-aware heuristic:
        - ASCII (code, English): ~4 chars/token
        - Non-ASCII (Cyrillic, CJK): ~1.5 chars/token

        This is more accurate than a flat multiplier, especially for
        codebases with mixed languages.
        """
        if not text:
            return 0
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii_chars = len(text) - ascii_chars
        estimated = (ascii_chars / 4.0) + (non_ascii_chars / 1.5)
        return max(1, int(estimated))

    def _wrap_context(self, context_parts: list[str]) -> str:
        """Wrap context parts in header/footer based on format."""
        if self.format == "json":
            import json

            return json.dumps({"previous_context": context_parts}, ensure_ascii=False, indent=2)

        if self.format == "plain":
            return "Previous Context\n\n" + "\n\n".join(context_parts) + "\n---\n"

        # Default: markdown
        header = "## Previous Context\n\n"
        footer = "\n---\n"
        return header + "\n\n".join(context_parts) + footer
