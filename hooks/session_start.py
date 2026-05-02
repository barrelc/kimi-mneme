#!/usr/bin/env python3
"""Hook: SessionStart — initialize session and inject context."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.extractor import Extractor


def main() -> None:
    """Handle SessionStart hook event."""
    try:
        input_data = json.load(sys.stdin)

        extractor = Extractor()
        result = extractor.handle_session_start(input_data)

        if result:
            print(result)

        sys.exit(0)

    except Exception as e:
        # Fail-open: log error but don't block session
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
