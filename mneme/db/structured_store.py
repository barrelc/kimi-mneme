"""Storage for structured observations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from typing import Any

from loguru import logger

from mneme.config import load_config
from mneme.core.prompts.json_parser import ParsedObservation
from mneme.db.schema import get_connection


class StructuredObservationStore:
    """Store and retrieve structured observations from SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = get_connection(self.db_path)
        return self._local.conn

    def close(self) -> None:
        """Close thread-local connection to release WAL locks."""
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.commit()
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_structured(
        self,
        obs: ParsedObservation,
        session_id: str,
        project: str,
        raw_observation_id: int | None = None,
        source: str = "ai",
        model: str | None = None,
    ) -> int:
        """Add a structured observation. Returns ID or 0 if deduplicated.

        Dedup v2: If a structured observation with the same content_hash already
        exists for this session, a soft dedup link is created instead of silently
        dropping the observation. This preserves the relationship between different
        raw_observation_ids.
        """
        content_hash = self._compute_hash(session_id, obs.title, obs.narrative)

        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO structured_observations
            (session_id, project, type, title, subtitle, facts, narrative,
             concepts, files_read, files_modified, content_hash,
             raw_observation_id, source, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, content_hash) DO NOTHING
            RETURNING id
            """,
            (
                session_id,
                project,
                obs.type,
                obs.title,
                obs.subtitle,
                json.dumps(obs.facts, ensure_ascii=False),
                obs.narrative,
                json.dumps(obs.concepts, ensure_ascii=False),
                json.dumps(obs.files_read, ensure_ascii=False),
                json.dumps(obs.files_modified, ensure_ascii=False),
                content_hash,
                raw_observation_id,
                source,
                model,
            ),
        )
        row = cursor.fetchone()
        obs_id = row[0] if row else None

        if obs_id:
            logger.debug(f"Structured observation added: {obs_id} ({obs.type})")
            # Add field-level vector embeddings (sqlite-vec first, Chroma fallback)
            try:
                from mneme.db.vector import SQLiteVecStore

                vec_store = SQLiteVecStore(db_path=self.db_path)
                # Share connection to avoid "database is locked"
                vec_store.set_conn(conn)
                vec_store.add_structured_fields(
                    structured_id=obs_id,
                    session_id=session_id,
                    project=project,
                    title=obs.title,
                    narrative=obs.narrative,
                    facts=obs.facts,
                )
            except Exception:
                pass  # Vector store is best-effort

            # Schedule PROJECT.md update
            try:
                from mneme.core.project_md import get_project_md_generator

                get_project_md_generator().schedule_update(project)
            except Exception:
                pass  # PROJECT.md is best-effort
        else:
            # Dedup v2: Create soft link to existing observation
            existing = conn.execute(
                "SELECT id FROM structured_observations WHERE session_id = ? AND content_hash = ?",
                (session_id, content_hash),
            ).fetchone()

            if existing:
                existing_id = existing[0]
                conn.execute(
                    """
                    INSERT INTO structured_observation_links
                    (existing_structured_id, linked_raw_observation_id, linked_session_id, content_hash, link_type)
                    VALUES (?, ?, ?, ?, 'dedup')
                    """,
                    (existing_id, raw_observation_id, session_id, content_hash),
                )
                logger.debug(
                    f"Soft dedup link created: raw_obs={raw_observation_id} -> structured={existing_id}"
                )
            else:
                logger.debug(f"Structured observation deduplicated (hash: {content_hash})")

        return obs_id or 0

    @staticmethod
    def _compute_hash(session_id: str, title: str, narrative: str | None) -> str:
        """Compute content hash for deduplication."""
        text = f"{session_id}:{title}:{narrative or ''}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_by_id(self, obs_id: int) -> dict[str, Any] | None:
        """Get a single structured observation by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM structured_observations WHERE id = ?",
                (obs_id,),
            ).fetchone()

        return self._deserialize(row) if row else None

    def get_by_session(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Get structured observations for a session."""
        sql = "SELECT * FROM structured_observations WHERE session_id = ? ORDER BY created_at DESC"
        params: list[Any] = [session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._deserialize(row) for row in rows]

    def get_by_raw_observation_id(self, raw_id: int) -> list[dict[str, Any]]:
        """Get structured observations linked to a raw observation."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM structured_observations WHERE raw_observation_id = ?",
                (raw_id,),
            ).fetchall()

        return [self._deserialize(row) for row in rows]

    def get_dedup_links(self, structured_id: int) -> list[dict[str, Any]]:
        """Get soft dedup links for a structured observation.

        Returns all raw observations that were deduplicated into this
        structured observation.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, linked_raw_observation_id, linked_session_id,
                       content_hash, link_type, created_at
                FROM structured_observation_links
                WHERE existing_structured_id = ?
                ORDER BY created_at DESC
                """,
                (structured_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_linked_raw_observations(self, structured_id: int) -> list[int]:
        """Get all raw observation IDs linked to a structured observation.

        Includes the primary raw_observation_id and all dedup-linked ones.
        """
        with self._get_conn() as conn:
            primary = conn.execute(
                "SELECT raw_observation_id FROM structured_observations WHERE id = ?",
                (structured_id,),
            ).fetchone()

            links = conn.execute(
                "SELECT linked_raw_observation_id FROM structured_observation_links WHERE existing_structured_id = ?",
                (structured_id,),
            ).fetchall()

        result = []
        if primary and primary[0]:
            result.append(primary[0])
        result.extend([row[0] for row in links if row[0]])
        return result

    def get_for_injection(
        self,
        project: str,
        limit: int = 5,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get compact structured observations for context injection.

        Returns most relevant observations for the project.
        """
        sql = """
            SELECT id, session_id, type, title, narrative, concepts,
                   files_read, files_modified, created_at
            FROM structured_observations
            WHERE project = ?
        """
        params: list[Any] = [project]

        if types:
            placeholders = ",".join("?" * len(types))
            sql += f" AND type IN ({placeholders})"
            params.extend(types)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_fts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search over structured observations."""
        words = [w for w in query.strip().split() if len(w) > 2]
        if words:
            fts_query = f'"{query}" OR ' + " OR ".join(words) if len(words) > 1 else query
        else:
            fts_query = query

        with self._get_conn() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT so.*, snippet(structured_observations_fts, 0, '[', ']', '...', 32) as snippet
                    FROM structured_observations_fts
                    JOIN structured_observations so ON structured_observations_fts.rowid = so.id
                    WHERE structured_observations_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                return [self._deserialize(row) for row in rows]
            except Exception as e:
                logger.debug(f"FTS search failed: {e}")
                return []

    def search_by_concept(self, concept: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search by concept tag."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM structured_observations
                WHERE concepts LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f'%"{concept}"%', limit),
            ).fetchall()

        return [self._deserialize(row) for row in rows]

    def search_by_file(self, file_path: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search by file path in files_read or files_modified."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM structured_observations
                WHERE files_read LIKE ? OR files_modified LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f'%"{file_path}"%', f'%"{file_path}"%', limit),
            ).fetchall()

        return [self._deserialize(row) for row in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about structured observations."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM structured_observations"
            ).fetchone()[0]

            by_type = conn.execute(
                """
                SELECT type, COUNT(*) as count
                FROM structured_observations
                GROUP BY type
                ORDER BY count DESC
                """
            ).fetchall()

            by_source = conn.execute(
                """
                SELECT source, COUNT(*) as count
                FROM structured_observations
                GROUP BY source
                ORDER BY count DESC
                """
            ).fetchall()

            by_project = conn.execute(
                """
                SELECT project, COUNT(*) as count
                FROM structured_observations
                GROUP BY project
                ORDER BY count DESC
                LIMIT 10
                """
            ).fetchall()

        return {
            "total": total,
            "by_type": [dict(row) for row in by_type],
            "by_source": [dict(row) for row in by_source],
            "by_project": [dict(row) for row in by_project],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
        """Deserialize a database row into a dict with parsed JSON fields."""
        result = dict(row)
        for key in ("facts", "concepts", "files_read", "files_modified"):
            if result.get(key):
                try:
                    result[key] = json.loads(result[key])
                except json.JSONDecodeError:
                    result[key] = []
            else:
                result[key] = []
        return result
