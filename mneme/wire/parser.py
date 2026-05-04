"""Parse wire.jsonl lines into typed event objects."""

from __future__ import annotations

import json
from typing import Any

from mneme.wire.models import (
    CompactionBeginEvent,
    CompactionEndEvent,
    ContentPartEvent,
    MCPLoadingBeginEvent,
    MCPLoadingEndEvent,
    SessionState,
    StatusUpdateEvent,
    StepBeginEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnBeginEvent,
    TurnEndEvent,
    WireEvent,
)


def parse_wire_line(session_id: str, line: str) -> WireEvent | None:
    """Parse a single wire.jsonl line into a typed event."""
    line = line.strip()
    if not line:
        return None

    try:
        raw: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Metadata header
    if raw.get("type") == "metadata":
        return None

    msg = raw.get("message", {})
    event_type = msg.get("type", "")
    payload = msg.get("payload", {})
    timestamp = raw.get("timestamp", 0.0)

    base = {
        "session_id": session_id,
        "timestamp": timestamp,
        "event_type": event_type,
        "payload": payload,
        "raw": raw,
    }

    match event_type:
        case "TurnBegin":
            return TurnBeginEvent(
                **base,
                user_input=payload.get("user_input", []),
            )
        case "TurnEnd":
            return TurnEndEvent(**base)
        case "StepBegin":
            return StepBeginEvent(
                **base,
                step_number=payload.get("n", 0),
            )
        case "ToolCall":
            func = payload.get("function", {})
            return ToolCallEvent(
                **base,
                tool_call_id=payload.get("id", ""),
                tool_name=func.get("name", ""),
                arguments=func.get("arguments", ""),
            )
        case "ToolResult":
            rv = payload.get("return_value", {})
            return ToolResultEvent(
                **base,
                tool_call_id=payload.get("tool_call_id", ""),
                is_error=rv.get("is_error", False),
                output=rv.get("output", ""),
            )
        case "ToolCallPart":
            # Partial tool call — treat similarly to ToolCall
            func = payload.get("function", {})
            return ToolCallEvent(
                **base,
                tool_call_id=payload.get("id", ""),
                tool_name=func.get("name", ""),
                arguments=func.get("arguments", ""),
            )
        case "ContentPart":
            return ContentPartEvent(
                **base,
                content_type=payload.get("type", ""),
                text=payload.get("text", ""),
                think=payload.get("think", ""),
                encrypted=payload.get("encrypted"),
            )
        case "StatusUpdate":
            tu = payload.get("token_usage") or {}
            return StatusUpdateEvent(
                **base,
                context_usage=payload.get("context_usage", 0.0),
                context_tokens=payload.get("context_tokens", 0),
                max_context_tokens=payload.get("max_context_tokens", 0),
                input_cache_read=tu.get("input_cache_read", 0),
                input_cache_creation=tu.get("input_cache_creation", 0),
                input_other=tu.get("input_other", 0),
                output_tokens=tu.get("output", 0),
                message_id=payload.get("message_id", ""),
                plan_mode=payload.get("plan_mode", False),
                mcp_status=payload.get("mcp_status"),
            )
        case "CompactionBegin":
            return CompactionBeginEvent(**base)
        case "CompactionEnd":
            return CompactionEndEvent(**base)
        case "MCPLoadingBegin":
            return MCPLoadingBeginEvent(**base)
        case "MCPLoadingEnd":
            return MCPLoadingEndEvent(**base)
        case _:
            # Unknown event — keep as generic WireEvent
            return WireEvent(**base)


def parse_state_json(session_id: str, raw: dict[str, Any]) -> SessionState:
    """Parse state.json dict into SessionState."""
    approval = raw.get("approval", {})
    return SessionState(
        session_id=session_id,
        custom_title=raw.get("custom_title", ""),
        todos=raw.get("todos", []),
        plan_mode=raw.get("plan_mode", False),
        archived=raw.get("archived", False),
        approval_yolo=approval.get("yolo", False),
        approval_afk=approval.get("afk", False),
        auto_approve_actions=approval.get("auto_approve_actions", []),
        raw=raw,
    )
