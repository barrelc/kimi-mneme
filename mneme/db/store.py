"""Observation storage and retrieval."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from mneme.config import load_config
from mneme.db.schema import get_connection
from mneme.db.vector import SQLiteVecStore


@dataclass
class Observation:
    """A single observation from a session."""

    session_id: str
    event_type: str
    tool_name: str | None = None
    tool_input: str | None = None
    tool_output: str | None = None
    error: str | None = None
    file_path: str | None = None
    prompt: str | None = None
    agent_name: str | None = None
    created_at: str | None = None
    id: int | None = None


@dataclass
class PendingMessage:
    """A pending work queue message."""

    session_id: str
    message_type: str  # 'observation', 'summarize', 'compress'
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: str | None = None
    tool_response: str | None = None
    error: str | None = None
    cwd: str | None = None
    last_user_message: str | None = None
    last_assistant_message: str | None = None
    prompt_number: int | None = None
    status: str = "pending"  # 'pending', 'processing', 'processed', 'failed'
    retry_count: int = 0
    created_at: str | None = None
    failed_at: str | None = None
    completed_at: str | None = None
    id: int | None = None


class ObservationStore:
    """Store and retrieve observations from SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self.sqlite_vec = SQLiteVecStore(db_path=self.db_path)
        self._ensure_db()
        self._local = threading.local()

    def _ensure_db(self) -> None:
        """Ensure database exists."""
        from mneme.db.schema import init_db

        db_file = Path(self.db_path)
        if not db_file.exists():
            init_db(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        # Reuse connection per thread
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = get_connection(self.db_path)
        return self._local.conn

    # -----------------------------------------------------------------------
    # Sessions
    # -----------------------------------------------------------------------

    def add_session(self, session_id: str, cwd: str) -> None:
        """Create a new session record."""
        import os

        project = os.path.basename(cwd.rstrip("/\\"))
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, cwd, project) VALUES (?, ?, ?)",
                (session_id, cwd, project),
            )
        logger.debug(f"Session created: {session_id}")

    def end_session(self, session_id: str, reason: str) -> None:
        """Mark session as ended."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
        logger.debug(f"Session ended: {session_id} ({reason})")

    # -----------------------------------------------------------------------
    # Observations
    # -----------------------------------------------------------------------

    def add_observation(self, observation: Observation, skip_vector: bool = True) -> int:
        """Add an observation and return its ID."""
        content = self._observation_to_text(observation)
        content_hash = self._hash_content(content) if content else None

        with self._get_conn() as conn:
            # Use provided created_at or default to CURRENT_TIMESTAMP
            created_at = observation.created_at
            if created_at:
                cursor = conn.execute(
                    """
                    INSERT INTO observations
                    (session_id, event_type, tool_name, tool_input, tool_output,
                     error, file_path, prompt, agent_name, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        observation.session_id,
                        observation.event_type,
                        observation.tool_name,
                        observation.tool_input,
                        observation.tool_output,
                        observation.error,
                        observation.file_path,
                        observation.prompt,
                        observation.agent_name,
                        content_hash,
                        created_at,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO observations
                    (session_id, event_type, tool_name, tool_input, tool_output,
                     error, file_path, prompt, agent_name, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        observation.session_id,
                        observation.event_type,
                        observation.tool_name,
                        observation.tool_input,
                        observation.tool_output,
                        observation.error,
                        observation.file_path,
                        observation.prompt,
                        observation.agent_name,
                        content_hash,
                    ),
                )
            obs_id = cursor.lastrowid

        if obs_id and not skip_vector:
            # Add to sqlite-vec for semantic search
            if content:
                self.sqlite_vec.add_raw_observation(
                    observation_id=obs_id,
                    session_id=observation.session_id,
                    content=content,
                    event_type=observation.event_type,
                    tool_name=observation.tool_name or "",
                )
            logger.debug(f"Observation added: {obs_id}")
        else:
            logger.debug(
                f"Observation deduplicated (hash: {content_hash})"
                if not obs_id
                else f"Observation added (no vector): {obs_id}"
            )

        return obs_id or 0

    @staticmethod
    def _observation_to_text(observation: Observation) -> str:
        """Convert observation to searchable text."""
        parts = []
        if observation.tool_name:
            parts.append(f"Tool: {observation.tool_name}")
        if observation.file_path:
            parts.append(f"File: {observation.file_path}")
        if observation.prompt:
            parts.append(f"Prompt: {observation.prompt}")
        if observation.tool_output:
            parts.append(f"Output: {observation.tool_output}")
        if observation.error:
            parts.append(f"Error: {observation.error}")
        if observation.tool_input:
            parts.append(f"Input: {observation.tool_input}")
        return "\n".join(parts)

    @staticmethod
    def _hash_content(content: str) -> str:
        """Hash content for deduplication."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        use_vector: bool = False,
    ) -> list[dict[str, Any]]:
        """Hybrid search: FTS + fallback LIKE + vector similarity."""
        # Build FTS query with OR between words for better recall
        words = [w for w in query.strip().split() if len(w) > 2]
        if words:
            # Try exact phrase first, then individual words with OR
            fts_query = f'"{query}" OR ' + " OR ".join(words) if len(words) > 1 else query
        else:
            fts_query = query

        fts_results: list[dict[str, Any]] = []

        # FTS search
        with self._get_conn() as conn:
            try:
                sql = """
                    SELECT o.id, o.session_id, o.event_type, o.tool_name,
                           o.file_path, o.created_at, o.prompt, o.tool_output,
                           o.error, o.tool_input,
                           COALESCE(snippet(observations_fts, -1, '[', ']', '...', 32), '') as snippet
                    FROM observations_fts
                    JOIN observations o ON observations_fts.rowid = o.id
                    WHERE observations_fts MATCH ?
                """
                params: list[Any] = [fts_query]

                if date_from:
                    sql += " AND o.created_at >= ?"
                    params.append(date_from)
                if date_to:
                    sql += " AND o.created_at <= ?"
                    params.append(date_to)

                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()
                fts_results = [dict(row) for row in rows]
            except Exception as e:
                logger.debug(f"FTS search failed, will use fallback: {e}")

        # Fallback: LIKE search if FTS returns nothing
        if not fts_results:
            with self._get_conn() as conn:
                like_pattern = f"%{query}%"
                sql = """
                    SELECT o.id, o.session_id, o.event_type, o.tool_name,
                           o.file_path, o.created_at, o.prompt, o.tool_output,
                           o.error, o.tool_input,
                           SUBSTR(COALESCE(o.tool_output, o.error, o.prompt, o.tool_input, ''), 1, 200) as snippet
                    FROM observations o
                    WHERE (o.tool_output LIKE ? OR o.error LIKE ? OR o.prompt LIKE ?
                           OR o.tool_input LIKE ? OR o.tool_name LIKE ? OR o.file_path LIKE ?)
                """
                params = [like_pattern] * 6

                if date_from:
                    sql += " AND o.created_at >= ?"
                    params.append(date_from)
                if date_to:
                    sql += " AND o.created_at <= ?"
                    params.append(date_to)

                sql += " ORDER BY o.created_at DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()
                fts_results = [dict(row) for row in rows]

        # Also search sessions by ID or content
        session_results = []
        if len(fts_results) < limit:
            with self._get_conn() as conn:
                like_pattern = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT DISTINCT s.id as session_id, s.cwd, s.summary,
                           (SELECT COUNT(*) FROM observations WHERE session_id = s.id) as obs_count
                    FROM sessions s
                    WHERE s.id LIKE ? OR s.cwd LIKE ? OR s.summary LIKE ?
                    LIMIT ?
                """,
                    (like_pattern, like_pattern, like_pattern, limit),
                ).fetchall()

                for row in rows:
                    # Check if we already have observations from this session
                    has_obs = any(r.get("session_id") == row["session_id"] for r in fts_results)
                    if not has_obs:
                        session_results.append(
                            {
                                "id": f"session_{row['session_id']}",
                                "session_id": row["session_id"],
                                "event_type": "SessionMatch",
                                "tool_name": None,
                                "file_path": row["cwd"],
                                "created_at": None,
                                "snippet": f"Session with {row['obs_count']} observations: {row['summary'] or row['cwd'] or row['session_id']}",
                            }
                        )

        # Vector search (sqlite-vec)
        vector_results = []
        if use_vector:
            try:
                vector_results = self.sqlite_vec.search_raw(query, limit=limit)
            except Exception as e:
                logger.debug(f"Vector search skipped: {e}")

        # Merge and deduplicate
        seen_ids = {r["id"] for r in fts_results}
        for vr in vector_results:
            obs_id = vr.get("observation_id")
            if obs_id and obs_id not in seen_ids:
                fts_results.append(
                    {
                        "id": obs_id,
                        "session_id": vr.get("session_id"),
                        "event_type": "VectorMatch",
                        "tool_name": vr.get("tool_name"),
                        "file_path": None,
                        "created_at": None,
                        "snippet": "",
                        "vector_distance": vr.get("distance"),
                    }
                )
                seen_ids.add(obs_id)

        # Add session results if we still have room
        for sr in session_results:
            if len(fts_results) >= limit:
                break
            if sr["id"] not in seen_ids:
                fts_results.append(sr)
                seen_ids.add(sr["id"])

        return fts_results[:limit]

    # -----------------------------------------------------------------------
    # Timeline
    # -----------------------------------------------------------------------

    def get_timeline(self, observation_id: int, radius: int = 5) -> dict[str, Any]:
        """Get observations around a specific point in time."""
        with self._get_conn() as conn:
            center = conn.execute(
                "SELECT * FROM observations WHERE id = ?", (observation_id,)
            ).fetchone()

            if not center:
                return {"center": None, "before": [], "after": []}

            rows = conn.execute(
                """
                SELECT * FROM observations
                WHERE session_id = ?
                  AND id BETWEEN ? AND ?
                ORDER BY id
                """,
                (
                    center["session_id"],
                    max(1, observation_id - radius),
                    observation_id + radius,
                ),
            ).fetchall()

        before = []
        after = []
        center_dict = dict(center)

        for row in rows:
            row_dict = dict(row)
            if row_dict["id"] < observation_id:
                before.append(row_dict)
            elif row_dict["id"] > observation_id:
                after.append(row_dict)

        return {"center": center_dict, "before": before, "after": after}

    # -----------------------------------------------------------------------
    # Batch fetch
    # -----------------------------------------------------------------------

    def get_observations(self, ids: list[int]) -> list[dict[str, Any]]:
        """Get full details for specific observation IDs."""
        if not ids:
            return []

        placeholders = ",".join("?" * len(ids))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM observations WHERE id IN ({placeholders})",
                ids,
            ).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Sessions listing
    # -----------------------------------------------------------------------

    def get_sessions(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """List sessions with enriched metadata."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.*,
                    COUNT(o.id) as observation_count,
                    MAX(o.created_at) as last_activity,
                    (SELECT prompt FROM observations
                     WHERE session_id = s.id AND event_type = 'UserPromptSubmit' AND prompt != ''
                     ORDER BY created_at DESC LIMIT 1) as last_prompt,
                    (SELECT prompt FROM observations
                     WHERE session_id = s.id AND event_type = 'UserPromptSubmit' AND prompt != ''
                     ORDER BY created_at ASC LIMIT 1) as first_prompt,
                    (SELECT COUNT(*) FROM observations
                     WHERE session_id = s.id AND event_type = 'UserPromptSubmit') as prompt_count,
                    (SELECT COUNT(*) FROM observations
                     WHERE session_id = s.id AND event_type = 'PostToolUse') as tool_count
                FROM sessions s
                LEFT JOIN observations o ON s.id = o.session_id
                GROUP BY s.id
                ORDER BY last_activity DESC NULLS LAST, s.started_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_sessions_for_project(
        self,
        cwd: str,
        limit: int = 20,
        recency_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get sessions for a specific project/directory."""
        import os

        project_name = os.path.basename(cwd.rstrip("/\\"))

        with self._get_conn() as conn:
            sql = """
                SELECT s.*, COUNT(o.id) as observation_count
                FROM sessions s
                LEFT JOIN observations o ON s.id = o.session_id
                WHERE s.cwd = ?
                   OR s.cwd LIKE ?
                   OR s.cwd LIKE ?
                   OR s.project = ?
            """
            params: list[Any] = [
                cwd,
                f"%{cwd}%",
                f"%{project_name}%",
                project_name,
            ]

            if recency_days:
                sql += " AND s.started_at >= datetime('now', '-' || ? || ' days')"
                params.append(recency_days)

            sql += """
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT ?
            """
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    def get_observations_for_session(
        self, session_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get observations for a specific session."""
        sql = """
            SELECT * FROM observations
            WHERE session_id = ?
            ORDER BY created_at ASC
        """
        params: list[Any] = [session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # User prompts
    # -----------------------------------------------------------------------

    def add_user_prompt(self, session_id: str, prompt_number: int, prompt_text: str) -> int:
        """Add a user prompt record."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_prompts (session_id, prompt_number, prompt_text)
                VALUES (?, ?, ?)
                """,
                (session_id, prompt_number, prompt_text),
            )
            prompt_id = cursor.lastrowid

        logger.debug(f"User prompt added: {prompt_id}")
        return prompt_id or 0

    def get_user_prompts(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get user prompts for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_prompts
                WHERE session_id = ?
                ORDER BY prompt_number DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Pending messages queue
    # -----------------------------------------------------------------------

    def add_pending_message(self, message: PendingMessage) -> int:
        """Add a message to the pending queue."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_messages
                (session_id, message_type, tool_use_id, tool_name, tool_input,
                 tool_response, error, cwd, last_user_message, last_assistant_message,
                 prompt_number, status, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    message.session_id,
                    message.message_type,
                    message.tool_use_id,
                    message.tool_name,
                    message.tool_input,
                    message.tool_response,
                    message.error,
                    message.cwd,
                    message.last_user_message,
                    message.last_assistant_message,
                    message.prompt_number,
                    message.status,
                    message.retry_count,
                ),
            )
            msg_id = cursor.lastrowid

        if msg_id:
            logger.debug(f"Pending message added: {msg_id}")
        return msg_id or 0

    def claim_pending_messages(
        self, limit: int = 10, message_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Claim pending messages for processing (self-healing)."""
        with self._get_conn() as conn:
            sql = """
                SELECT * FROM pending_messages
                WHERE status = 'pending'
            """
            params: list[Any] = []

            if message_type:
                sql += " AND message_type = ?"
                params.append(message_type)

            sql += " ORDER BY created_at LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()

            # Mark as processing
            for row in rows:
                conn.execute(
                    """
                    UPDATE pending_messages
                    SET status = 'processing', retry_count = retry_count + 1
                    WHERE id = ?
                    """,
                    (row["id"],),
                )

        return [dict(row) for row in rows]

    def mark_message_processed(self, message_id: int) -> None:
        """Mark a message as processed."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE pending_messages
                SET status = 'processed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message_id,),
            )
        logger.debug(f"Message {message_id} processed")

    def mark_message_failed(self, message_id: int) -> None:
        """Mark a message as failed."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE pending_messages
                SET status = 'failed', failed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message_id,),
            )
        logger.debug(f"Message {message_id} failed")

    def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM pending_messages").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE status = 'pending'"
            ).fetchone()[0]
            processing = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE status = 'processing'"
            ).fetchone()[0]
            processed = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE status = 'processed'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE status = 'failed'"
            ).fetchone()[0]

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "processed": processed,
            "failed": failed,
        }

    # -----------------------------------------------------------------------
    # Observation feedback
    # -----------------------------------------------------------------------

    def add_feedback(
        self,
        observation_id: int,
        signal_type: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Add feedback signal for an observation."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO observation_feedback
                (observation_id, signal_type, session_id, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (
                    observation_id,
                    signal_type,
                    session_id,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            feedback_id = cursor.lastrowid

        logger.debug(f"Feedback added: {feedback_id}")
        return feedback_id or 0

    def get_feedback_for_observation(self, observation_id: int) -> list[dict[str, Any]]:
        """Get feedback for an observation."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM observation_feedback
                WHERE observation_id = ?
                ORDER BY created_at DESC
                """,
                (observation_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        with self._get_conn() as conn:
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            observations = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            summaries = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            user_prompts = conn.execute("SELECT COUNT(*) FROM user_prompts").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM pending_messages").fetchone()[0]
            feedback = conn.execute("SELECT COUNT(*) FROM observation_feedback").fetchone()[0]

            top_projects = conn.execute("""
                SELECT COALESCE(project, cwd) as project, COUNT(*) as count
                FROM sessions
                GROUP BY COALESCE(project, cwd)
                ORDER BY count DESC
                LIMIT 5
                """).fetchall()

        db_size = Path(self.db_path).stat().st_size

        return {
            "total_sessions": sessions,
            "total_observations": observations,
            "total_summaries": summaries,
            "total_user_prompts": user_prompts,
            "total_pending_messages": pending,
            "total_feedback": feedback,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "top_projects": [dict(row) for row in top_projects],
            "queue": self.get_queue_stats(),
        }

    # -----------------------------------------------------------------------
    # Summaries
    # -----------------------------------------------------------------------

    def add_summary(
        self,
        session_id: str,
        content: str,
        observation_ids: list[int] | None = None,
        keywords: list[str] | None = None,
        embedding_id: str | None = None,
    ) -> int:
        """Add an AI-generated summary."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO summaries
                (session_id, observation_ids, content, keywords, embedding_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    json.dumps(observation_ids or []),
                    content,
                    json.dumps(keywords or []),
                    embedding_id,
                ),
            )
            summary_id = cursor.lastrowid

        logger.debug(f"Summary added: {summary_id}")
        return summary_id or 0

    # -----------------------------------------------------------------------
    # Session Summaries (AI-generated structured summaries)
    # -----------------------------------------------------------------------

    def add_session_summary(
        self,
        session_id: str,
        title: str | None = None,
        request: str | None = None,
        investigated: str | None = None,
        learned: str | None = None,
        completed: str | None = None,
        next_steps: str | None = None,
        files_read: str | None = None,
        files_edited: str | None = None,
        notes: str | None = None,
        raw_summary: str | None = None,
        model: str | None = None,
    ) -> int:
        """Add an AI-generated structured session summary."""
        with self._get_conn() as conn:
            # Delete any existing summary for this session
            conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
            cursor = conn.execute(
                """
                INSERT INTO session_summaries
                (session_id, title, request, investigated, learned, completed,
                 next_steps, files_read, files_edited, notes, raw_summary, model)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    request,
                    investigated,
                    learned,
                    completed,
                    next_steps,
                    files_read,
                    files_edited,
                    notes,
                    raw_summary,
                    model,
                ),
            )
            summary_id = cursor.lastrowid

        logger.debug(f"Session summary added: {summary_id} for session {session_id}")
        return summary_id or 0

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        """Get the AI-generated structured summary for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM session_summaries
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()

        if row:
            return dict(row)
        return None

    # -----------------------------------------------------------------------
    # Session checkpoints
    # -----------------------------------------------------------------------

    def add_checkpoint(
        self,
        session_id: str,
        summary: str,
        key_decisions: list[str] | None = None,
        open_tasks: list[str] | None = None,
        checkpoint_type: str = "auto",
        token_count: int | None = None,
        observation_count: int | None = None,
    ) -> int:
        """Add a session checkpoint for resume after compaction/crash."""
        with self._get_conn() as conn:
            # Get next checkpoint number
            row = conn.execute(
                "SELECT MAX(checkpoint_number) FROM session_checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            next_number = (row[0] or 0) + 1

            cursor = conn.execute(
                """
                INSERT INTO session_checkpoints
                (session_id, checkpoint_number, checkpoint_type, summary,
                 key_decisions, open_tasks, token_count, observation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    next_number,
                    checkpoint_type,
                    summary,
                    json.dumps(key_decisions or []),
                    json.dumps(open_tasks or []),
                    token_count,
                    observation_count,
                ),
            )
            checkpoint_id = cursor.lastrowid

        logger.info(f"Checkpoint {next_number} added for session {session_id}")
        return checkpoint_id or 0

    def get_latest_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        """Get the latest checkpoint for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM session_checkpoints
                WHERE session_id = ?
                ORDER BY checkpoint_number DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()

        if not row:
            return None

        result = dict(row)
        result["key_decisions"] = json.loads(result.get("key_decisions") or "[]")
        result["open_tasks"] = json.loads(result.get("open_tasks") or "[]")
        return result

    def get_checkpoints(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get all checkpoints for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM session_checkpoints
                WHERE session_id = ?
                ORDER BY checkpoint_number DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            r["key_decisions"] = json.loads(r.get("key_decisions") or "[]")
            r["open_tasks"] = json.loads(r.get("open_tasks") or "[]")
            results.append(r)
        return results

    def get_resume_context(self, session_id: str) -> dict[str, Any] | None:
        """Get full resume context for a session (latest checkpoint + last observations)."""
        checkpoint = self.get_latest_checkpoint(session_id)
        if not checkpoint:
            return None

        observations = self.get_observations_for_session(session_id, limit=5)

        return {
            "checkpoint": checkpoint,
            "recent_observations": observations,
            "session_id": session_id,
        }

    # -----------------------------------------------------------------------
    # Compaction events
    # -----------------------------------------------------------------------

    def record_compaction(
        self,
        session_id: str,
        tokens_before: int | None = None,
        tokens_after: int | None = None,
        observations_dropped: int | None = None,
        summary_generated: str | None = None,
    ) -> int:
        """Record a context compaction event."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO compaction_events
                (session_id, tokens_before, tokens_after, observations_dropped, summary_generated)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    tokens_before,
                    tokens_after,
                    observations_dropped,
                    summary_generated,
                ),
            )
            event_id = cursor.lastrowid

        logger.info(f"Compaction recorded for session {session_id}")
        return event_id or 0

    def get_compaction_history(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get compaction history for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM compaction_events
                WHERE session_id = ?
                ORDER BY compacted_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_token_economics(self) -> dict[str, Any]:
        """Calculate token economics across all compaction events.

        Returns:
            Dict with tokens_invested, tokens_loaded, tokens_saved,
            savings_percent, compaction_count, observations_preserved.
        """
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(tokens_before), 0) as total_before,
                    COALESCE(SUM(tokens_after), 0) as total_after,
                    COALESCE(SUM(observations_dropped), 0) as total_dropped,
                    COUNT(*) as compaction_count
                FROM compaction_events
                """).fetchone()

            total_obs = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

        total_before = row[0] or 0
        total_after = row[1] or 0
        total_dropped = row[2] or 0
        compaction_count = row[3] or 0

        tokens_saved = max(0, total_before - total_after)
        savings_percent = round((tokens_saved / total_before) * 100, 1) if total_before > 0 else 0

        return {
            "tokens_invested": total_before,
            "tokens_loaded": total_after,
            "tokens_saved": tokens_saved,
            "savings_percent": savings_percent,
            "compaction_count": compaction_count,
            "observations_dropped": total_dropped,
            "observations_preserved": max(0, total_obs - total_dropped),
            "total_observations": total_obs,
        }

    # -----------------------------------------------------------------------
    # Patterns (cross-session)
    # -----------------------------------------------------------------------

    def add_or_update_pattern(
        self,
        pattern_type: str,
        pattern_hash: str,
        title: str,
        description: str,
        session_id: str | None = None,
        related_files: list[str] | None = None,
        related_observation_ids: list[int] | None = None,
    ) -> int:
        """Add a new pattern or update existing one."""
        with self._get_conn() as conn:
            # Try to update existing
            existing = conn.execute(
                "SELECT id, occurrence_count FROM patterns WHERE pattern_hash = ?",
                (pattern_hash,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE patterns
                    SET occurrence_count = occurrence_count + 1,
                        last_seen_session_id = ?,
                        updated_at = CURRENT_TIMESTAMP,
                        description = CASE WHEN LENGTH(?) > LENGTH(description) THEN ? ELSE description END
                    WHERE id = ?
                    """,
                    (session_id, description, description, existing["id"]),
                )
                logger.debug(f"Pattern updated: {pattern_hash}")
                return existing["id"]

            # Insert new
            cursor = conn.execute(
                """
                INSERT INTO patterns
                (pattern_type, pattern_hash, title, description,
                 first_seen_session_id, last_seen_session_id,
                 related_files, related_observation_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_type,
                    pattern_hash,
                    title,
                    description,
                    session_id,
                    session_id,
                    json.dumps(related_files or []),
                    json.dumps(related_observation_ids or []),
                ),
            )
            pattern_id = cursor.lastrowid

        logger.info(f"New pattern added: {title}")
        return pattern_id or 0

    def find_patterns(
        self,
        pattern_type: str | None = None,
        query: str | None = None,
        min_occurrences: int = 1,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find patterns matching criteria."""
        with self._get_conn() as conn:
            sql = "SELECT * FROM patterns WHERE occurrence_count >= ?"
            params: list[Any] = [min_occurrences]

            if pattern_type:
                sql += " AND pattern_type = ?"
                params.append(pattern_type)

            if query:
                sql += " AND (title LIKE ? OR description LIKE ?)"
                params.extend([f"%{query}%", f"%{query}%"])

            sql += " ORDER BY occurrence_count DESC, updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            r["related_files"] = json.loads(r.get("related_files") or "[]")
            r["related_observation_ids"] = json.loads(r.get("related_observation_ids") or "[]")
            results.append(r)
        return results

    def get_patterns_for_project(self, cwd: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get patterns relevant to current project."""
        import os

        project_name = os.path.basename(cwd.rstrip("/\\"))

        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM patterns
                WHERE related_files LIKE ? OR title LIKE ? OR description LIKE ?
                ORDER BY occurrence_count DESC, updated_at DESC
                LIMIT ?
                """,
                (f"%{project_name}%", f"%{project_name}%", f"%{project_name}%", limit),
            ).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            r["related_files"] = json.loads(r.get("related_files") or "[]")
            r["related_observation_ids"] = json.loads(r.get("related_observation_ids") or "[]")
            results.append(r)
        return results

    # -----------------------------------------------------------------------
    # Truncated outputs
    # -----------------------------------------------------------------------

    def record_truncated_output(
        self,
        observation_id: int,
        original_size: int,
        truncated_size: int,
        summary: str | None = None,
        head_preview: str | None = None,
        tail_preview: str | None = None,
        line_count: int | None = None,
    ) -> int:
        """Record that a tool output was truncated."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO truncated_outputs
                (observation_id, original_size, truncated_size, summary,
                 head_preview, tail_preview, line_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    original_size,
                    truncated_size,
                    summary,
                    head_preview,
                    tail_preview,
                    line_count,
                ),
            )
            record_id = cursor.lastrowid

        logger.debug(f"Truncated output recorded for observation {observation_id}")
        return record_id or 0

    def get_truncated_output(self, observation_id: int) -> dict[str, Any] | None:
        """Get truncation record for an observation."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM truncated_outputs WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()

        return dict(row) if row else None
