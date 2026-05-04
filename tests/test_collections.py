"""Tests for Knowledge Collections."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mneme.core.prompts.json_parser import ParsedObservation
from mneme.db.collections_store import CollectionsStore
from mneme.db.schema import init_db
from mneme.db.structured_store import StructuredObservationStore


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    # Create a session
    from mneme.db.store import ObservationStore
    store = ObservationStore(db_path=db_path)
    store.add_session("sess_1", "/home/user/myproject")
    yield db_path
    try:
        Path(db_path).unlink(missing_ok=True)
    except PermissionError:
        pass


class TestCollectionsStore:
    def test_create_and_get(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_id = coll_store.create(
            name="api-architecture",
            description="API design decisions",
            project="myapp",
        )
        assert coll_id > 0

        coll = coll_store.get_by_name("api-architecture")
        assert coll is not None
        assert coll["name"] == "api-architecture"
        assert coll["description"] == "API design decisions"
        assert coll["project"] == "myapp"

    def test_list_collections(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="coll-1", project="p1")
        coll_store.create(name="coll-2", project="p1")
        coll_store.create(name="coll-3", project="p2")

        all_colls = coll_store.list_collections()
        assert len(all_colls) == 3

        p1_colls = coll_store.list_collections(project="p1")
        assert len(p1_colls) == 2

    def test_update(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="test-coll")
        coll_store.update(name="test-coll", description="Updated desc")

        coll = coll_store.get_by_name("test-coll")
        assert coll["description"] == "Updated desc"

    def test_delete(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="to-delete")
        assert coll_store.delete("to-delete") is True
        assert coll_store.get_by_name("to-delete") is None
        assert coll_store.delete("nonexistent") is False

    def test_add_remove_items(self, temp_db):
        # Create structured observation first
        struct_store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="decision",
            title="Use REST API",
            subtitle=None,
            facts=["Chose REST over GraphQL"],
            narrative="We decided to use REST for simplicity",
            concepts=["architecture"],
            files_read=[],
            files_modified=["docs/api.md"],
            source="ai",
        )
        obs_id = struct_store.add_structured(obs, session_id="sess_1", project="myapp", source="ai")
        assert obs_id > 0
        struct_store.close()

        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="my-collection")

        # Add item
        assert coll_store.add_item("my-collection", obs_id) is True
        coll = coll_store.get_by_name("my-collection")
        assert len(coll["items"]) == 1
        assert coll["items"][0]["title"] == "Use REST API"

        # Remove item
        assert coll_store.remove_item("my-collection", obs_id) is True
        coll = coll_store.get_by_name("my-collection")
        assert len(coll["items"]) == 0

    def test_export_markdown(self, temp_db):
        struct_store = StructuredObservationStore(db_path=temp_db)
        obs = ParsedObservation(
            type="feature",
            title="Added auth",
            subtitle=None,
            facts=["JWT tokens"],
            narrative=None,
            concepts=[],
            files_read=[],
            files_modified=["src/auth.py"],
            source="ai",
        )
        obs_id = struct_store.add_structured(obs, session_id="sess_1", project="myapp", source="ai")
        struct_store.close()

        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="auth-features")
        coll_store.add_item("auth-features", obs_id)

        md = coll_store.export_markdown("auth-features")
        assert "# auth-features" in md
        assert "Added auth" in md
        assert "JWT tokens" in md
        assert "src/auth.py" in md

    def test_export_json(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="empty-coll")
        data = coll_store.export_json("empty-coll")
        assert data["name"] == "empty-coll"
        assert data["item_count"] == 0

    def test_export_plain(self, temp_db):
        coll_store = CollectionsStore(db_path=temp_db)
        coll_store.create(name="plain-coll")
        text = coll_store.export_plain("plain-coll")
        assert "plain-coll" in text

    def test_auto_populate(self, temp_db):
        # Create observations
        struct_store = StructuredObservationStore(db_path=temp_db)
        for i in range(3):
            obs = ParsedObservation(
                type="decision",
                title=f"Decision {i}",
                subtitle=None,
                facts=[f"Fact {i}"],
                narrative=None,
                concepts=["architecture"],
                files_read=[],
                files_modified=[],
                source="ai",
            )
            struct_store.add_structured(obs, session_id="sess_1", project="myapp", source="ai")
        struct_store.close()

        coll_store = CollectionsStore(db_path=temp_db)
        coll_id = coll_store.create(
            name="auto-coll",
            query="Decision",
            types=["decision"],
        )
        assert coll_id > 0

        coll = coll_store.get_by_id(coll_id)
        assert len(coll["items"]) >= 1
