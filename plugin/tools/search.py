#!/usr/bin/env python3
"""Plugin tool: mneme_search — search memory index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mneme.compat import fix_windows_encoding

fix_windows_encoding()

from mneme.db.store import ObservationStore
from mneme.db.wire_store import WireStore


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
        wire_store = WireStore()
        
        # Search observations
        obs_results = store.search(
            query=query,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

        # Also search wire events for richer context
        wire_results = wire_store.search_wire_events(query=query, limit=limit)
        
        # Convert wire events to same format
        for wr in wire_results:
            # Skip if we already have this session in obs_results
            if not any(r.get("session_id") == wr["session_id"] for r in obs_results):
                import json as json_mod
                try:
                    payload = json_mod.loads(wr.get("payload_json", "{}"))
                    # Extract meaningful text from payload
                    text = ""
                    if isinstance(payload, dict):
                        if "content" in payload:
                            text = str(payload["content"])[:200]
                        elif "message" in payload:
                            text = str(payload["message"])[:200]
                        elif "tool_name" in payload:
                            text = f"{payload['tool_name']}: {str(payload.get('tool_input', ''))[:100]}"
                        else:
                            text = str(payload)[:200]
                    else:
                        text = str(payload)[:200]
                except Exception:
                    text = wr.get("payload_json", "")[:200]
                
                obs_results.append({
                    "id": f"wire_{wr['id']}",
                    "session_id": wr["session_id"],
                    "created_at": wr.get("timestamp"),
                    "event_type": wr.get("event_type", "WireEvent"),
                    "tool_name": None,
                    "file_path": wr.get("session_cwd"),
                    "snippet": text,
                })

        # Filter by project if specified
        if project:
            obs_results = [
                r
                for r in obs_results
                if project.lower() in r.get("session_id", "").lower()
                or project.lower() in r.get("file_path", "").lower()
            ]

        # Format compact output
        compact_results = []
        for r in obs_results[:limit]:
            compact_results.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "timestamp": r.get("created_at"),
                    "type": r["event_type"],
                    "tool_name": r.get("tool_name"),
                    "file_path": r.get("file_path"),
                    "snippet": r.get("snippet", ""),
                }
            )

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
