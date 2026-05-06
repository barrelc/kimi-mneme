"""Vector storage using sqlite-vec for semantic similarity search."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from typing import Any

import numpy as np
from loguru import logger

from mneme.config import load_config
from mneme.db.schema import get_connection

# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

# Dimensionality for fallback dummy embeddings (matches all-MiniLM-L6-v2)
_FALLBACK_EMBEDDING_DIM = 384


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
                    cls._instance._has_sentence_transformers = None
        return cls._instance

    def _check_sentence_transformers(self) -> bool:
        if self._has_sentence_transformers is None:
            try:
                import sentence_transformers  # noqa: F401

                self._has_sentence_transformers = True
            except ImportError:
                self._has_sentence_transformers = False
        return self._has_sentence_transformers

    def _load(self, model_name: str) -> Any:
        if self._model is None or self._model_name != model_name:
            if not self._check_sentence_transformers():
                logger.warning(
                    "sentence-transformers not installed. "
                    "Using deterministic dummy embeddings. "
                    "Install with: pip install 'kimi-mneme[embeddings]'"
                )
                return None
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
            self._model_name = model_name
            logger.debug(f"Loaded embedding model: {model_name}")
        return self._model

    def encode(self, texts: list[str], model_name: str) -> np.ndarray:
        model = self._load(model_name)
        if model is not None:
            return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        # Fallback: deterministic dummy embeddings for CI/testing
        return _dummy_embeddings(texts)


def _dummy_embeddings(texts: list[str]) -> np.ndarray:
    """Generate deterministic normalized embeddings without ML libraries.

    Uses SHA-256 hashing to produce consistent pseudo-random vectors.
    Suitable for testing and CI where sentence-transformers is too heavy.
    """
    embeddings = np.zeros((len(texts), _FALLBACK_EMBEDDING_DIM), dtype=np.float32)
    for i, text in enumerate(texts):
        # Deterministic seed from text content
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        # Use seed bytes to fill the vector
        vec = np.frombuffer(seed, dtype=np.uint8).astype(np.float32)
        # Expand to 384 dims by repeating and slicing
        vec = np.resize(vec, _FALLBACK_EMBEDDING_DIM)
        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        embeddings[i] = vec
    return embeddings


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
# sqlite-vec (primary vector store, works everywhere)
# ---------------------------------------------------------------------------


class SQLiteVecStore:
    """Store and search structured observation embeddings via sqlite-vec.

    Uses field-level embeddings (title, narrative, facts) for fine-grained
    semantic search. Falls back gracefully if sqlite-vec is not available.

    IMPORTANT: sqlite-vec 0.1.x stores vec0 virtual table data IN-MEMORY
    per connection. We use a process-level singleton connection to ensure
    persistence across operations.
    """

    _VEC_TABLES = {
        "title": "vec_title",
        "narrative": "vec_narrative",
        "facts": "vec_facts",
    }
    _RAW_VEC_TABLE = "vec_raw_observations"

    # Process-level singleton connection to ensure vec0 data persists
    _singleton_conn: sqlite3.Connection | None = None
    _singleton_lock = threading.Lock()
    _singleton_db_path: str | None = None

    def __init__(self, db_path: str | None = None) -> None:
        config = load_config()
        self.db_path = db_path or config["db"]["path"]
        self.embedding_model = config["vector"]["embedding_model"]
        self._local = threading.local()
        self._vec_available = self._check_vec()
        # Track whether this instance "owns" the singleton (for cleanup in tests)
        self._owns_singleton = False

    def _check_vec(self) -> bool:
        """Check if sqlite-vec extension is available."""
        try:
            import importlib

            importlib.import_module("sqlite_vec")
            return True
        except ImportError:
            logger.warning(
                "sqlite-vec not installed. Semantic search via sqlite-vec disabled. "
                "Install with: pip install sqlite-vec"
            )
            return False

    def _get_conn(self) -> sqlite3.Connection:
        """Get singleton connection with vec extension loaded.

        Uses a process-level singleton because sqlite-vec 0.1.x stores
        vec0 data in-memory per connection. Creating a new connection
        loses all previously inserted embeddings.
        """
        # Fast path: check if singleton exists, matches db_path, and is open
        if (
            SQLiteVecStore._singleton_conn is not None
            and SQLiteVecStore._singleton_db_path == self.db_path
        ):
            # Verify connection is still open
            try:
                SQLiteVecStore._singleton_conn.execute("SELECT 1")
                return SQLiteVecStore._singleton_conn
            except Exception:
                # Connection was closed — reset and recreate
                SQLiteVecStore._singleton_conn = None
                SQLiteVecStore._singleton_db_path = None

        with SQLiteVecStore._singleton_lock:
            # Double-check after acquiring lock
            if (
                SQLiteVecStore._singleton_conn is not None
                and SQLiteVecStore._singleton_db_path == self.db_path
            ):
                try:
                    SQLiteVecStore._singleton_conn.execute("SELECT 1")
                    return SQLiteVecStore._singleton_conn
                except sqlite3.ProgrammingError:
                    SQLiteVecStore._singleton_conn = None
                    SQLiteVecStore._singleton_db_path = None

            # Create new singleton connection
            conn = get_connection(self.db_path)
            if self._vec_available:
                try:
                    import sqlite_vec

                    conn.enable_load_extension(True)
                    sqlite_vec.load(conn)
                    conn.enable_load_extension(False)
                    # Ensure vec virtual tables exist
                    self._ensure_vec_tables(conn)
                except Exception as e:
                    logger.warning(f"Failed to load sqlite-vec extension: {e}")
                    self._vec_available = False

            SQLiteVecStore._singleton_conn = conn
            SQLiteVecStore._singleton_db_path = self.db_path
            self._owns_singleton = True
            logger.debug(f"sqlite-vec: created singleton connection for {self.db_path}")
            return conn

    def set_conn(self, conn: sqlite3.Connection) -> None:
        """Use an existing connection (for sharing with StructuredObservationStore).

        NOTE: This replaces the singleton connection. Use with care.
        The caller owns the connection lifecycle — we won't close it.
        """
        with SQLiteVecStore._singleton_lock:
            # Don't close the old singleton — the caller manages their conn
            SQLiteVecStore._singleton_conn = conn
            SQLiteVecStore._singleton_db_path = self.db_path
            self._owns_singleton = False  # We don't own this connection
        if self._vec_available:
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                self._ensure_vec_tables(conn)
            except Exception as e:
                logger.warning(f"Failed to load sqlite-vec extension: {e}")

    @classmethod
    def release_singleton(cls) -> None:
        """Release the singleton connection to allow other processes access.

        sqlite-vec stores embeddings in-memory per connection, so this
        will lose recently added embeddings that haven't been persisted.
        Call this only after committing transactions.
        """
        with cls._singleton_lock:
            if cls._singleton_conn is not None:
                try:
                    cls._singleton_conn.commit()
                    cls._singleton_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    cls._singleton_conn.close()
                except Exception:
                    pass
                finally:
                    cls._singleton_conn = None
                    cls._singleton_db_path = None
                    cls._vec_available = False

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
            "vec_raw_observations": """
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_raw_observations USING vec0(
                    embedding float[384],
                    +observation_id INTEGER,
                    +session_id TEXT,
                    +event_type TEXT,
                    +tool_name TEXT,
                    partition_key TEXT
                )
            """,
        }
        for _name, sql in tables.items():
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
            conn.commit()
            logger.debug(f"sqlite-vec: added {count} embeddings for so_{structured_id}")
        return count

    def add_raw_observation(
        self,
        observation_id: int,
        session_id: str,
        content: str,
        event_type: str = "",
        tool_name: str = "",
        project: str = "",
    ) -> bool:
        """Add a raw observation embedding to sqlite-vec.

        Adds a raw observation embedding for semantic search.

        Returns:
            True if added successfully.
        """
        if not self._vec_available or not content:
            return False

        conn = self._get_conn()
        try:
            emb = self._encode([content])[0]
            conn.execute(
                """
                INSERT INTO vec_raw_observations(embedding, observation_id, session_id, event_type, tool_name, partition_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (emb, observation_id, session_id, event_type, tool_name or "", project or ""),
            )
            conn.commit()
            logger.debug(f"sqlite-vec: added raw observation {observation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add raw observation vec: {e}")
            return False

    def search_raw(
        self,
        query: str,
        project: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search over raw observations.

        Semantic search over raw observations.

        Returns:
            List of results with observation_id, session_id, event_type, tool_name, distance.
        """
        if not self._vec_available:
            return []

        conn = self._get_conn()
        query_emb = self._encode([query])[0]

        try:
            if project:
                sql = """
                    SELECT observation_id, session_id, event_type, tool_name, distance
                    FROM vec_raw_observations
                    WHERE embedding MATCH ? AND k = ? AND partition_key = ?
                """
                params = (query_emb, limit, project)
            else:
                sql = """
                    SELECT observation_id, session_id, event_type, tool_name, distance
                    FROM vec_raw_observations
                    WHERE embedding MATCH ? AND k = ?
                """
                params = (query_emb, limit)

            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "observation_id": row["observation_id"],
                        "session_id": row["session_id"],
                        "event_type": row["event_type"],
                        "tool_name": row["tool_name"],
                        "distance": row["distance"],
                    }
                )
            return results
        except Exception as e:
            logger.error(f"sqlite-vec raw search failed: {e}")
            return []

    def delete_raw_by_session(self, session_id: str) -> int:
        """Delete all raw observation vectors for a session.

        Returns:
            Number of embeddings deleted.
        """
        if not self._vec_available:
            return 0

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM vec_raw_observations WHERE session_id = ?",
                (session_id,),
            )
            count = cursor.rowcount
            if count:
                conn.commit()
            return count
        except Exception as e:
            logger.error(f"Failed to delete raw vectors: {e}")
            return 0

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
                    results.append(
                        {
                            "structured_id": row["structured_id"],
                            "session_id": row["session_id"],
                            "field": field,
                            "distance": row["distance"],
                        }
                    )
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
        if total:
            conn.commit()
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
        conn.commit()

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
            logger.info(
                f"sqlite-vec sync: {total} embeddings for {len(observations)} observations (id > {last_id})"
            )
        return total
