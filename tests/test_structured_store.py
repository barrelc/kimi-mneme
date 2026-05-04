"""Tests for StructuredObservationStore."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

import pytest

from mneme.core.prompts.json_parser import ParsedObservation
from mneme.db.schema import init_db
from mneme.db.structured_store import StructuredObservationStore


@pytest.fixture
def temp_db():
    """Create a temporary database with a session."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    # Create a session for foreign key constraints
    from mneme.db.store import ObservationStore

    store = ObservationStore(db_path=db_path)
    store.add_session("sess_1", "/home/user/myproject")
    store.add_session("sess_a", "/home/user/proj")
    yield db_path
    # Windows: connection may still be open, ignore unlink errors
    with contextlib.suppress(PermissionError):
        Path(db_path).unlink(missing_ok=True)


class TestStructuredObservationStore:
    def test_add_and_get(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="feature",
            title="Added new API endpoint",
            subtitle="POST /api/v1/users",
            facts=["Created UserController", "Added validation middleware"],
            narrative="Implemented user registration endpoint",
            concepts=["api-design", "validation"],
            files_read=["docs/api.md"],
            files_modified=["src/users.py", "src/routes.py"],
            source="ai",
        )
        obs_id = store.add_structured(obs, session_id="sess_1", project="myapp", source="ai")
        assert obs_id > 0

        retrieved = store.get_by_id(obs_id)
        assert retrieved is not None
        assert retrieved["title"] == "Added new API endpoint"
        assert retrieved["type"] == "feature"
        assert retrieved["facts"] == ["Created UserController", "Added validation middleware"]
        assert retrieved["concepts"] == ["api-design", "validation"]

    def test_deduplication(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="bugfix",
            title="Fixed null pointer",
            subtitle=None,
            facts=["Added null check"],
            narrative=None,
            concepts=[],
            files_read=[],
            files_modified=["src/main.py"],
            source="heuristic",
        )
        id1 = store.add_structured(obs, session_id="sess_1", project="myapp", source="heuristic")
        id2 = store.add_structured(obs, session_id="sess_1", project="myapp", source="heuristic")
        assert id1 > 0
        assert id2 == 0  # deduplicated

    def test_get_by_session(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        for i in range(3):
            obs = ParsedObservation(
                type="discovery",
                title=f"Discovery {i}",
                subtitle=None,
                facts=[],
                narrative=None,
                concepts=[],
                files_read=[],
                files_modified=[],
                source="heuristic",
            )
            store.add_structured(obs, session_id="sess_a", project="proj", source="heuristic")

        results = store.get_by_session("sess_a")
        assert len(results) == 3

    def test_get_for_injection(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="decision",
            title="Use SQLite for local storage",
            subtitle=None,
            facts=["No external dependencies needed"],
            narrative="Chose SQLite over PostgreSQL",
            concepts=["architecture"],
            files_read=[],
            files_modified=["docs/arch.md"],
            source="ai",
        )
        store.add_structured(obs, session_id="sess_1", project="kimi-mneme", source="ai")

        results = store.get_for_injection(project="kimi-mneme", limit=5)
        assert len(results) == 1
        assert results[0]["title"] == "Use SQLite for local storage"

    def test_search_by_concept(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="refactor",
            title="Refactored auth module",
            subtitle=None,
            facts=["Extracted JWT logic"],
            narrative=None,
            concepts=["jwt", "auth", "refactoring"],
            files_read=[],
            files_modified=["src/auth.py"],
            source="ai",
        )
        store.add_structured(obs, session_id="sess_1", project="myapp", source="ai")

        results = store.search_by_concept("jwt")
        assert len(results) == 1

    def test_stats(self, temp_db):
        store = StructuredObservationStore(db_path=temp_db)
        for t, title in [
            ("feature", "Test feature 1"),
            ("bugfix", "Test bugfix"),
            ("feature", "Test feature 2"),
        ]:
            obs = ParsedObservation(
                type=t,
                title=title,
                subtitle=None,
                facts=[],
                narrative=None,
                concepts=[],
                files_read=[],
                files_modified=[],
                source="heuristic",
            )
            store.add_structured(obs, session_id="sess_1", project="p", source="heuristic")

        stats = store.get_stats()
        assert stats["total"] == 3
        by_type = {r["type"]: r["count"] for r in stats["by_type"]}
        assert by_type.get("feature") == 2
        assert by_type.get("bugfix") == 1

    def test_dedup_v2_soft_links(self, temp_db):
        """Test that deduplicated observations create soft links (B.2)."""
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="bugfix",
            title="Fixed null pointer",
            subtitle=None,
            facts=["Added null check"],
            narrative=None,
            concepts=[],
            files_read=[],
            files_modified=["src/main.py"],
            source="heuristic",
        )
        # First insertion succeeds (no raw_observation_id FK constraint)
        id1 = store.add_structured(
            obs, session_id="sess_1", project="myapp", raw_observation_id=None, source="heuristic"
        )
        assert id1 > 0

        # Second insertion is deduplicated
        id2 = store.add_structured(
            obs, session_id="sess_1", project="myapp", raw_observation_id=None, source="heuristic"
        )
        assert id2 == 0  # deduplicated

        # But a soft link should exist (linked_raw_observation_id is nullable)
        links = store.get_dedup_links(id1)
        assert len(links) == 1
        assert links[0]["linked_raw_observation_id"] is None
        assert links[0]["link_type"] == "dedup"
        assert links[0]["content_hash"] is not None

    def test_linked_raw_observations(self, temp_db):
        """Test get_linked_raw_observations returns all linked raw IDs."""
        store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="feature",
            title="New feature",
            subtitle=None,
            facts=[],
            narrative=None,
            concepts=[],
            files_read=[],
            files_modified=[],
            source="heuristic",
        )
        id1 = store.add_structured(
            obs, session_id="sess_1", project="myapp", raw_observation_id=None, source="heuristic"
        )
        # Deduplicate 2 more times
        store.add_structured(
            obs, session_id="sess_1", project="myapp", raw_observation_id=None, source="heuristic"
        )
        store.add_structured(
            obs, session_id="sess_1", project="myapp", raw_observation_id=None, source="heuristic"
        )

        # get_linked_raw_observations returns primary + links (all None here)
        linked = store.get_linked_raw_observations(id1)
        # Primary is None, links are None — so result is empty list
        assert linked == []
