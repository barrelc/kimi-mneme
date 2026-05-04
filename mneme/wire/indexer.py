"""Index wire events into SQLite."""

from __future__ import annotations

import json
from typing import Any

from mneme.db.wire_store import WireStore
from mneme.wire.models import (
    ContentPartEvent,
    SessionState,
    StatusUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnBeginEvent,
    WireEvent,
)


class WireIndexer:
    """Consume wire events and persist them to the database."""

    def __init__(self, db_path: str | None = None) -> None:
        self.store = WireStore(db_path)
        # Runtime counters per session for turn/step tracking
        self._turns: dict[str, int] = {}
        self._steps: dict[str, int] = {}

    def index_events(self, events: list[WireEvent]) -> dict[str, int]:
        """Index a batch of events. Returns counts by type."""
        counts: dict[str, int] = {}
        for evt in events:
            counts[evt.event_type] = counts.get(evt.event_type, 0) + 1
            self._index_single(evt)
        return counts

    def _index_single(self, evt: WireEvent) -> None:
        sid = evt.session_id

        # Track turn / step numbers
        match evt:
            case TurnBeginEvent():
                self._turns[sid] = self._turns.get(sid, 0) + 1
                self._steps[sid] = 0  # reset steps on new turn
                self.store.ensure_session(sid)
                # Also store prompt as observation for backward compat
                prompt_text = _extract_prompt_text(evt)
                if prompt_text:
                    self.store.add_observation_from_wire(
                        session_id=sid,
                        event_type="UserPromptSubmit",
                        prompt=prompt_text,
                        turn_number=self._turns.get(sid),
                        step_number=0,
                    )
            case _ if hasattr(evt, "step_number") and evt.step_number:
                self._steps[sid] = max(self._steps.get(sid, 0), evt.step_number)
            case _ if evt.event_type == "StepBegin":
                # StepBegin doesn't have step_number attr in our model,
                # but payload has it.  Handle generically.
                step_n = evt.payload.get("n", 0)
                self._steps[sid] = max(self._steps.get(sid, 0), step_n)

        # Attach runtime counters to event for storage
        turn_n = self._turns.get(sid)
        step_n = self._steps.get(sid)
        if turn_n is not None:
            object.__setattr__(evt, "turn_number", turn_n)
        if step_n is not None:
            object.__setattr__(evt, "step_number", step_n)

        # Persist raw event
        self.store.add_wire_event(evt)

        # Typed storage
        match evt:
            case StatusUpdateEvent():
                self.store.add_session_stat(evt)
            case ContentPartEvent():
                if evt.think:
                    self.store.add_thinking(evt)
                if evt.text:
                    self.store.add_assistant_message(evt)
            case ToolCallEvent():
                pass  # raw event is enough; result comes in ToolResult
            case ToolResultEvent():
                self.store.ensure_session(sid)
                out = _normalize_output(evt.output)
                if evt.is_error:
                    self.store.add_observation_from_wire(
                        session_id=sid,
                        event_type="PostToolUseFailure",
                        tool_output=out,
                        turn_number=turn_n,
                        step_number=step_n,
                    )
                else:
                    self.store.add_observation_from_wire(
                        session_id=sid,
                        event_type="PostToolUse",
                        tool_output=out,
                        turn_number=turn_n,
                        step_number=step_n,
                    )

    def index_state(self, state: SessionState | None) -> None:
        """Update session metadata from state.json."""
        if state is None:
            return
        self.store.sync_todos(state)
        # Update session title if available
        if state.custom_title:
            with self.store._get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET summary = COALESCE(summary, ?) WHERE id = ?",
                    (state.custom_title, state.session_id),
                )


def _extract_prompt_text(evt: TurnBeginEvent) -> str:
    """Extract plain text from TurnBegin user_input."""
    parts: list[str] = []
    for item in evt.user_input:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, str):
            parts.append(item)
    return " ".join(parts).strip()


def _normalize_output(value: Any) -> str:
    """Convert tool output to string (handles text, list, dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                texts.append(item.get("text", json.dumps(item, ensure_ascii=False)))
            else:
                texts.append(str(item))
        return "\n".join(texts)
    if value is None:
        return ""
    return str(value)
