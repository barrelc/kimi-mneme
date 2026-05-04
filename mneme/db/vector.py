"""Vector storage using ChromaDB or sqlite-vec for semantic similarity search."""

from __future__ import annotations

import struct
import sys
import threading
from typing import Any

import numpy as np
from loguru import logger

from mneme.config import load_config
from mneme.db.schema import get_connection

_CHROMA_BROKEN_WARNED = False


def _is_chroma_broken_on_windows() -> bool:
    """Check if chromadb >= 1.0 on Windows has known segfault issues."""
    global _CHROMA_BROKEN_WARNED
    if sys.platform != "win32":
        return False
    try:
        import chromadb

        version = getattr(chromadb, "__version__", "0")
        major = int(version.split(".")[0])
        broken = major >= 1
        if broken and not _CHROMA_BROKEN_WARNED:
            _CHROMA_BROKEN_WARNED = True
            logger.warning(
                "ChromaDB >= 1.0 on Windows has known stability issues (segfault). "
                "Falling back to sqlite-vec for vector search."
            )
        return broken
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

class _EmbeddingCache:
    """Lazy-loaded sentence-transformers model with caching."""

    _instance: _EmbeddingCache | None = None
    _lock = threading.Lock()

    def __new__(cls) -> _EmbeddingCache:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
                    cls._instance._model_name = None
        return cls._instance

    def _load(self, model_name: str) -> Any:
        if self._model is None or self._model_name != model_name:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
                self._model_name = model_name
                logger.debug(f"Loaded embedding model: {model_name}")
            except ImportError:
                logger.error(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
                raise
        return self._model

    def encode(self, texts: list[str], model_name: str) -> np.ndarray:
        model = self._load(model_name)
        return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)


def _encode_texts(texts: list[str], model_name: str | None = None) -> np.ndarray:
    """Encode texts to normalized float32 embeddings."""
    config = load_config()
    model = model_name or config["vector"]["embedding_model"]
    cache = _EmbeddingCache()
    return cache.encode(texts, model)


def _numpy_to_blob(embedding: np.ndarray) -> bytes:
    """Convert numpy float32 array to sqlite-vec blob."""
    return embedding.astype(np.float32).tobytes()


# ---------------------------------------------------------------------------
# ChromaDB (legacy, disabled on Windows >= 1.0)
# ---------------------------------------------------------------------------

class VectorStore:
    """Store and search observation embeddings via ChromaDB."""

    def __init__(self, persist_dir: str | None = None) -> None:
        config = load_config()
        self.persist_dir = persist_dir or config["vector"]["path"]
        self.embedding_model = config["vector"]["embedding_model"]
        self._client: Any = None
        self._collection: Any = None
        self._embedding_fn: Any = None
        self._disabled = _is_chroma_broken_on_windows()

    def _get_client(self) -> Any:
        """Lazy-init Chroma client."""
        if self._disabled:
            return None
        if self._client is None:
            try:
                import chromadb
                from chromadb.utils import embedding_functions

                self._client = chromadb.PersistentClient(path=self.persist_dir)
                self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=self.embedding_model
                )
                self._collection = self._client.get_or_create_collection(
                    name="mneme_observations",
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.debug(f"Chroma client initialized at {self.persist_dir}")
            except ImportError:
                logger.warning(
                    "chromadb not installed. Vector search disabled. "
                    "Install with: pip install chromadb sentence-transformers"
                )
                return None
            except Exception as e:
                logger.error(f"Failed to initialize Chroma: {e}")
                return None
        return self._client

    def add(
        self,
        observation_id: int,
        session_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Add an observation embedding to the vector store.

        Returns:
            embedding_id or None if disabled/failed.
        """
        client = self._get_client()
        if client is None or self._collection is None:
            return None

        embedding_id = f"obs_{observation_id}_{session_id}"
        meta = {
            "session_id": session_id,
            "observation_id": observation_id,
        }
        if metadata:
            meta.update(metadata)

        try:
            self._collection.add(
                ids=[embedding_id],
                documents=[content],
                metadatas=[meta],
            )
            logger.debug(f"Vector added: {embedding_id}")
            return embedding_id
        except Exception as e:
            logger.error(f"Failed to add vector: {e}")
            return None

    def add_structured_fields(
        self,
        structured_id: int,
        session_id: str,
        title: str,
        narrative: str | None,
        facts: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Add field-level embeddings for structured observation.

        Creates separate embeddings for title, narrative, and each fact
        for fine-grained semantic search.

        Returns:
            List of embedding_ids that were added.
        """
        client = self._get_client()
        if client is None or self._collection is None:
            return []

        added_ids: list[str] = []
        base_meta = {
            "session_id": session_id,
            "structured_id": structured_id,
            "source": "structured",
        }
        if metadata:
            base_meta.update(metadata)

        # Title embedding
        if title:
            try:
                tid = f"so_{structured_id}_title"
                self._collection.add(
                    ids=[tid],
                    documents=[title],
                    metadatas=[{**base_meta, "field": "title"}],
                )
                added_ids.append(tid)
            except Exception as e:
                logger.error(f"Failed to add title vector: {e}")

        # Narrative embedding
        if narrative:
            try:
                nid = f"so_{structured_id}_narrative"
                self._collection.add(
                    ids=[nid],
                    documents=[narrative],
                    metadatas=[{**base_meta, "field": "narrative"}],
                )
                added_ids.append(nid)
            except Exception as e:
                logger.error(f"Failed to add narrative vector: {e}")

        # Fact embeddings
        for i, fact in enumerate(facts):
            if not fact:
                continue
            try:
                fid = f"so_{structured_id}_fact_{i}"
                self._collection.add(
                    ids=[fid],
                    documents=[fact],
                    metadatas=[{**base_meta, "field": "fact", "fact_index": i}],
                )
                added_ids.append(fid)
            except Exception as e:
                logger.error(f"Failed to add fact vector: {e}")

        if added_ids:
            logger.debug(f"Structured vectors added: {len(added_ids)} fields for so_{structured_id}")
        return added_ids

    def search(
        self,
        query: str,
        limit: int = 10,
        filter_dict: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over observations.

        Returns:
            List of results with id, distance, document, metadata.
        """
        client = self._get_client()
        if client is None or self._collection is None:
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(limit, 100),
                where=filter_dict,
                include=["metadatas", "documents", "distances"],
            )

            output = []
            if results["ids"] and results["ids"][0]:
                for i, embedding_id in enumerate(results["ids"][0]):
                    output.append(
                        {
                            "embedding_id": embedding_id,
                            "observation_id": results["metadatas"][0][i].get("observation_id"),
                            "structured_id": results["metadatas"][0][i].get("structured_id"),
                            "session_id": results["metadatas"][0][i].get("session_id"),
                            "field": results["metadatas"][0][i].get("field"),
                            "distance": results["distances"][0][i],
                            "snippet": (
                                results["documents"][0][i][:200] + "..."
                                if len(results["documents"][0][i]) > 200
                                else results["documents"][0][i]
                            ),
                        }
                    )
            return output

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def delete_by_session(self, session_id: str) -> bool:
        """Delete all vectors for a session."""
        client = self._get_client()
        if client is None or self._collection is None:
            return False

        try:
            self._collection.delete(where={"session_id": session_id})
            logger.debug(f"Vectors deleted for session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete vectors: {e}")
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get vector store statistics."""
        client = self._get_client()
        if client is None or self._collection is None:
            return {"enabled": False, "count": 0}

        try:
            count = self._collection.count()
            return {"enabled": True, "count": count}
        except Exception as e:
            logger.error(f"Failed to get vector stats: {e}")
            return {"enabled": True, "count": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# sqlite-vec (lightweight alternative, works everywhere)
# ---------------------------------------------------------------------------

class SQLiteVecStore:
    """Store and search structured observation embeddings via sqlite-vec.

    Uses field-level embeddings (title, narrative, facts) for fine-grained
    semantic search. Falls back gracefully if sqlite-vec is not available.
    """

    _VEC_TABLES = {
        "title": "vec_title",
        "narrative": "vec_narrative",
        "facts": "vec_facts",
    }

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self.embedding_model = config["vector"]["embedding_model"]
        self._local = threading.local()
        self._vec_available = self._check_vec()

    def _check_vec(self) -> bool:
        """Check if sqlite-vec extension is available."""
        try:
            import sqlite_vec

            return True
        except ImportError:
            logger.warning(
                "sqlite-vec not installed. Semantic search via sqlite-vec disabled. "
                "Install with: pip install sqlite-vec"
            )
            return False

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection with vec extension loaded."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = get_connection(self.db_path)
            if self._vec_available:
                try:
                    import sqlite_vec

                    conn.enable_load_extension(True)
                    sqlite_vec.load(conn)
                    # Ensure vec virtual tables exist
                    self._ensure_vec_tables(conn)
                except Exception as e:
                    logger.warning(f"Failed to load sqlite-vec extension: {e}")
                    self._vec_available = False
            self._local.conn = conn
        return self._local.conn

    def set_conn(self, conn: sqlite3.Connection) -> None:
        """Use an existing connection (for sharing with StructuredObservationStore)."""
        self._local.conn = conn
        if self._vec_available:
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                self._ensure_vec_tables(conn)
            except Exception as e:
                logger.warning(f"Failed to load sqlite-vec extension: {e}")
                self._vec_available = False

    def _ensure_vec_tables(self, conn: sqlite3.Connection) -> None:
        """Create vec0 virtual tables if they don't exist."""
        import sqlite3

        tables = {
            "vec_title": """
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_title USING vec0(
                    embedding float[384],
                    +structured_id INTEGER,
                    +session_id TEXT,
                    +project TEXT,
                    partition_key TEXT
                )
            """,
            "vec_narrative": """
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_narrative USING vec0(
                    embedding float[384],
                    +structured_id INTEGER,
                    +session_id TEXT,
                    +project TEXT,
                    partition_key TEXT
                )
            """,
            "vec_facts": """
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts USING vec0(
                    embedding float[384],
                    +structured_id INTEGER,
                    +session_id TEXT,
                    +project TEXT,
                    +fact_index INTEGER,
                    partition_key TEXT
                )
            """,
        }
        for name, sql in tables.items():
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                if "already exists" in str(e):
                    pass
                else:
                    raise

    def _encode(self, texts: list[str]) -> list[bytes]:
        """Encode texts to sqlite-vec blobs."""
        embeddings = _encode_texts(texts, self.embedding_model)
        return [_numpy_to_blob(emb) for emb in embeddings]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_structured_fields(
        self,
        structured_id: int,
        session_id: str,
        project: str,
        title: str,
        narrative: str | None,
        facts: list[str],
    ) -> int:
        """Add field-level embeddings for a structured observation.

        Returns:
            Number of embeddings added.
        """
        if not self._vec_available:
            return 0

        conn = self._get_conn()
        count = 0

        # Title
        if title:
            try:
                emb = self._encode([title])[0]
                conn.execute(
                    """
                    INSERT INTO vec_title(embedding, structured_id, session_id, project, partition_key)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (emb, structured_id, session_id, project, project),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to add title vec: {e}")

        # Narrative
        if narrative:
            try:
                emb = self._encode([narrative])[0]
                conn.execute(
                    """
                    INSERT INTO vec_narrative(embedding, structured_id, session_id, project, partition_key)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (emb, structured_id, session_id, project, project),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to add narrative vec: {e}")

        # Facts
        for i, fact in enumerate(facts):
            if not fact:
                continue
            try:
                emb = self._encode([fact])[0]
                conn.execute(
                    """
                    INSERT INTO vec_facts(embedding, structured_id, session_id, project, fact_index, partition_key)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (emb, structured_id, session_id, project, i, project),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to add fact vec: {e}")

        if count:
            logger.debug(f"sqlite-vec: added {count} embeddings for so_{structured_id}")
        return count

    def sync_batch(
        self,
        observations: list[dict[str, Any]],
    ) -> int:
        """Sync a batch of structured observations into vec tables.

        Args:
            observations: List of dicts with keys:
                id, session_id, project, title, narrative, facts (list)

        Returns:
            Total number of embeddings added.
        """
        if not self._vec_available:
            return 0

        total = 0
        for obs in observations:
            total += self.add_structured_fields(
                structured_id=obs["id"],
                session_id=obs["session_id"],
                project=obs["project"],
                title=obs.get("title", ""),
                narrative=obs.get("narrative"),
                facts=obs.get("facts") or [],
            )
        return total

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        project: str | None = None,
        limit: int = 10,
        fields: list[str] | None = None,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across structured observation fields.

        Args:
            query: Search query text.
            project: Optional project filter (uses partition_key).
            limit: Max results per field.
            fields: Which fields to search ('title', 'narrative', 'facts').
                    Defaults to all.
            days: Optional recency filter — only observations from last N days.

        Returns:
            List of results with structured_id, field, distance, snippet.
        """
        if not self._vec_available:
            return []

        conn = self._get_conn()
        query_emb = self._encode([query])[0]
        search_fields = fields or list(self._VEC_TABLES.keys())
        results: list[dict[str, Any]] = []

        for field in search_fields:
            table = self._VEC_TABLES.get(field)
            if not table:
                continue

            try:
                if project and days:
                    # Filter by project + recency via JOIN with structured_observations
                    sql = f"""
                        SELECT v.structured_id, v.session_id, v.distance
                        FROM {table} AS v
                        JOIN structured_observations so ON v.structured_id = so.id
                        WHERE v.embedding MATCH ? AND v.k = ? AND v.partition_key = ?
                          AND so.created_at > datetime('now', '-{days} days')
                    """
                    params = (query_emb, limit, project)
                elif project:
                    sql = f"""
                        SELECT structured_id, session_id, distance
                        FROM {table}
                        WHERE embedding MATCH ? AND k = ? AND partition_key = ?
                    """
                    params = (query_emb, limit, project)
                elif days:
                    sql = f"""
                        SELECT v.structured_id, v.session_id, v.distance
                        FROM {table} AS v
                        JOIN structured_observations so ON v.structured_id = so.id
                        WHERE v.embedding MATCH ? AND v.k = ?
                          AND so.created_at > datetime('now', '-{days} days')
                    """
                    params = (query_emb, limit)
                else:
                    sql = f"""
                        SELECT structured_id, session_id, distance
                        FROM {table}
                        WHERE embedding MATCH ? AND k = ?
                    """
                    params = (query_emb, limit)

                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    results.append({
                        "structured_id": row["structured_id"],
                        "session_id": row["session_id"],
                        "field": field,
                        "distance": row["distance"],
                    })
            except Exception as e:
                logger.error(f"sqlite-vec search failed on {table}: {e}")

        # Sort by distance (cosine similarity, lower is better)
        results.sort(key=lambda x: x["distance"])
        return results[:limit]

    def search_with_content(
        self,
        query: str,
        project: str | None = None,
        limit: int = 10,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search that joins with structured_observations for full content.

        Args:
            days: Optional recency filter — only observations from last N days.

        Returns:
            Results with full observation data + distance + matched_field.
        """
        if not self._vec_available:
            return []

        # First get semantic matches
        matches = self.search(query, project=project, limit=limit * 3, days=days)
        if not matches:
            return []

        # Deduplicate by structured_id, keeping best distance
        best: dict[int, dict[str, Any]] = {}
        for m in matches:
            sid = m["structured_id"]
            if sid not in best or m["distance"] < best[sid]["distance"]:
                best[sid] = m

        # Fetch full content
        conn = self._get_conn()
        structured_ids = list(best.keys())
        placeholders = ",".join("?" * len(structured_ids))

        try:
            rows = conn.execute(
                f"""
                SELECT id, session_id, project, type, title, subtitle, narrative,
                       facts, concepts, files_read, files_modified, created_at
                FROM structured_observations
                WHERE id IN ({placeholders})
                """,
                structured_ids,
            ).fetchall()
        except Exception as e:
            logger.error(f"Failed to fetch observation content: {e}")
            return []

        import json

        output = []
        for row in rows:
            sid = row["id"]
            match = best[sid]
            result = dict(row)
            for key in ("facts", "concepts", "files_read", "files_modified"):
                try:
                    result[key] = json.loads(result[key]) if result[key] else []
                except (json.JSONDecodeError, TypeError):
                    result[key] = []
            result["distance"] = match["distance"]
            result["matched_field"] = match["field"]
            output.append(result)

        output.sort(key=lambda x: x["distance"])
        return output[:limit]

    def delete_by_session(self, session_id: str) -> int:
        """Delete all vectors for a session. Returns count deleted."""
        if not self._vec_available:
            return 0

        conn = self._get_conn()
        total = 0
        for table in self._VEC_TABLES.values():
            try:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ?",
                    (session_id,),
                )
                total += cursor.rowcount
            except Exception as e:
                logger.error(f"Failed to delete from {table}: {e}")
        return total

    def get_stats(self) -> dict[str, Any]:
        """Get sqlite-vec statistics."""
        if not self._vec_available:
            return {"enabled": False, "backend": "sqlite-vec", "counts": {}}

        conn = self._get_conn()
        counts = {}
        for name, table in self._VEC_TABLES.items():
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[name] = row[0] if row else 0
            except Exception as e:
                counts[name] = 0
                logger.debug(f"Failed to count {table}: {e}")

        return {
            "enabled": True,
            "backend": "sqlite-vec",
            "counts": counts,
            "total": sum(counts.values()),
        }

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def get_sync_state(self) -> dict[str, Any]:
        """Get last sync state for structured_observations."""
        if not self._vec_available:
            return {"last_synced_id": 0}

        conn = self._get_conn()
        row = conn.execute(
            "SELECT last_synced_id, synced_at FROM vec_sync_state WHERE table_name = ?",
            ("structured_observations",),
        ).fetchone()
        return {
            "last_synced_id": row["last_synced_id"] if row else 0,
            "synced_at": row["synced_at"] if row else None,
        }

    def update_sync_state(self, last_id: int) -> None:
        """Update sync watermark."""
        if not self._vec_available:
            return

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO vec_sync_state (table_name, last_synced_id, synced_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(table_name) DO UPDATE SET
                last_synced_id = excluded.last_synced_id,
                synced_at = excluded.synced_at
            """,
            ("structured_observations", last_id),
        )

    def sync_pending(self, batch_size: int = 100) -> int:
        """Sync all pending structured observations to vec tables.

        Returns:
            Number of embeddings added.
        """
        if not self._vec_available:
            return 0

        conn = self._get_conn()
        state = self.get_sync_state()
        last_id = state["last_synced_id"]

        rows = conn.execute(
            """
            SELECT id, session_id, project, title, narrative, facts
            FROM structured_observations
            WHERE id > ?
            ORDER BY id
            LIMIT ?
            """,
            (last_id, batch_size),
        ).fetchall()

        if not rows:
            return 0

        import json

        observations = []
        max_id = last_id
        for row in rows:
            obs = dict(row)
            if obs.get("facts"):
                try:
                    obs["facts"] = json.loads(obs["facts"])
                except json.JSONDecodeError:
                    obs["facts"] = []
            observations.append(obs)
            max_id = max(max_id, obs["id"])

        total = self.sync_batch(observations)
        self.update_sync_state(max_id)

        if total:
            logger.info(f"sqlite-vec sync: {total} embeddings for {len(observations)} observations (id > {last_id})")
        return total
