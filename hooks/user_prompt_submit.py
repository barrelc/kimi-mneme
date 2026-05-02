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

        extractor = Extractor()
        extractor.handle_user_prompt_submit(input_data)

        sys.exit(0)

    except Exception as e:
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
