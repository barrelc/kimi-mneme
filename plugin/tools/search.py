#!/usr/bin/env python3
"""Plugin tool: mneme_search — search memory index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mneme.db.store import ObservationStore


def main() -> None:
    """Handle mneme_search tool call."""
    try:
        params = json.load(sys.stdin)

        query = params.get("query", "")
        limit = min(params.get("limit", 10), 50)
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        project = params.get("project")

        store = ObservationStore()
        results = store.search(
            query=query,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

        # Filter by project if specified
        if project:
            results = [
                r for r in results
                if project.lower() in r.get("session_id", "").lower()
                or project.lower() in r.get("file_path", "").lower()
            ]

        # Format compact output
        compact_results = []
        for r in results:
            compact_results.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "timestamp": r["created_at"],
                "type": r["event_type"],
                "tool_name": r.get("tool_name"),
                "file_path": r.get("file_path"),
                "snippet": r.get("snippet", ""),
            })

        output = {
            "results": compact_results,
            "total": len(compact_results),
            "query": query,
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
