#!/usr/bin/env python3
"""Hook: UserPromptSubmit — log user prompts with wire.jsonl fallback."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.extractor import Extractor


def _extract_prompt_from_wire(session_id: str, cwd: str) -> str:
    """Extract latest user prompt from wire.jsonl when hook prompt is empty."""
    try:
        sessions_dir = Path.home() / ".kimi" / "sessions"
        if not sessions_dir.exists():
            return ""
        
        # Find the session directory
        for hash_dir in sessions_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            session_dir = hash_dir / session_id
            if session_dir.exists():
                wire_file = session_dir / "wire.jsonl"
                if wire_file.exists():
                    # Read last TurnBegin event
                    lines = wire_file.read_text(encoding="utf-8").strip().split("\n")
                    for line in reversed(lines):
                        try:
                            event = json.loads(line)
                            if event.get("message", {}).get("type") == "TurnBegin":
                                user_input = event["message"]["payload"]["user_input"]
                                if isinstance(user_input, list):
                                    texts = []
                                    for part in user_input:
                                        if part.get("type") == "text":
                                            texts.append(part.get("text", ""))
                                    return " ".join(texts)
                                elif isinstance(user_input, str):
                                    return user_input
                        except (json.JSONDecodeError, KeyError):
                            continue
        return ""
    except Exception:
        return ""


def main() -> None:
    """Handle UserPromptSubmit hook event."""
    try:
        input_data = json.load(sys.stdin)
        
        session_id = input_data.get("session_id", "")
        cwd = input_data.get("cwd", "")
        prompt = input_data.get("prompt", "")
        
        # If prompt is empty, try to extract from wire.jsonl
        if not prompt and session_id:
            prompt = _extract_prompt_from_wire(session_id, cwd)
            if prompt:
                input_data["prompt"] = prompt
        
        extractor = Extractor()
        extractor.handle_user_prompt_submit(input_data)

        sys.exit(0)

    except Exception as e:
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
