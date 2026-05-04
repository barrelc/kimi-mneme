# Tools Reference

kimi-mneme provides tools through three interfaces:

1. **Kimi CLI Plugin** (3 tools) — `mneme_search`, `mneme_timeline`, `mneme_get`
2. **MCP Server** (15 tools) — For Claude Desktop, Cursor, Goose, etc.
3. **Web UI** — Interactive viewer at `http://localhost:37777`

## MCP Tools Overview

| Tool | Category | Purpose |
|------|----------|---------|
| `memory_search` | Search | FTS5 full-text search |
| `memory_semantic_search` | Search | sqlite-vec semantic search (with optional `days` recency filter) |
| `memory_recall` | Detail | Get full observation by ID |
| `memory_timeline` | Context | Chronological observations for a session |
| `memory_stats` | Context | Memory statistics |
| `memory_by_concept` | Search | Filter by concept tag |
| `memory_by_file` | Search | Find observations related to a file |
| `memory_workflow` | Guide | **How to use memory effectively** — 3-step workflow |
| `smart_search` | Codebase | Tree-sitter AST symbol search |
| `smart_outline` | Codebase | File structural outline |
| `smart_unfold` | Codebase | Symbol body extraction |
| `memory_build_collection` | Collections | Create knowledge collection |
| `memory_list_collections` | Collections | List all collections |
| `memory_export_collection` | Collections | Export as md/json/plain |
| `memory_query_collection` | Collections | **Semantic Q&A over a collection** |

### Progressive Disclosure Workflow

To minimize token usage, always follow this 3-layer pattern:

```
Step 1: memory_search or memory_semantic_search
  → Get compact index with IDs
  → Review and identify relevant results

Step 2: memory_timeline
  → Get context around interesting results
  → Narrow down to most relevant IDs

Step 3: memory_recall
  → Fetch full details ONLY for selected IDs
  → ~10x token savings vs fetching everything
```

> 💡 **Tip**: Call `memory_workflow()` first if unsure how to use the memory system.

---

## Kimi CLI Plugin Tools (3 tools)

## Tool Overview

| Tool | Purpose | Token Cost |
|------|---------|------------|
| `mneme_search` | Search memory index | ~50-100 tokens/result |
| `mneme_timeline` | Get chronological context | ~200-500 tokens/result |
| `mneme_get` | Fetch full details | ~500-1000 tokens/result |

## Progressive Disclosure Workflow

To minimize token usage, always follow this 3-layer pattern:

```
Step 1: mneme_search
  → Get compact index with IDs
  → Review and identify relevant results

Step 2: mneme_timeline
  → Get context around interesting results
  → Narrow down to most relevant IDs

Step 3: mneme_get
  → Fetch full details ONLY for selected IDs
  → ~10x token savings vs fetching everything
```

---

## mneme_search

Search the memory index with full-text and semantic queries.

### Parameters

```json
{
  "query": "authentication bug",
  "type": "bugfix",
  "limit": 10,
  "date_from": "2026-04-01",
  "date_to": "2026-05-01",
  "project": "my-project"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (natural language or keywords) |
| `type` | string | No | Filter by observation type: `bugfix`, `feature`, `refactor`, `docs`, `test` |
| `limit` | integer | No | Max results (default: 10, max: 50) |
| `date_from` | string | No | ISO date filter (inclusive) |
| `date_to` | string | No | ISO date filter (inclusive) |
| `project` | string | No | Filter by project/directory name |

### Returns

```json
{
  "results": [
    {
      "id": 123,
      "session_id": "sess_abc",
      "timestamp": "2026-04-15T10:30:00Z",
      "type": "PostToolUse",
      "tool_name": "WriteFile",
      "file_path": "src/auth.ts",
      "snippet": "Fixed JWT token validation...",
      "relevance_score": 0.92
    },
    {
      "id": 124,
      "session_id": "sess_abc",
      "timestamp": "2026-04-15T10:35:00Z",
      "type": "PostToolUseFailure",
      "tool_name": "Shell",
      "snippet": "npm test failed: auth middleware...",
      "relevance_score": 0.85
    }
  ],
  "total": 2,
  "query_time_ms": 45
}
```

### Example Usage

```
// Search for auth-related work
mneme_search(query="authentication middleware JWT", limit=5)

// Search for recent bug fixes
mneme_search(query="bug fix", type="bugfix", date_from="2026-04-01")

// Search in specific project
mneme_search(query="database migration", project="backend-api")
```

---

## mneme_timeline

Get chronological context around a specific observation.

### Parameters

```json
{
  "observation_id": 123,
  "radius": 5
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `observation_id` | integer | Yes | Center observation ID |
| `radius` | integer | No | Number of observations before/after (default: 5, max: 20) |

### Returns

```json
{
  "center": {
    "id": 123,
    "timestamp": "2026-04-15T10:30:00Z",
    "type": "PostToolUse",
    "tool_name": "WriteFile",
    "file_path": "src/auth.ts"
  },
  "before": [
    {
      "id": 120,
      "timestamp": "2026-04-15T10:25:00Z",
      "type": "UserPromptSubmit",
      "snippet": "Fix the auth bug where tokens..."
    },
    {
      "id": 121,
      "timestamp": "2026-04-15T10:27:00Z",
      "type": "PostToolUse",
      "tool_name": "ReadFile",
      "file_path": "src/auth.ts"
    }
  ],
  "after": [
    {
      "id": 124,
      "timestamp": "2026-04-15T10:35:00Z",
      "type": "PostToolUseFailure",
      "tool_name": "Shell",
      "snippet": "npm test failed..."
    }
  ]
}
```

### Example Usage

```
// See what happened around observation #123
mneme_timeline(observation_id=123, radius=3)
```

---

## mneme_get

Fetch full observation details by IDs. Always batch multiple IDs.

### Parameters

```json
{
  "ids": [123, 124, 125]
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ids` | array[integer] | Yes | Observation IDs to fetch |

### Returns

```json
{
  "observations": [
    {
      "id": 123,
      "session_id": "sess_abc",
      "timestamp": "2026-04-15T10:30:00Z",
      "type": "PostToolUse",
      "tool_name": "WriteFile",
      "tool_input": {
        "path": "src/auth.ts",
        "content": "..."
      },
      "tool_output": "File written successfully",
      "file_path": "src/auth.ts",
      "summary": "Fixed JWT validation by adding..."
    },
    {
      "id": 124,
      "session_id": "sess_abc",
      "timestamp": "2026-04-15T10:35:00Z",
      "type": "PostToolUseFailure",
      "tool_name": "Shell",
      "tool_input": {
        "command": "npm test"
      },
      "error": "3 tests failed in auth.test.ts",
      "file_path": null
    }
  ]
}
```

### Example Usage

```
// Fetch full details for observations #123 and #124
mneme_get(ids=[123, 124])
```

---

## Complete Search Example

```
User: "What was that auth bug we fixed last week?"

AI:
// Step 1: Search index
mneme_search(query="authentication bug fix", date_from="2026-04-25", limit=10)
→ Results: [#456, #457, #460, ...]

// Step 2: Review index, pick interesting IDs
// #456 looks relevant (high score, "JWT validation error")

// Step 3: Get timeline around #456
mneme_timeline(observation_id=456, radius=5)
→ Shows: user prompt → read file → edit file → test failure → fix → success

// Step 4: Fetch full details for key observations
mneme_get(ids=[456, 457, 460])
→ Full tool inputs/outputs

AI to user: "Last Tuesday you fixed a JWT validation bug in src/auth.ts. 
The issue was that tokens weren't being validated against the secret key. 
You added the validation and fixed 3 failing tests."
```

---

## Plugin Registration

The tools are declared in `plugin/plugin.json`:

```json
{
  "name": "kimi-mneme",
  "version": "1.1.0",
  "tools": [
    {
      "name": "mneme_search",
      "description": "Search memory index with full-text queries. Returns compact index with IDs, timestamps, types, and snippets. Use this as the first step in progressive disclosure.",
      "command": ["python3", "tools/search.py"],
      "parameters": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "type": { "type": "string", "enum": ["bugfix", "feature", "refactor", "docs", "test"] },
          "limit": { "type": "integer", "default": 10 },
          "date_from": { "type": "string" },
          "date_to": { "type": "string" },
          "project": { "type": "string" }
        },
        "required": ["query"]
      }
    },
    {
      "name": "mneme_timeline",
      "description": "Get chronological context around a specific observation. Shows what happened before and after. Use after mneme_search to understand context.",
      "command": ["python3", "tools/timeline.py"],
      "parameters": {
        "type": "object",
        "properties": {
          "observation_id": { "type": "integer" },
          "radius": { "type": "integer", "default": 5 }
        },
        "required": ["observation_id"]
      }
    },
    {
      "name": "mneme_get",
      "description": "Fetch full observation details by IDs. Always batch multiple IDs in one call. Use as the final step after identifying relevant observations.",
      "command": ["python3", "tools/get.py"],
      "parameters": {
        "type": "object",
        "properties": {
          "ids": { "type": "array", "items": { "type": "integer" } }
        },
        "required": ["ids"]
      }
    }
  ]
}
```

Install with:

```bash
kimi plugin install /path/to/kimi-mneme/plugin
```
