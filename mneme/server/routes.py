"""API routes for kimi-mneme web server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from mneme.db.store import ObservationStore
from mneme.db.vector import VectorStore
from mneme.db.wire_store import WireStore

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


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

    # Add vector store stats
    vector_store = VectorStore()
    vector_stats = vector_store.get_stats()
    stats["vector_store"] = vector_stats

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
) -> dict[str, Any]:
    """Semantic vector search over observations."""
    vector_store = VectorStore()
    results = vector_store.search(query=q, limit=limit)
    return {
        "results": results,
        "total": len(results),
        "query": q,
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
