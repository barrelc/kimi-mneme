"""API routes for kimi-mneme web server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from mneme.db.store import ObservationStore
from mneme.db.vector import VectorStore

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
