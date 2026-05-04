#!/usr/bin/env python3
"""Plugin tool: mneme_timeline — get chronological context."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mneme.db.store import ObservationStore


def main() -> None:
    """Handle mneme_timeline tool call."""
    try:
        params = json.load(sys.stdin)

        observation_id = params.get("observation_id", 0)
        radius = min(params.get("radius", 5), 20)

        store = ObservationStore()
        timeline = store.get_timeline(observation_id, radius)

        # Format compact output
        def format_obs(obs: dict) -> dict:
            return {
                "id": obs["id"],
                "timestamp": obs["created_at"],
                "type": obs["event_type"],
                "tool_name": obs.get("tool_name"),
                "file_path": obs.get("file_path"),
                "snippet": (obs.get("tool_output") or obs.get("error") or obs.get("prompt") or "")[
                    :200
                ],
            }

        output = {
            "center": format_obs(timeline["center"]) if timeline["center"] else None,
            "before": [format_obs(o) for o in timeline["before"]],
            "after": [format_obs(o) for o in timeline["after"]],
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
