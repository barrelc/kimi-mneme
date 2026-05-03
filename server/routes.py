"""API routes for kimi-mneme web server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from mneme.db.store import ObservationStore

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
) -> dict[str, Any]:
    """List sessions."""
    store = ObservationStore()
    sessions = store.get_sessions(limit=limit, offset=offset)
    return {
        "sessions": sessions,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Get database statistics."""
    store = ObservationStore()
    return store.get_stats()


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Get full session data with timeline, prompts, checkpoint, and pending work."""
    store = ObservationStore()

    # Get session info
    with store._get_conn() as conn:
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

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

    return {
        "session": session,
        "observations": observations,
        "user_prompts": user_prompts,
        "checkpoint": checkpoint,
        "pending_messages": pending_messages,
        "compactions": compactions,
    }
