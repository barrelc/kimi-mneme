"""Tests for StructuringWorker."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path

import pytest

from mneme.core.worker import StructuringWorker
from mneme.db.schema import init_db
from mneme.db.store import ObservationStore, PendingMessage


@pytest.fixture
def temp_db():
    """Create a temporary database with a session."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    from mneme.db.store import ObservationStore

    store = ObservationStore(db_path=db_path)
    store.add_session("sess_1", "/home/user/myproject")
    yield db_path
    with contextlib.suppress(PermissionError):
        Path(db_path).unlink(missing_ok=True)


class TestStructuringWorker:
    def test_worker_initialization(self, temp_db):
        worker = StructuringWorker(interval=1)
        assert worker.running is False
        assert worker.interval == 1

    def test_process_empty_queue(self, temp_db):
        worker = StructuringWorker(interval=1)
        # Override db path
        worker.store = ObservationStore(db_path=temp_db)
        worker.structured_store.db_path = temp_db

        async def run():
            await worker._process_batch(limit=5)

        asyncio.get_event_loop().run_until_complete(run())
        # Should not crash with empty queue

    def test_process_batch_with_message(self, temp_db):
        store = ObservationStore(db_path=temp_db)
        # Add a pending message
        msg = PendingMessage(
            session_id="sess_1",
            message_type="observation",
            tool_name="WriteFile",
            tool_input='{"path": "test.py"}',
            tool_response="File written",
            status="pending",
        )
        store.add_pending_message(msg)

        worker = StructuringWorker(interval=1)
        worker.store = store
        worker.structured_store.db_path = temp_db

        async def run():
            await worker._process_batch(limit=5)

        asyncio.get_event_loop().run_until_complete(run())

        # Message should be marked as processed or failed
        # (heuristic should process it since no AI token)
        stats = store.get_queue_stats()
        assert stats["pending"] == 0

    def test_extract_project(self):
        assert StructuringWorker._extract_project("/home/user/myproject") == "myproject"
        assert StructuringWorker._extract_project("/home/user/myproject/") == "myproject"
        assert StructuringWorker._extract_project("C:\\Users\\barre\\project") == "project"
