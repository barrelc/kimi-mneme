"""Read wire.jsonl, state.json and context.jsonl for a single session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mneme.wire.models import SessionState, WireEvent
from mneme.wire.parser import parse_state_json, parse_wire_line


class SessionReader:
    """Tail-follow reader for a single Kimi CLI session directory."""

    def __init__(self, session_dir: Path | str, session_id: str) -> None:
        self.session_dir = Path(session_dir)
        self.session_id = session_id
        self.wire_path = self.session_dir / "wire.jsonl"
        self.state_path = self.session_dir / "state.json"
        self.context_path = self.session_dir / "context.jsonl"
        self._wire_offset: int = 0
        self._state_mtime: float = 0.0

    # ------------------------------------------------------------------
    # Wire events
    # ------------------------------------------------------------------

    def read_new_events(self) -> list[WireEvent]:
        """Return all wire events written since last call."""
        if not self.wire_path.exists():
            return []

        events: list[WireEvent] = []
        with self.wire_path.open("r", encoding="utf-8") as fh:
            fh.seek(self._wire_offset)
            for line in fh:
                evt = parse_wire_line(self.session_id, line)
                if evt is not None:
                    events.append(evt)
            self._wire_offset = fh.tell()
        return events

    def reset(self) -> None:
        """Reset offset to re-read from the beginning."""
        self._wire_offset = 0

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def read_state(self) -> SessionState | None:
        """Read state.json if it has changed since last call."""
        if not self.state_path.exists():
            return None

        mtime = self.state_path.stat().st_mtime
        if mtime == self._state_mtime:
            return None

        try:
            raw: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        self._state_mtime = mtime
        return parse_state_json(self.session_id, raw)

    # ------------------------------------------------------------------
    # Context (optional — heavy, read on demand)
    # ------------------------------------------------------------------

    def read_context_messages(self) -> list[dict[str, Any]]:
        """Read all messages from context.jsonl and context_N.jsonl files."""
        messages: list[dict[str, Any]] = []
        for path in sorted(self.session_dir.glob("context*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                continue
        return messages
