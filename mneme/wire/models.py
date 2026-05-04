"""Wire event dataclasses for Kimi CLI session tracing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WireEvent:
    """Base class for all wire events."""

    session_id: str
    timestamp: float
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class TurnBeginEvent(WireEvent):
    """User input at the start of a turn."""

    user_input: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TurnEndEvent(WireEvent):
    """End of a turn."""

    pass


@dataclass
class StepBeginEvent(WireEvent):
    """Start of a step."""

    step_number: int = 0


@dataclass
class ToolCallEvent(WireEvent):
    """Tool invocation."""

    tool_call_id: str = ""
    tool_name: str = ""
    arguments: str = ""


@dataclass
class ToolResultEvent(WireEvent):
    """Tool execution result."""

    tool_call_id: str = ""
    is_error: bool = False
    output: str = ""


@dataclass
class ContentPartEvent(WireEvent):
    """Assistant content (text or thinking)."""

    content_type: str = ""  # "text" | "think" | ...
    text: str = ""
    think: str = ""
    encrypted: bool | None = None


@dataclass
class StatusUpdateEvent(WireEvent):
    """Token usage and context stats."""

    context_usage: float = 0.0
    context_tokens: int = 0
    max_context_tokens: int = 0
    input_cache_read: int = 0
    input_cache_creation: int = 0
    input_other: int = 0
    output_tokens: int = 0
    message_id: str = ""
    plan_mode: bool = False
    mcp_status: Any = None


@dataclass
class CompactionBeginEvent(WireEvent):
    """Context compaction started."""

    pass


@dataclass
class CompactionEndEvent(WireEvent):
    """Context compaction finished."""

    pass


@dataclass
class MCPLoadingBeginEvent(WireEvent):
    """MCP loading started."""

    pass


@dataclass
class MCPLoadingEndEvent(WireEvent):
    """MCP loading finished."""

    pass


@dataclass
class SessionState:
    """Parsed state.json for a session."""

    session_id: str
    custom_title: str = ""
    todos: list[dict[str, Any]] = field(default_factory=list)
    plan_mode: bool = False
    archived: bool = False
    approval_yolo: bool = False
    approval_afk: bool = False
    auto_approve_actions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
