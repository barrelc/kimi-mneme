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
from mneme.db.structured_store import StructuredObservationStore
from mneme.db.vector import SQLiteVecStore
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
        structured_store = StructuredObservationStore()
        vec_store = SQLiteVecStore()

        all_results = []

        # 1. Search raw observations
        obs_results = store.search(
            query=query,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )
        for r in obs_results:
            snippet = r.get("snippet") or ""
            # If snippet is empty (FTS returned null), build a fallback from available fields
            if not snippet:
                snippet = (
                    " | ".join(
                        s
                        for s in [
                            r.get("prompt"),
                            r.get("tool_output"),
                            r.get("error"),
                            r.get("tool_input"),
                            r.get("tool_name"),
                            r.get("file_path"),
                        ]
                        if s
                    )
                    or "(no preview)"
                )
            all_results.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "timestamp": r.get("created_at"),
                    "type": r["event_type"],
                    "tool_name": r.get("tool_name"),
                    "file_path": r.get("file_path"),
                    "snippet": snippet[:200],
                    "source": "observation",
                }
            )

        # 2. Search structured observations (FTS)
        structured_results = structured_store.search_fts(query, limit=limit)
        for r in structured_results:
            all_results.append(
                {
                    "id": f"structured_{r['id']}",
                    "session_id": r["session_id"],
                    "timestamp": r.get("created_at"),
                    "type": r.get("type", "structured"),
                    "tool_name": None,
                    "file_path": None,
                    "snippet": f"{r.get('title', '')}: {r.get('narrative', '')}"[:200],
                    "source": "structured",
                }
            )

        # 3. Semantic search via sqlite-vec
        try:
            semantic_results = vec_store.search_with_content(
                query=query, project=project, limit=limit
            )
            for sr in semantic_results:
                obs = sr.get("observation", {})
                # Avoid duplicates
                existing_ids = {r["id"] for r in all_results}
                obs_id = obs.get("id")
                if obs_id and f"semantic_{obs_id}" not in existing_ids:
                    all_results.append(
                        {
                            "id": f"semantic_{obs_id}",
                            "session_id": obs.get("session_id", ""),
                            "timestamp": obs.get("created_at"),
                            "type": obs.get("type", "semantic"),
                            "tool_name": sr.get("matched_field", ""),
                            "file_path": None,
                            "snippet": obs.get("title", ""),
                            "source": "semantic",
                            "distance": sr.get("distance"),
                        }
                    )
        except Exception:
            pass  # Semantic search is best-effort

        # 4. Search wire events for richer context
        wire_results = wire_store.search_wire_events(query=query, limit=limit)
        for wr in wire_results:
            if not any(r.get("session_id") == wr["session_id"] for r in all_results):
                import json as json_mod

                try:
                    payload = json_mod.loads(wr.get("payload_json", "{}"))
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

                all_results.append(
                    {
                        "id": f"wire_{wr['id']}",
                        "session_id": wr["session_id"],
                        "created_at": wr.get("timestamp"),
                        "event_type": wr.get("event_type", "WireEvent"),
                        "tool_name": None,
                        "file_path": wr.get("session_cwd"),
                        "snippet": text,
                        "source": "wire",
                    }
                )

        # Filter by project if specified
        if project:
            all_results = [
                r
                for r in all_results
                if project.lower() in r.get("session_id", "").lower()
                or project.lower() in r.get("file_path", "").lower()
            ]

        # Deduplicate by snippet content
        seen_snippets = set()
        deduped = []
        for r in all_results:
            snippet = r.get("snippet", "")
            if snippet and snippet not in seen_snippets:
                seen_snippets.add(snippet)
                deduped.append(r)
            elif not snippet:
                deduped.append(r)

        output = {
            "results": deduped[:limit],
            "total": len(deduped[:limit]),
            "query": query,
            "sources": {
                "observations": sum(1 for r in deduped if r.get("source") == "observation"),
                "structured": sum(1 for r in deduped if r.get("source") == "structured"),
                "semantic": sum(1 for r in deduped if r.get("source") == "semantic"),
                "wire": sum(1 for r in deduped if r.get("source") == "wire"),
            },
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
