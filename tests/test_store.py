"""Tests for ObservationStore."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mneme.db.schema import init_db
from mneme.db.store import Observation, ObservationStore


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    yield db_path

    # On Windows, SQLite connections may keep the file locked.
    # Force close all connections and retry deletion with backoff.
    import gc
    import sqlite3
    import time

    gc.collect()

    # Close any lingering sqlite connections by checking gc objects
    # Use type() check to avoid triggering __class__ on torch objects (FutureWarning)
    for obj in gc.get_objects():
        try:
            if type(obj) is sqlite3.Connection:
                obj.close()
        except Exception:
            pass

    # Retry deletion with backoff (WAL files may need time to clean up)
    for _ in range(10):
        try:
            Path(db_path).unlink(missing_ok=True)
            break
        except PermissionError:
            time.sleep(0.1)


@pytest.fixture
def store(temp_db):
    """Create an ObservationStore with temp DB."""
    return ObservationStore(db_path=temp_db)


class TestObservationStore:
    def test_add_session(self, store):
        store.add_session("sess_123", "/project")

        sessions = store.get_sessions(limit=10)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess_123"
        assert sessions[0]["cwd"] == "/project"

    def test_add_observation(self, store):
        store.add_session("sess_123", "/project")

        obs = Observation(
            session_id="sess_123",
            event_type="PostToolUse",
            tool_name="WriteFile",
            file_path="src/main.py",
            tool_output="File written",
        )

        obs_id = store.add_observation(obs)
        assert obs_id > 0

    def test_search(self, store):
        store.add_session("sess_123", "/project")

        obs = Observation(
            session_id="sess_123",
            event_type="PostToolUse",
            tool_name="WriteFile",
            file_path="src/auth.py",
            tool_output="Fixed authentication bug",
        )
        store.add_observation(obs)

        results = store.search("authentication")
        assert len(results) >= 1

    def test_get_timeline(self, store):
        store.add_session("sess_123", "/project")

        for i in range(5):
            obs = Observation(
                session_id="sess_123",
                event_type="PostToolUse",
                tool_name="Shell",
                tool_output=f"Command {i}",
            )
            store.add_observation(obs)

        timeline = store.get_timeline(3, radius=2)
        assert timeline["center"] is not None
        assert len(timeline["before"]) >= 0
        assert len(timeline["after"]) >= 0

    def test_get_observations(self, store):
        store.add_session("sess_123", "/project")

        obs = Observation(
            session_id="sess_123",
            event_type="UserPromptSubmit",
            prompt="Hello world",
        )
        obs_id = store.add_observation(obs)

        results = store.get_observations([obs_id])
        assert len(results) == 1
        assert results[0]["prompt"] == "Hello world"

    def test_get_stats(self, store):
        store.add_session("sess_123", "/project")

        stats = store.get_stats()
        assert stats["total_sessions"] == 1
        assert stats["total_observations"] == 0
