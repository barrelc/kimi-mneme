#!/usr/bin/env python3
"""Plugin tool: mneme_get — fetch full observation details."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mneme.compat import fix_windows_encoding

fix_windows_encoding()

from mneme.db.store import ObservationStore


def main() -> None:
    """Handle mneme_get tool call."""
    try:
        params = json.load(sys.stdin)

        ids = params.get("ids", [])
        if not ids:
            print(json.dumps({"observations": []}, ensure_ascii=False))
            return

        store = ObservationStore()
        observations = store.get_observations(ids)

        # Format full output
        full_observations = []
        for obs in observations:
            full_obs = {
                "id": obs["id"],
                "session_id": obs["session_id"],
                "timestamp": obs["created_at"],
                "type": obs["event_type"],
                "tool_name": obs.get("tool_name"),
                "tool_input": obs.get("tool_input"),
                "tool_output": obs.get("tool_output"),
                "error": obs.get("error"),
                "file_path": obs.get("file_path"),
                "prompt": obs.get("prompt"),
                "agent_name": obs.get("agent_name"),
            }
            full_observations.append(full_obs)

        output = {
            "observations": full_observations,
            "count": len(full_observations),
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
