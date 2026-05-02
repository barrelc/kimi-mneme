#!/usr/bin/env python3
"""Hook: UserPromptSubmit — log user prompts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.extractor import Extractor


def main() -> None:
    """Handle UserPromptSubmit hook event."""
    try:
        input_data = json.load(sys.stdin)
        
        # DEBUG: log what we received
        debug_path = Path.home() / ".kimi" / "mneme" / "hook_debug.log"
        with open(debug_path, "a", encoding="utf-8") as f:
            f.write("=== UserPromptSubmit ===\n")
            f.write(json.dumps(input_data, ensure_ascii=False, indent=2))
            f.write("\n\n")
        
        # Try to extract prompt from various fields
        prompt = input_data.get("prompt", "")
        
        # If prompt is empty, try user_input or content parts
        if not prompt:
            user_input = input_data.get("user_input", [])
            if isinstance(user_input, list):
                # Extract text from ContentPart list
                texts = []
                for part in user_input:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            texts.append(part.get("text", ""))
                        elif "text" in part:
                            texts.append(part["text"])
                prompt = " ".join(texts)
            elif isinstance(user_input, str):
                prompt = user_input
        
        # Update input_data with extracted prompt
        if prompt:
            input_data["prompt"] = prompt
            
            # Log that we extracted it
            with open(debug_path, "a", encoding="utf-8") as f:
                f.write(f"EXTRACTED PROMPT: {prompt[:100]}...\n\n")
        else:
            with open(debug_path, "a", encoding="utf-8") as f:
                f.write("WARNING: Could not extract prompt\n\n")

        extractor = Extractor()
        extractor.handle_user_prompt_submit(input_data)

        sys.exit(0)

    except Exception as e:
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
