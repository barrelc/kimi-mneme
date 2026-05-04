"""Storage for wire event data extracted from Kimi CLI sessions."""

from __future__ import annotations

import json
import threading
from typing import Any

from mneme.config import load_config
from mneme.db.schema import get_connection
from mneme.wire.models import (
    ContentPartEvent,
    SessionState,
    StatusUpdateEvent,
    WireEvent,
)


class WireStore:
    """Store and query wire event data."""

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self._local = threading.local()

    def _get_conn(self) -> Any:
        # Reuse connection per thread to avoid opening thousands of connections
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = get_connection(self.db_path)
        return self._local.conn

    # ------------------------------------------------------------------
    # Session ensure
    # ------------------------------------------------------------------

    def ensure_session(self, session_id: str, cwd: str = "") -> None:
        """Create session record if missing."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, cwd, project) VALUES (?, ?, ?)",
                (session_id, cwd, cwd),
            )

    # ------------------------------------------------------------------
    # Wire events
    # ------------------------------------------------------------------

    def add_wire_event(self, event: WireEvent) -> int:
        """Store a raw wire event. Skips duplicates via INSERT OR IGNORE."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO wire_events
                (session_id, timestamp, event_type, step_number, turn_number, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    event.timestamp,
                    event.event_type,
                    getattr(event, "step_number", None),
                    getattr(event, "turn_number", None),
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
            return cursor.lastrowid or 0

    def get_wire_events(
        self,
        session_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get wire events for a session."""
        sql = "SELECT * FROM wire_events WHERE session_id = ?"
        params: list[Any] = [session_id]
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY timestamp LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Session stats (StatusUpdate)
    # ------------------------------------------------------------------

    def add_session_stat(self, event: StatusUpdateEvent) -> int:
        """Store a StatusUpdate snapshot."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO session_stats
                (session_id, timestamp, context_tokens, max_context_tokens,
                 input_cache_read, input_cache_creation, input_other,
                 output_tokens, message_id, plan_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    event.timestamp,
                    event.context_tokens,
                    event.max_context_tokens,
                    event.input_cache_read,
                    event.input_cache_creation,
                    event.input_other,
                    event.output_tokens,
                    event.message_id,
                    int(event.plan_mode or 0),
                ),
            )
            return cursor.lastrowid or 0

    def get_session_stats(self, session_id: str) -> list[dict[str, Any]]:
        """Get all stats snapshots for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM session_stats
                WHERE session_id = ?
                ORDER BY timestamp
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_session_stat(self, session_id: str) -> dict[str, Any] | None:
        """Get the most recent stats snapshot for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM session_stats
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Thinking
    # ------------------------------------------------------------------

    def add_thinking(self, event: ContentPartEvent) -> int:
        """Store an agent thinking block."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO thinking
                (session_id, turn_number, step_number, content, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    getattr(event, "turn_number", None),
                    getattr(event, "step_number", None),
                    event.think,
                    event.timestamp,
                ),
            )
            return cursor.lastrowid or 0

    def get_thinking(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get thinking blocks for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM thinking WHERE session_id = ? ORDER BY timestamp LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Assistant messages
    # ------------------------------------------------------------------

    def add_assistant_message(self, event: ContentPartEvent) -> int:
        """Store an assistant response."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO assistant_messages
                (session_id, turn_number, step_number, content, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    getattr(event, "turn_number", None),
                    getattr(event, "step_number", None),
                    event.text,
                    event.timestamp,
                ),
            )
            return cursor.lastrowid or 0

    def get_assistant_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get assistant messages for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM assistant_messages WHERE session_id = ? ORDER BY timestamp LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Todos
    # ------------------------------------------------------------------

    def sync_todos(self, state: SessionState) -> None:
        """Replace todos for a session with latest from state.json."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM session_todos WHERE session_id = ?", (state.session_id,))
            for i, todo in enumerate(state.todos):
                conn.execute(
                    """
                    INSERT INTO session_todos
                    (session_id, title, status, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    (state.session_id, todo.get("title", ""), todo.get("status", ""), i),
                )

    def get_todos(self, session_id: str) -> list[dict[str, Any]]:
        """Get todos for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM session_todos WHERE session_id = ? ORDER BY position",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Observations bridge (populate from wire for backward compat)
    # ------------------------------------------------------------------

    def add_observation_from_wire(
        self,
        session_id: str,
        event_type: str,
        tool_name: str | None = None,
        tool_input: str | None = None,
        tool_output: str | None = None,
        error: str | None = None,
        file_path: str | None = None,
        prompt: str | None = None,
        step_number: int | None = None,
        turn_number: int | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Add an observation record compatible with the old schema.
        
        Skips vector embedding for performance — wire events are indexed
        in bulk and vector search is secondary for trace data.
        """
        from datetime import datetime, timezone
        from mneme.db.store import Observation, ObservationStore

        store = ObservationStore(self.db_path)
        # Convert wire timestamp to ISO format for created_at
        created_at = None
        if timestamp:
            created_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

        obs = Observation(
            session_id=session_id,
            event_type=event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            error=error,
            file_path=file_path,
            prompt=prompt,
            created_at=created_at,
        )
        return store.add_observation(obs, skip_vector=True)
