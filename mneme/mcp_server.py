"""MCP server for kimi-mneme memory access (FastMCP 3.2)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from mneme.compat import fix_windows_encoding

fix_windows_encoding()

from mneme.db.structured_store import StructuredObservationStore  # noqa: E402
from mneme.db.vector import SQLiteVecStore  # noqa: E402

mcp = FastMCP(
    "kimi-mneme",
    instructions="Persistent memory for Kimi Code CLI. Search past observations, recall details, and get project context via semantic or full-text search.",
)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def memory_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Search memory index with full-text queries.

    Args:
        query: Search query (supports FTS5 syntax).
        limit: Maximum results to return.

    Returns:
        Dict with 'results' list and 'total' count.
    """
    store = StructuredObservationStore()
    results = store.search_fts(query, limit=limit)
    return {"results": results, "total": len(results), "query": query}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def memory_semantic_search(
    query: str,
    project: str | None = None,
    limit: int = 10,
    days: int | None = None,
) -> dict[str, Any]:
    """Semantic search over memory using embeddings (sqlite-vec).

    Finds observations by meaning, not just keyword matching.
    Great for: "find similar code patterns", "what did I do about auth?",
    "show me discoveries about performance".

    Args:
        query: Natural language query.
        project: Optional project filter.
        limit: Maximum results.
        days: Optional recency filter — only observations from last N days.

    Returns:
        Dict with 'results' (full observations + distance + matched_field).
    """
    vec_store = SQLiteVecStore()
    results = vec_store.search_with_content(query=query, project=project, limit=limit, days=days)
    return {
        "results": results,
        "total": len(results),
        "query": query,
        "project": project,
        "days": days,
        "backend": "sqlite-vec",
    }


@mcp.tool(annotations={"readOnlyHint": True})
def memory_recall(observation_id: int) -> dict[str, Any]:
    """Get full details for a specific structured observation.

    Args:
        observation_id: The ID of the observation.

    Returns:
        Full observation data or error message.
    """
    store = StructuredObservationStore()
    obs = store.get_by_id(observation_id)
    if obs:
        return {"observation": obs, "found": True}
    return {"error": f"Observation {observation_id} not found", "found": False}


@mcp.tool(annotations={"readOnlyHint": True})
def memory_timeline(session_id: str, limit: int = 20) -> dict[str, Any]:
    """Get chronological structured observations for a session.

    Args:
        session_id: The session ID.
        limit: Maximum observations to return.

    Returns:
        Dict with 'observations' list.
    """
    store = StructuredObservationStore()
    results = store.get_by_session(session_id, limit=limit)
    return {"observations": results, "session_id": session_id, "total": len(results)}


@mcp.tool(annotations={"readOnlyHint": True})
def memory_stats() -> dict[str, Any]:
    """Get memory statistics.

    Returns:
        Stats about structured observations (total, by_type, by_source, by_project).
    """
    store = StructuredObservationStore()
    return store.get_stats()


@mcp.tool(annotations={"readOnlyHint": True})
def memory_by_concept(concept: str, limit: int = 10) -> dict[str, Any]:
    """Search observations by concept tag.

    Args:
        concept: Concept name (e.g., 'how-it-works', 'pattern', 'trade-off').
        limit: Maximum results.

    Returns:
        Matching observations.
    """
    store = StructuredObservationStore()
    results = store.search_by_concept(concept, limit=limit)
    return {"results": results, "concept": concept, "total": len(results)}


@mcp.tool(annotations={"readOnlyHint": True})
def memory_by_file(file_path: str, limit: int = 10) -> dict[str, Any]:
    """Find observations related to a specific file.

    Args:
        file_path: File path to search for.
        limit: Maximum results.

    Returns:
        Observations that read or modified the file.
    """
    store = StructuredObservationStore()
    results = store.search_by_file(file_path, limit=limit)
    return {"results": results, "file": file_path, "total": len(results)}


@mcp.resource("memory://stats")
def get_memory_stats() -> dict[str, Any]:
    """Get memory statistics as a resource."""
    store = StructuredObservationStore()
    return store.get_stats()


# ---------------------------------------------------------------------------
# Tree-sitter Codebase Tools
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
def smart_search(
    query: str,
    path: str = ".",
    max_results: int = 20,
    file_pattern: str | None = None,
) -> dict[str, Any]:
    """Search codebase for symbols (functions, classes, methods) using AST parsing.

    Much more precise than text search — finds actual definitions, not mentions
    in comments or strings.

    Args:
        query: Symbol name to search for (partial match supported).
        path: Root directory to search (default: current working directory).
        max_results: Maximum symbols to return.
        file_pattern: Filter file paths containing this substring (e.g., ".py", "src/api").

    Returns:
        List of symbols with name, kind, signature, file path, and line number.
    """
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    symbols = analyzer.search_symbols(
        query=query,
        path=path,
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
                "line": s.line_start,
            }
            for s in symbols
        ],
        "total": len(symbols),
        "query": query,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def smart_outline(file_path: str) -> dict[str, Any]:
    """Get structural outline of a source file.

    Shows all functions, classes, and methods with signatures but without bodies.
    Much cheaper than reading the full file.

    Args:
        file_path: Path to the source file.

    Returns:
        File outline with symbol list.
    """
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    outline = analyzer.get_outline(file_path)
    return outline


@mcp.tool(annotations={"readOnlyHint": True})
def smart_unfold(file_path: str, symbol_name: str) -> dict[str, Any]:
    """Expand a specific symbol (function, class, method) from a file.

    Returns the full source code of just that symbol.
    Use after smart_search or smart_outline to read specific code.

    Args:
        file_path: Path to the source file.
        symbol_name: Name of the symbol to unfold.

    Returns:
        Symbol details with full body, or error if not found.
    """
    from mneme.core.codebase_analyzer import get_analyzer

    analyzer = get_analyzer()
    symbol = analyzer.get_symbol_body(file_path, symbol_name)

    if not symbol:
        return {
            "error": f'Symbol "{symbol_name}" not found in {file_path}',
            "found": False,
        }

    return {
        "name": symbol.name,
        "kind": symbol.kind,
        "signature": symbol.signature,
        "docstring": symbol.docstring,
        "file_path": symbol.file_path,
        "line_start": symbol.line_start,
        "line_end": symbol.line_end,
        "body": symbol.body,
        "found": True,
    }


# ---------------------------------------------------------------------------
# Knowledge Collections Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def memory_build_collection(
    name: str,
    description: str | None = None,
    project: str | None = None,
    query: str | None = None,
    types: str | None = None,
    concepts: str | None = None,
    files: str | None = None,
) -> dict[str, Any]:
    """Build a knowledge collection from filtered observations.

    Creates a curated subset of memory that can be exported or queried later.
    Useful for: onboarding docs, architecture decisions, bug patterns.

    Args:
        name: Collection name (unique, used as identifier).
        description: What this collection is about.
        project: Filter by project name.
        query: FTS search query to auto-populate.
        types: Comma-separated observation types (decision,bugfix,feature,refactor,discovery,change).
        concepts: Comma-separated concepts to filter by.
        files: Comma-separated file path filters.

    Returns:
        Collection ID and item count.
    """
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

    coll = store.get_by_id(coll_id) if coll_id else None
    return {
        "id": coll_id,
        "name": name,
        "item_count": len(coll["items"]) if coll else 0,
        "status": "created",
    }


@mcp.tool(annotations={"readOnlyHint": True})
def memory_list_collections(project: str | None = None) -> dict[str, Any]:
    """List all knowledge collections with their stats.

    Args:
        project: Optional project filter.

    Returns:
        List of collections with item counts.
    """
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    collections = store.list_collections(project=project)
    return {"collections": collections, "total": len(collections)}


@mcp.tool(annotations={"readOnlyHint": True})
def memory_export_collection(name: str, format: str = "md") -> dict[str, Any]:
    """Export a knowledge collection in various formats.

    Args:
        name: Collection name.
        format: Export format — "md" (markdown), "json", or "plain".

    Returns:
        Exported content in requested format.
    """
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
        return {"error": "Unsupported format. Use: md, json, plain"}


@mcp.tool(annotations={"readOnlyHint": True})
def memory_workflow() -> dict[str, Any]:
    """How to use kimi-mneme memory effectively.

    Follow this 3-step workflow for best results:

    1. SEARCH — Find relevant observations:
       • memory_search(query) — full-text search (fast, keyword-based)
       • memory_semantic_search(query) — meaning-based search (finds related concepts)
       • memory_by_concept(concept) — filter by concept tags
       • memory_by_file(file_path) — find observations about a file

    2. CONTEXT — Get chronological context:
       • memory_timeline(session_id) — see what happened before/after
       • memory_stats() — overview of what's in memory

    3. DETAIL — Fetch full content:
       • memory_recall(observation_id) — get complete observation with all facts

    For codebase exploration:
       • smart_search(query) — find symbols (functions, classes)
       • smart_outline(file_path) — see file structure
       • smart_unfold(file_path, symbol_name) — read specific symbol body

    For knowledge collections:
       • memory_list_collections() — see available collections
       • memory_export_collection(name) — export as markdown
    """
    return {
        "workflow": "search → context → detail",
        "tools": {
            "search": [
                "memory_search",
                "memory_semantic_search",
                "memory_by_concept",
                "memory_by_file",
            ],
            "context": ["memory_timeline", "memory_stats"],
            "detail": ["memory_recall"],
            "codebase": ["smart_search", "smart_outline", "smart_unfold"],
            "collections": ["memory_list_collections", "memory_export_collection"],
        },
    }


@mcp.tool(annotations={"readOnlyHint": True})
def memory_query_collection(
    name: str,
    question: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Ask a question about a knowledge collection.

    Uses semantic similarity to find the most relevant observations
    in the collection that answer your question.

    Args:
        name: Collection name.
        question: Natural language question.
        limit: Maximum number of relevant observations to return.

    Returns:
        Ranked list of relevant observations with relevance scores.
    """
    from mneme.db.collections_store import CollectionsStore

    store = CollectionsStore()
    return store.query_collection(name, question=question, limit=limit)


def main() -> None:
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
