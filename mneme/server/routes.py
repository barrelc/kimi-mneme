"""API routes for kimi-mneme web server."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mneme import __version__
from mneme.db.store import ObservationStore
from mneme.db.structured_store import StructuredObservationStore
from mneme.db.vector import SQLiteVecStore
from mneme.db.wire_store import WireStore

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "version": __version__}


@router.get("/search")
async def search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    date_from: str | None = Query(None, description="ISO date from"),
    date_to: str | None = Query(None, description="ISO date to"),
) -> dict[str, Any]:
    """Search observations."""
    store = ObservationStore()
    results = store.search(query=q, limit=limit, date_from=date_from, date_to=date_to)
    return {
        "results": results,
        "total": len(results),
        "query": q,
    }


@router.get("/observation/{observation_id}")
async def get_observation(observation_id: int) -> dict[str, Any]:
    """Get a single observation by ID."""
    store = ObservationStore()
    observations = store.get_observations([observation_id])

    if not observations:
        raise HTTPException(status_code=404, detail="Observation not found")

    return observations[0]


@router.get("/timeline/{observation_id}")
async def get_timeline(
    observation_id: int,
    radius: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Get timeline around an observation."""
    store = ObservationStore()
    timeline = store.get_timeline(observation_id, radius)
    return timeline


@router.get("/sessions")
async def get_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    project: str | None = Query(None, description="Filter by project name"),
) -> dict[str, Any]:
    """List sessions."""
    store = ObservationStore()
    if project:
        sessions = store.get_sessions_for_project(project, limit=limit)
    else:
        sessions = store.get_sessions(limit=limit, offset=offset)
    return {
        "sessions": sessions,
        "limit": limit,
        "offset": offset,
        "project": project,
    }


@router.get("/projects")
async def get_projects() -> dict[str, Any]:
    """Get list of unique projects from sessions."""
    store = ObservationStore()
    sessions = store.get_sessions(limit=1000)
    projects = {}
    for s in sessions:
        cwd = s.get("cwd", "")
        if cwd:
            # Extract project name from path
            name = cwd.replace("\\", "/").rstrip("/").split("/")[-1]
            if name:
                projects[name] = {
                    "name": name,
                    "path": cwd,
                    "sessions": projects.get(name, {}).get("sessions", 0) + 1,
                }
    return {"projects": list(projects.values())}


@router.get("/stats")
async def get_stats(
    project: str | None = Query(None, description="Filter by project name")
) -> dict[str, Any]:
    """Get database statistics."""
    store = ObservationStore()
    stats = store.get_stats()

    # Add vector store stats (sqlite-vec)
    vec_store = SQLiteVecStore()
    stats["vector_store"] = vec_store.get_stats()

    # Add real token economics (B.4)
    economics = store.get_token_economics()
    stats["token_economics"] = economics

    # Filter by project if specified
    if project:
        sessions = store.get_sessions(limit=1000)
        project_sessions = [s for s in sessions if project in s.get("cwd", "")]
        stats["total_sessions"] = len(project_sessions)
        # Recalculate observations count for project
        total_obs = 0
        for s in project_sessions:
            total_obs += s.get("observation_count", 0)
        stats["total_observations"] = total_obs
        stats["current_project"] = project

    return stats


@router.get("/vector_search")
async def vector_search(
    q: str = Query(..., description="Semantic search query"),
    limit: int = Query(10, ge=1, le=50),
    project: str | None = Query(None, description="Filter by project"),
    days: int | None = Query(None, description="Recency filter: last N days"),
) -> dict[str, Any]:
    """Semantic vector search over structured observations (sqlite-vec)."""
    vec_store = SQLiteVecStore()
    results = vec_store.search_with_content(query=q, project=project, limit=limit, days=days)
    return {
        "results": results,
        "total": len(results),
        "query": q,
        "project": project,
        "days": days,
        "backend": "sqlite-vec",
    }


@router.get("/semantic_search")
async def semantic_search(
    q: str = Query(..., description="Semantic search query"),
    project: str | None = Query(None, description="Filter by project"),
    fields: list[str] | None = Query(  # noqa: B008
        None, description="Fields to search: title, narrative, facts"
    ),
    limit: int = Query(10, ge=1, le=50),
    days: int | None = Query(None, description="Recency filter: last N days"),
) -> dict[str, Any]:
    """Semantic search with field-level control (sqlite-vec)."""
    vec_store = SQLiteVecStore()
    results = vec_store.search(query=q, project=project, limit=limit, fields=fields, days=days)
    return {
        "results": results,
        "total": len(results),
        "query": q,
        "project": project,
        "fields": fields,
        "days": days,
        "backend": "sqlite-vec",
    }


@router.get("/observations")
async def get_observations(
    event_type: str | None = Query(None, description="Filter by event type"),
    project: str | None = Query(None, description="Filter by project name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List observations with optional filtering."""
    store = ObservationStore()
    with store._get_conn() as conn:
        sql = """
            SELECT o.*, s.project, s.cwd as session_cwd
            FROM observations o
            JOIN sessions s ON o.session_id = s.id
            WHERE 1=1
        """
        params: list[Any] = []

        if event_type:
            sql += " AND o.event_type = ?"
            params.append(event_type)

        if project:
            sql += " AND (s.project = ? OR s.cwd LIKE ?)"
            params.extend([project, f"%{project}%"])

        sql += " ORDER BY o.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()

    return {
        "observations": [dict(row) for row in rows],
        "limit": limit,
        "offset": offset,
        "event_type": event_type,
        "project": project,
    }


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Get full session data with timeline, prompts, checkpoint, and pending work."""
    store = ObservationStore()

    # Get session info
    with store._get_conn() as conn:
        session_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()

    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dict(session_row)

    # Get all observations for this session (chronological)
    observations = store.get_observations_for_session(session_id, limit=None)

    # Get user prompts
    user_prompts = store.get_user_prompts(session_id, limit=100)

    # Get latest checkpoint
    checkpoint = store.get_latest_checkpoint(session_id)

    # Get pending messages for this session
    with store._get_conn() as conn:
        pending_rows = conn.execute(
            """
            SELECT * FROM pending_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            """,
            (session_id,),
        ).fetchall()
    pending_messages = [dict(row) for row in pending_rows]

    # Get compaction history
    compactions = store.get_compaction_history(session_id, limit=5)

    # Get AI-generated session summary
    ai_summary = store.get_session_summary(session_id)

    return {
        "session": session,
        "observations": observations,
        "user_prompts": user_prompts,
        "checkpoint": checkpoint,
        "pending_messages": pending_messages,
        "compactions": compactions,
        "ai_summary": ai_summary,
    }


@router.get("/wire_events")
async def get_wire_events(
    session_id: str = Query(..., description="Session ID"),
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Get wire events for a session."""
    store = WireStore()
    events = store.get_wire_events(session_id, event_type=event_type, limit=limit)
    return {"events": events, "session_id": session_id, "event_type": event_type}


@router.get("/session_stats")
async def get_session_stats(
    session_id: str = Query(..., description="Session ID"),
) -> dict[str, Any]:
    """Get token usage and context statistics for a session."""
    store = WireStore()
    stats = store.get_session_stats(session_id)
    latest = store.get_latest_session_stat(session_id)
    return {"stats": stats, "latest": latest, "session_id": session_id}


@router.get("/thinking")
async def get_thinking(
    session_id: str = Query(..., description="Session ID"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Get agent thinking blocks for a session."""
    store = WireStore()
    items = store.get_thinking(session_id, limit=limit)
    return {"thinking": items, "session_id": session_id}


@router.get("/assistant_messages")
async def get_assistant_messages(
    session_id: str = Query(..., description="Session ID"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Get assistant responses for a session."""
    store = WireStore()
    items = store.get_assistant_messages(session_id, limit=limit)
    return {"messages": items, "session_id": session_id}


@router.get("/todos")
async def get_todos(
    session_id: str = Query(..., description="Session ID"),
) -> dict[str, Any]:
    """Get session todos from state.json."""
    store = WireStore()
    items = store.get_todos(session_id)
    return {"todos": items, "session_id": session_id}


@router.get("/structured_observations")
async def get_structured_observations(
    project: str | None = Query(None, description="Filter by project name"),
    obs_type: str | None = Query(None, description="Filter by type (bugfix, feature, etc.)"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List structured observations with optional filtering."""
    store = StructuredObservationStore()

    if session_id:
        results = store.get_by_session(session_id, limit=limit)
    elif project:
        results = store.get_for_injection(project=project, limit=limit)
    else:
        # Get all recent
        with store._get_conn() as conn:
            sql = "SELECT * FROM structured_observations ORDER BY created_at DESC LIMIT ? OFFSET ?"
            rows = conn.execute(sql, (limit, offset)).fetchall()
            results = [store._deserialize(row) for row in rows]

    if obs_type:
        results = [r for r in results if r.get("type") == obs_type]

    return {
        "observations": results,
        "limit": limit,
        "offset": offset,
        "project": project,
        "type": obs_type,
    }


@router.get("/structured_search")
async def search_structured(
    q: str = Query(..., description="FTS search query"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Full-text search over structured observations."""
    store = StructuredObservationStore()
    results = store.search_fts(q, limit=limit)
    return {"results": results, "total": len(results), "query": q}


@router.get("/structured_stats")
async def get_structured_stats() -> dict[str, Any]:
    """Get statistics about structured observations."""
    store = StructuredObservationStore()
    return store.get_stats()


# ---------------------------------------------------------------------------
# SSE Stream
# ---------------------------------------------------------------------------

# Global event queue for SSE (max 100 events)
_sse_events: deque[dict[str, Any]] = deque(maxlen=100)
_sse_clients: set[asyncio.Queue] = set()


def broadcast_sse(event_type: str, data: dict[str, Any]) -> None:
    """Broadcast an event to all SSE clients."""
    event = {"type": event_type, "data": data, "timestamp": asyncio.get_event_loop().time()}
    _sse_events.append(event)
    for queue in list(_sse_clients):
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)


@router.get("/stream")
async def sse_stream() -> StreamingResponse:
    """Server-Sent Events endpoint for real-time updates."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    _sse_clients.add(queue)

    async def event_generator():
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'message': 'SSE connected'})}\n\n"

            while True:
                event = await queue.get()
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _sse_clients.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/queue_status")
async def get_queue_status() -> dict[str, Any]:
    """Get pending queue status for processing indicator."""
    store = ObservationStore()
    stats = store.get_queue_stats()
    return {
        "pending": stats.get("pending", 0),
        "processing": stats.get("processing", 0),
        "processed": stats.get("processed", 0),
        "failed": stats.get("failed", 0),
        "total": stats.get("total", 0),
    }


# ---------------------------------------------------------------------------
# Settings (B.3)
# ---------------------------------------------------------------------------


class SettingsPayload(BaseModel):
    structuring: bool = True
    injection: bool = True
    vector: bool = True
    projectmd: bool = True
    strip_system: bool = True
    redact_sensitive: bool = True
    compact_cards: bool = False


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get current settings (merged from config + UI overrides)."""
    from mneme.config import load_config

    config = load_config()
    return {
        "structuring": config.get("structuring", {}).get("enabled", True),
        "injection": config.get("injection", {}).get("enabled", True),
        "vector": config.get("vector", {}).get("enabled", True),
        "projectmd": config.get("project_md", {}).get("enabled", True),
        "strip_system": config.get("privacy", {}).get("strip_system", True),
        "redact_sensitive": config.get("privacy", {}).get("redact_sensitive", True),
        "compact_cards": False,
        "config_path": str(config.get("_config_path", "")),
    }


@router.post("/settings")
async def update_settings(payload: SettingsPayload) -> dict[str, Any]:
    """Update settings (UI overrides stored in config)."""
    from mneme.config import load_config, save_config

    config = load_config()

    # Update config sections
    if "structuring" not in config:
        config["structuring"] = {}
    config["structuring"]["enabled"] = payload.structuring

    if "injection" not in config:
        config["injection"] = {}
    config["injection"]["enabled"] = payload.injection

    if "vector" not in config:
        config["vector"] = {}
    config["vector"]["enabled"] = payload.vector

    if "project_md" not in config:
        config["project_md"] = {}
    config["project_md"]["enabled"] = payload.projectmd

    if "privacy" not in config:
        config["privacy"] = {}
    config["privacy"]["strip_system"] = payload.strip_system
    config["privacy"]["redact_sensitive"] = payload.redact_sensitive

    save_config(config)

    return {"status": "ok", "settings": payload.model_dump()}


# ---------------------------------------------------------------------------
# Codebase Analyzer (Tree-sitter)
# ---------------------------------------------------------------------------


@router.get("/codebase/search")
async def codebase_search(
    q: str = Query(..., description="Search query for symbol names"),
    path: str = Query(".", description="Project root or file path"),
    languages: str | None = Query(
        None, description="Comma-separated: python,javascript,typescript,rust,go"
    ),
    max_results: int = Query(20, ge=1, le=100),
    file_pattern: str | None = Query(None, description="Filter file paths containing substring"),
) -> dict[str, Any]:
    """AST-based symbol search across codebase."""
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    lang_list = languages.split(",") if languages else None

    symbols = analyzer.search_symbols(
        query=q,
        path=path,
        languages=lang_list,
        max_results=max_results,
        file_pattern=file_pattern,
    )

    return {
        "results": [
            {
                "name": s.name,
                "kind": s.kind,
                "signature": s.signature,
                "docstring": s.docstring,
                "file_path": s.file_path,
                "line_start": s.line_start,
                "line_end": s.line_end,
            }
            for s in symbols
        ],
        "total": len(symbols),
        "query": q,
        "path": path,
    }


@router.get("/codebase/outline")
async def codebase_outline(
    file_path: str = Query(..., description="Path to source file"),
) -> dict[str, Any]:
    """Get structural outline of a source file."""
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    outline = analyzer.get_outline(file_path)
    return outline


@router.get("/codebase/symbol")
async def codebase_symbol(
    file_path: str = Query(..., description="Path to source file"),
    symbol_name: str = Query(..., description="Name of symbol to unfold"),
) -> dict[str, Any]:
    """Get full body of a specific symbol."""
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    symbol = analyzer.get_symbol_body(file_path, symbol_name)

    if not symbol:
        raise HTTPException(status_code=404, detail="Symbol not found")

    return {
        "name": symbol.name,
        "kind": symbol.kind,
        "signature": symbol.signature,
        "docstring": symbol.docstring,
        "file_path": symbol.file_path,
        "line_start": symbol.line_start,
        "line_end": symbol.line_end,
        "body": symbol.body,
    }


# ---------------------------------------------------------------------------
# Knowledge Collections
# ---------------------------------------------------------------------------


@router.post("/collections")
async def create_collection(
    name: str,
    description: str | None = None,
    project: str | None = None,
    query: str | None = None,
    types: str | None = Query(None, description="Comma-separated observation types"),
    concepts: str | None = Query(None, description="Comma-separated concepts"),
    files: str | None = Query(None, description="Comma-separated file path filters"),
) -> dict[str, Any]:
    """Create a new knowledge collection."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    type_list = types.split(",") if types else None
    concept_list = concepts.split(",") if concepts else None
    file_list = files.split(",") if files else None

    coll_id = store.create(
        name=name,
        description=description,
        project=project,
        query=query,
        types=type_list,
        concepts=concept_list,
        files=file_list,
    )

    return {"id": coll_id, "name": name, "status": "created"}


@router.get("/collections")
async def list_collections(
    project: str | None = Query(None, description="Filter by project"),
) -> dict[str, Any]:
    """List all knowledge collections."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    collections = store.list_collections(project=project)
    return {"collections": collections, "total": len(collections)}


@router.get("/collections/{name}")
async def get_collection(name: str) -> dict[str, Any]:
    """Get collection details with items."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    coll = store.get_by_name(name)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    return coll


@router.delete("/collections/{name}")
async def delete_collection(name: str) -> dict[str, Any]:
    """Delete a collection."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    if not store.delete(name):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "deleted", "name": name}


@router.post("/collections/{name}/items")
async def add_collection_item(
    name: str,
    structured_id: int,
) -> dict[str, Any]:
    """Add a structured observation to a collection."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    if not store.add_item(name, structured_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "added", "collection": name, "structured_id": structured_id}


@router.delete("/collections/{name}/items/{structured_id}")
async def remove_collection_item(
    name: str,
    structured_id: int,
) -> dict[str, Any]:
    """Remove a structured observation from a collection."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    if not store.remove_item(name, structured_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "removed", "collection": name, "structured_id": structured_id}


@router.get("/collections/{name}/export")
async def export_collection(
    name: str,
    format: str = Query("md", description="Export format: md, json, plain"),
) -> dict[str, Any]:
    """Export collection in various formats."""
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()

    if format == "md":
        content = store.export_markdown(name)
        return {"format": "markdown", "content": content}
    elif format == "json":
        data = store.export_json(name)
        return {"format": "json", "data": data}
    elif format == "plain":
        content = store.export_plain(name)
        return {"format": "plain", "content": content}
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use: md, json, plain")


@router.get("/collections/{name}/query")
async def query_collection(
    name: str,
    q: str = Query(..., description="Question to ask about the collection"),
    limit: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Query a knowledge collection with a natural language question.

    Returns the most relevant observations from the collection
    ranked by semantic similarity to the question.
    """
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    result = store.query_collection(name, question=q, limit=limit)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
