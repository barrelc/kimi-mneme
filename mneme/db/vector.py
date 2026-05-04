"""Vector storage using ChromaDB for semantic similarity search."""

from __future__ import annotations

import sys
from typing import Any

from loguru import logger

from mneme.config import load_config

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
                "Vector search disabled. Install chromadb<1.0 to enable."
            )
        return broken
    except Exception:
        return False


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
                            "session_id": results["metadatas"][0][i].get("session_id"),
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
