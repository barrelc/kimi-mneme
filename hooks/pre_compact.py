#!/usr/bin/env python3
"""Hook: PreCompact — record token count before context compaction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.extractor import Extractor


def main() -> None:
    """Handle PreCompact hook event."""
    try:
        input_data = json.load(sys.stdin)

        extractor = Extractor()
        extractor.handle_pre_compact(input_data)

        sys.exit(0)

    except Exception as e:
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
