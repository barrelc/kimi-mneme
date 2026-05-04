"""Storage for Knowledge Collections (аналог Knowledge Corpora)."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from loguru import logger

from mneme.config import load_config
from mneme.db.schema import get_connection
from mneme.db.structured_store import StructuredObservationStore


class CollectionsStore:
    """Store and manage Knowledge Collections."""

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = get_connection(self.db_path)
        return self._local.conn

    def _close_conn(self) -> None:
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

    def create(
        self,
        name: str,
        description: str | None = None,
        project: str | None = None,
        query: str | None = None,
        types: list[str] | None = None,
        concepts: list[str] | None = None,
        files: list[str] | None = None,
    ) -> int:
        """Create a new collection. Returns collection ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO observation_collections
            (name, description, project, query, types, concepts, files)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                name,
                description,
                project,
                query,
                json.dumps(types or [], ensure_ascii=False),
                json.dumps(concepts or [], ensure_ascii=False),
                json.dumps(files or [], ensure_ascii=False),
            ),
        )
        row = cursor.fetchone()
        coll_id = row[0] if row else 0
        conn.commit()
        self._close_conn()

        if coll_id and query:
            # Auto-populate from query
            self._auto_populate(coll_id, query, project, types, concepts, files)

        logger.info(f"Collection created: {name} (id={coll_id})")
        return coll_id

    def _auto_populate(
        self,
        coll_id: int,
        query: str | None,
        project: str | None,
        types: list[str] | None,
        concepts: list[str] | None,
        files: list[str] | None,
    ) -> int:
        """Auto-populate collection from search criteria."""
        store = StructuredObservationStore(db_path=self.db_path)

        # Build search results
        results: list[dict[str, Any]] = []

        if query:
            results.extend(store.search_fts(query, limit=100))

        # Filter by criteria
        filtered = []
        for obs in results:
            if project and obs.get("project") != project:
                continue
            if types and obs.get("type") not in types:
                continue
            if concepts:
                obs_concepts = obs.get("concepts", [])
                if not any(c in obs_concepts for c in concepts):
                    continue
            if files:
                obs_files = (obs.get("files_read", []) + obs.get("files_modified", []))
                if not any(f in " ".join(obs_files) for f in files):
                    continue
            filtered.append(obs)

        # Add to collection
        count = 0
        conn = self._get_conn()
        for obs in filtered:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO collection_items (collection_id, structured_id) VALUES (?, ?)",
                    (coll_id, obs["id"]),
                )
                count += 1
            except Exception:
                pass
        conn.commit()
        self._close_conn()

        logger.info(f"Auto-populated collection {coll_id} with {count} items")
        return count

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        """Get collection by name with items."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM observation_collections WHERE name = ?",
            (name,),
        ).fetchone()
        self._close_conn()

        if not row:
            return None

        result = dict(row)
        result["types"] = json.loads(result.get("types") or "[]")
        result["concepts"] = json.loads(result.get("concepts") or "[]")
        result["files"] = json.loads(result.get("files") or "[]")
        result["items"] = self._get_items(result["id"])
        return result

    def get_by_id(self, coll_id: int) -> dict[str, Any] | None:
        """Get collection by ID with items."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM observation_collections WHERE id = ?",
            (coll_id,),
        ).fetchone()
        self._close_conn()

        if not row:
            return None

        result = dict(row)
        result["types"] = json.loads(result.get("types") or "[]")
        result["concepts"] = json.loads(result.get("concepts") or "[]")
        result["files"] = json.loads(result.get("files") or "[]")
        result["items"] = self._get_items(coll_id)
        return result

    def _get_items(self, coll_id: int) -> list[dict[str, Any]]:
        """Get structured observations in a collection."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT so.* FROM structured_observations so
            JOIN collection_items ci ON so.id = ci.structured_id
            WHERE ci.collection_id = ?
            ORDER BY ci.added_at DESC
            """,
            (coll_id,),
        ).fetchall()
        self._close_conn()

        store = StructuredObservationStore(db_path=self.db_path)
        return [store._deserialize(row) for row in rows]

    def list_collections(self, project: str | None = None) -> list[dict[str, Any]]:
        """List all collections with item counts."""
        conn = self._get_conn()
        if project:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(ci.structured_id) as item_count
                FROM observation_collections c
                LEFT JOIN collection_items ci ON c.id = ci.collection_id
                WHERE c.project = ?
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """,
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(ci.structured_id) as item_count
                FROM observation_collections c
                LEFT JOIN collection_items ci ON c.id = ci.collection_id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        self._close_conn()

        results = []
        for row in rows:
            d = dict(row)
            d["types"] = json.loads(d.get("types") or "[]")
            d["concepts"] = json.loads(d.get("concepts") or "[]")
            d["files"] = json.loads(d.get("files") or "[]")
            results.append(d)
        return results

    def update(
        self,
        name: str,
        description: str | None = None,
        project: str | None = None,
        query: str | None = None,
        types: list[str] | None = None,
        concepts: list[str] | None = None,
        files: list[str] | None = None,
    ) -> bool:
        """Update collection metadata."""
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE observation_collections
            SET description = ?, project = ?, query = ?, types = ?, concepts = ?, files = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
            """,
            (
                description,
                project,
                query,
                json.dumps(types or [], ensure_ascii=False),
                json.dumps(concepts or [], ensure_ascii=False),
                json.dumps(files or [], ensure_ascii=False),
                name,
            ),
        )
        conn.commit()
        self._close_conn()
        logger.info(f"Collection updated: {name}")
        return True

    def delete(self, name: str) -> bool:
        """Delete collection (cascades to items)."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM observation_collections WHERE name = ?",
            (name,),
        )
        conn.commit()
        self._close_conn()
        logger.info(f"Collection deleted: {name}")
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def add_item(self, collection_name: str, structured_id: int) -> bool:
        """Add a structured observation to a collection."""
        coll = self.get_by_name(collection_name)
        if not coll:
            return False

        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO collection_items (collection_id, structured_id) VALUES (?, ?)",
            (coll["id"], structured_id),
        )
        conn.commit()
        self._close_conn()
        return True

    def remove_item(self, collection_name: str, structured_id: int) -> bool:
        """Remove a structured observation from a collection."""
        coll = self.get_by_name(collection_name)
        if not coll:
            return False

        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM collection_items WHERE collection_id = ? AND structured_id = ?",
            (coll["id"], structured_id),
        )
        conn.commit()
        self._close_conn()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_markdown(self, name: str) -> str:
        """Export collection as markdown."""
        coll = self.get_by_name(name)
        if not coll:
            return ""

        lines = [
            f"# {coll['name']}",
            "",
        ]
        if coll.get("description"):
            lines.append(coll["description"])
            lines.append("")

        lines.append(f"*Project: {coll.get('project', 'N/A')} | {len(coll['items'])} observations*")
        lines.append("")

        type_emoji = {
            "bugfix": "🐛",
            "feature": "✨",
            "refactor": "♻️",
            "change": "📝",
            "discovery": "🔍",
            "decision": "🎯",
        }

        for obs in coll["items"]:
            obs_type = obs.get("type", "discovery")
            emoji = type_emoji.get(obs_type, "•")
            title = obs.get("title", "Untitled")
            narrative = obs.get("narrative", "")

            lines.append(f"### {emoji} {title}")
            if narrative:
                lines.append(narrative)

            facts = obs.get("facts", [])
            for fact in facts[:3]:
                lines.append(f"- {fact}")

            files = (obs.get("files_modified", []) + obs.get("files_read", []))[:3]
            if files:
                lines.append(f"**Files:** {', '.join(files)}")
            lines.append("")

        lines.append("---")
        lines.append(f"*Generated by kimi-mneme | Collection: {name}*")

        return "\n".join(lines)

    def export_json(self, name: str) -> dict[str, Any]:
        """Export collection as JSON."""
        coll = self.get_by_name(name)
        if not coll:
            return {}
        return {
            "name": coll["name"],
            "description": coll.get("description"),
            "project": coll.get("project"),
            "items": coll["items"],
            "item_count": len(coll["items"]),
        }

    def export_plain(self, name: str) -> str:
        """Export collection as plain text for context injection."""
        coll = self.get_by_name(name)
        if not coll:
            return ""

        lines = [f"## {coll['name']}"]
        if coll.get("description"):
            lines.append(coll["description"])

        for obs in coll["items"][:10]:
            lines.append(f"- [{obs.get('type', '?')}] {obs.get('title', 'Untitled')}")
            if obs.get("narrative"):
                lines.append(f"  {obs['narrative']}")

        return "\n".join(lines)

    def query_collection(
        self,
        name: str,
        question: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Query a collection by semantic similarity to a question.

        Uses sqlite-vec to find the most relevant observations in the collection.
        Returns matching items with relevance scores.
        """
        coll = self.get_by_name(name)
        if not coll:
            return {"error": f"Collection '{name}' not found", "results": []}

        items = coll.get("items", [])
        if not items:
            return {"collection": name, "results": [], "question": question}

        # If sqlite-vec is available, use semantic search
        try:
            from mneme.db.vector import _encode_texts

            # Encode question
            q_embeddings = _encode_texts([question], model_name=None)
            if not q_embeddings or len(q_embeddings) == 0:
                raise ValueError("Failed to encode question")
            q_emb = q_embeddings[0]

            # Encode all items (title + narrative)
            item_texts = []
            for obs in items:
                text = " ".join(filter(None, [
                    obs.get("title", ""),
                    obs.get("narrative", ""),
                    " ".join(obs.get("facts", [])),
                ]))
                item_texts.append(text)

            item_embeddings = _encode_texts(item_texts, model_name=None)

            # Compute cosine similarities
            import numpy as np

            q_norm = q_emb / (np.linalg.norm(q_emb) + 1e-8)
            scores = []
            for emb in item_embeddings:
                emb_norm = emb / (np.linalg.norm(emb) + 1e-8)
                sim = float(np.dot(q_norm, emb_norm))
                scores.append(sim)

            # Sort by score descending
            indexed = list(enumerate(scores))
            indexed.sort(key=lambda x: x[1], reverse=True)

            results = []
            for idx, score in indexed[:limit]:
                obs = items[idx]
                results.append({
                    "observation": obs,
                    "relevance": round(score, 4),
                    "rank": len(results) + 1,
                })

            return {
                "collection": name,
                "question": question,
                "results": results,
                "total_items": len(items),
                "method": "semantic",
            }

        except Exception as e:
            logger.debug(f"Semantic query failed, falling back to keyword: {e}")
            # Fallback: simple keyword matching
            q_lower = question.lower()
            scored = []
            for obs in items:
                text = " ".join(filter(None, [
                    obs.get("title", ""),
                    obs.get("narrative", ""),
                    " ".join(obs.get("facts", [])),
                    " ".join(obs.get("concepts", [])),
                ])).lower()
                score = 0
                for word in q_lower.split():
                    if len(word) > 2:
                        score += text.count(word)
                if score > 0:
                    scored.append((obs, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            results = [
                {"observation": obs, "relevance": score, "rank": i + 1, "method": "keyword"}
                for i, (obs, score) in enumerate(scored[:limit])
            ]

            return {
                "collection": name,
                "question": question,
                "results": results,
                "total_items": len(items),
                "method": "keyword",
            }
