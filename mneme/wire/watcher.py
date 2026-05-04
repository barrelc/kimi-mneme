"""Filesystem watcher for Kimi CLI session directories."""

from __future__ import annotations

import threading
from pathlib import Path

from loguru import logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from mneme.wire.indexer import WireIndexer
from mneme.wire.reader import SessionReader


class _WireEventHandler(FileSystemEventHandler):
    """Handle filesystem events for wire.jsonl and state.json."""

    def __init__(self, watcher: SessionWatcher) -> None:
        self.watcher = watcher

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name == "wire.jsonl":
            self.watcher._on_wire_changed(path.parent)
        elif path.name == "state.json":
            self.watcher._on_state_changed(path.parent)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            # New session directory — scan it
            path = Path(event.src_path)
            if self.watcher._is_session_dir(path):
                self.watcher._register_session(path)
            return
        self.on_modified(event)


_global_watcher: SessionWatcher | None = None
_global_lock = threading.Lock()


def get_global_watcher(db_path: str | None = None) -> SessionWatcher:
    """Get or create the global singleton watcher."""
    global _global_watcher
    with _global_lock:
        if _global_watcher is None:
            _global_watcher = SessionWatcher(db_path)
        return _global_watcher


def stop_global_watcher() -> None:
    """Stop the global singleton watcher."""
    global _global_watcher
    with _global_lock:
        if _global_watcher is not None:
            _global_watcher.stop()
            _global_watcher = None


class SessionWatcher:
    """Watch ~/.kimi/sessions/ and index wire data in real time."""

    def __init__(self, db_path: str | None = None) -> None:
        self.sessions_dir = Path.home() / ".kimi" / "sessions"
        self.indexer = WireIndexer(db_path)
        self._readers: dict[str, SessionReader] = {}
        self._lock = threading.Lock()
        self._observer: Observer | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching."""
        if self._running:
            return
        self._running = True

        # Initial scan
        self._scan_all()

        # Start watchdog
        if self.sessions_dir.exists():
            handler = _WireEventHandler(self)
            self._observer = Observer()
            self._observer.schedule(handler, str(self.sessions_dir), recursive=True)
            self._observer.start()
            logger.info(f"SessionWatcher started on {self.sessions_dir}")

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("SessionWatcher stopped")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _scan_all(self) -> None:
        """Scan all existing sessions on startup."""
        if not self.sessions_dir.exists():
            return
        for hash_dir in self.sessions_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            for session_dir in hash_dir.iterdir():
                if session_dir.is_dir() and (session_dir / "wire.jsonl").exists():
                    self._register_session(session_dir)

    def _is_session_dir(self, path: Path) -> bool:
        """Check if path looks like a session directory."""
        return path.is_dir() and (path / "wire.jsonl").exists()

    def _register_session(self, session_dir: Path) -> None:
        """Register a session directory and do an initial read."""
        session_id = session_dir.name
        with self._lock:
            if session_id in self._readers:
                return
            reader = SessionReader(session_dir, session_id)
            self._readers[session_id] = reader

        # Initial ingestion
        self._ingest(reader)
        logger.debug(f"Registered session {session_id}")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _ingest(self, reader: SessionReader) -> None:
        """Read new wire events and state for a session."""
        try:
            events = reader.read_new_events()
            if events:
                counts = self.indexer.index_events(events)
                logger.debug(f"Indexed {len(events)} events for {reader.session_id}: {counts}")

            state = reader.read_state()
            if state:
                self.indexer.index_state(state)
        except Exception:
            logger.exception(f"Failed to ingest session {reader.session_id}")

    def _on_wire_changed(self, session_dir: Path) -> None:
        """Callback when wire.jsonl is modified."""
        session_id = session_dir.name
        with self._lock:
            reader = self._readers.get(session_id)
            if reader is None:
                reader = SessionReader(session_dir, session_id)
                self._readers[session_id] = reader
        self._ingest(reader)

    def _on_state_changed(self, session_dir: Path) -> None:
        """Callback when state.json is modified."""
        session_id = session_dir.name
        with self._lock:
            reader = self._readers.get(session_id)
            if reader is None:
                reader = SessionReader(session_dir, session_id)
                self._readers[session_id] = reader
        try:
            state = reader.read_state()
            if state:
                self.indexer.index_state(state)
        except Exception:
            logger.exception(f"Failed to index state for {session_id}")
