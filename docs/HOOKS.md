# Hooks Reference

kimi-mneme uses Kimi CLI's [Hooks system](https://moonshotai.github.io/kimi-cli/en/customization/hooks.md) to capture session data automatically.

## Registered Hooks

Add these to `~/.kimi/config.toml`:

```toml
# Session lifecycle
[[hooks]]
event = "SessionStart"
command = "python3 /path/to/kimi-mneme/hooks/session_start.py"

[[hooks]]
event = "SessionEnd"
command = "python3 /path/to/kimi-mneme/hooks/session_end.py"

# Tool usage
[[hooks]]
event = "PostToolUse"
command = "python3 /path/to/kimi-mneme/hooks/post_tool_use.py"

[[hooks]]
event = "PostToolUseFailure"
command = "python3 /path/to/kimi-mneme/hooks/post_tool_use_failure.py"

# User interaction
[[hooks]]
event = "UserPromptSubmit"
command = "python3 /path/to/kimi-mneme/hooks/user_prompt_submit.py"
```

## Hook Details

### SessionStart

**Trigger**: When a new session is created or resumed.

**Input**:
```json
{
  "hook_event_name": "SessionStart",
  "session_id": "sess_abc123",
  "cwd": "/home/user/project",
  "source": "startup"
}
```

**Action**:
- Create session record in database
- Check for previous checkpoints (if session was resumed after compaction)
- Query cross-session patterns for current project
- Query relevant past context
- Inject context into session (via stdout)

**Output** (stdout):
```json
{
  "hookSpecificOutput": {
    "context": "## 📌 Session Resume Context\n**Checkpoint #2** (compaction)\n...\n\n## 🔁 Recurring Patterns\n❌ Recurring error in Shell (3×)\n...\n\n## Previous Context\n..."
  }
}
```

---

### SessionEnd

**Trigger**: When session is closed.

**Input**:
```json
{
  "hook_event_name": "SessionEnd",
  "session_id": "sess_abc123",
  "cwd": "/home/user/project",
  "reason": "user_exit"
}
```

**Action**:
- Mark session as complete
- Trigger compression of observations
- Generate session summary
- Detect and store cross-session patterns (errors, fixes)

---

### PostToolUse

**Trigger**: After successful tool execution.

**Input**:
```json
{
  "hook_event_name": "PostToolUse",
  "session_id": "sess_abc123",
  "cwd": "/home/user/project",
  "tool_name": "WriteFile",
  "tool_input": {
    "path": "/project/src/auth.ts",
    "content": "..."
  },
  "tool_output": "File written successfully",
  "tool_call_id": "call_123"
}
```

**Action**:
- Extract and sanitize observation
- Detect truncation (output > 100K chars)
- Store in database
- Record truncation metadata if applicable
- Update vector index (async)

---

### PostToolUseFailure

**Trigger**: After failed tool execution.

**Input**:
```json
{
  "hook_event_name": "PostToolUseFailure",
  "session_id": "sess_abc123",
  "cwd": "/home/user/project",
  "tool_name": "Shell",
  "tool_input": {
    "command": "npm test"
  },
  "error": "Error: 3 tests failed",
  "tool_call_id": "call_124"
}
```

**Action**:
- Store error observation (flagged as failure)
- These are weighted higher in search (learning from mistakes)
- Contributes to pattern detection (error patterns)

---

### UserPromptSubmit

**Trigger**: Before user input is processed.

**Input**:
```json
{
  "hook_event_name": "UserPromptSubmit",
  "session_id": "sess_abc123",
  "cwd": "/home/user/project",
  "prompt": "Fix the auth bug we had yesterday"
}
```

**Action**:
- Store user prompt
- Extract intent/keywords for better search
- Contributes to checkpoint open tasks detection

---

## Optional Hooks

These provide additional data but are not required:

```toml
# Subagent tracking
[[hooks]]
event = "SubagentStart"
command = "python3 /path/to/kimi-mneme/hooks/subagent_start.py"

[[hooks]]
event = "SubagentStop"
command = "python3 /path/to/kimi-mneme/hooks/subagent_stop.py"

# Compaction tracking (HIGHLY RECOMMENDED for context recovery)
[[hooks]]
event = "PreCompact"
command = "python3 /path/to/kimi-mneme/hooks/pre_compact.py"

[[hooks]]
event = "PostCompact"
command = "python3 /path/to/kimi-mneme/hooks/post_compact.py"

# Error tracking
[[hooks]]
event = "StopFailure"
command = "python3 /path/to/kimi-mneme/hooks/stop_failure.py"
```

### PostCompact (Context Compaction Recovery)

**Trigger**: After Kimi CLI compacts context mid-session.

**Input**:
```json
{
  "hook_event_name": "PostCompact",
  "session_id": "sess_abc123",
  "trigger": "token_threshold",
  "estimated_token_count": 2000,
  "previous_token_count": 5000
}
```

**Action**:
- Record compaction event (tokens_before, tokens_after)
- Extract key decisions from recent observations
- Extract open tasks from user prompts
- Create session checkpoint with summary
- **This enables session resume after compaction**

**Why this matters**: Without this hook, when Kimi CLI compacts context, your session loses all mid-session context. With mneme's PostCompact hook, a checkpoint is created that gets injected on the next SessionStart.

---

## Hook Implementation Pattern

Each hook follows this pattern:

```python
#!/usr/bin/env python3
"""Hook script template."""

import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.extractor import Extractor


def main():
    # Read input from stdin
    input_data = json.load(sys.stdin)
    
    extractor = Extractor()
    
    # Route to appropriate handler
    event = input_data.get("hook_event_name", "")
    
    if event == "SessionStart":
        result = extractor.handle_session_start(input_data)
        if result:
            print(result)
    elif event == "SessionEnd":
        extractor.handle_session_end(input_data)
    elif event == "PostToolUse":
        extractor.handle_post_tool_use(input_data)
    elif event == "PostToolUseFailure":
        extractor.handle_post_tool_use_failure(input_data)
    elif event == "UserPromptSubmit":
        extractor.handle_user_prompt_submit(input_data)
    elif event == "PostCompact":
        extractor.handle_compaction_event(input_data)
    
    # Exit 0 = allow (hooks are fire-and-forget)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

## Performance Notes

- All hooks run **fire-and-forget** (async, non-blocking)
- Database writes are batched where possible
- Vector indexing happens in background thread
- Pattern detection runs asynchronously on SessionEnd
- Hook timeout: 30 seconds (fail-open)
- Checkpoint creation: < 50ms
