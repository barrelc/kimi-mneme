# Web UI

> **Note:** `sqlite3` CLI is required for database inspection and internal operations. Install via your system package manager (`apt install sqlite3`, `brew install sqlite3`, `winget install SQLite.SQLite`, etc.).

kimi-mneme includes a web-based memory viewer at `http://localhost:37777`.

## Features

- **Real-time stream** — See observations as they happen via SSE
- **Search interface** — Full-text (FTS5) and semantic (sqlite-vec) search with recency filter
- **Session browser** — Explore past sessions chronologically
- **Timeline view** — See context around any observation
- **Statistics** — Memory usage, session counts, top projects, token economics
- **Checkpoints** — View session checkpoints and resume context
- **Patterns** — Browse detected cross-session patterns
- **Compaction history** — Track context compaction events
- **Skeleton loaders** — Shimmer animation while loading
- **Token economics** — `~Nt` badge per observation, savings % indicator
- **Per-card expand/collapse** — Toggle between compact and full view
- **Console drawer** — DevTools-style log panel with filters (All/Info/Warn/Error/Hook)
- **Welcome modal** — First-run feature highlights

## Starting the Server

### Automatic (default)

The server starts automatically when you run `kimi` if `server.enabled` is `true` in config.

### Manual

```bash
python -m mneme.server
```

Or with custom port:

```bash
python -m mneme.server --port 8080
```

## API Endpoints

### Health Check

```bash
GET /api/health
```

```json
{"status": "ok", "version": "2.0.18"}
```

### Search

```bash
GET /api/search?q=auth+bug&limit=10
```

```json
{
  "results": [...],
  "total": 42,
  "query_time_ms": 45
}
```

### Get Observation

```bash
GET /api/observation/123
```

```json
{
  "id": 123,
  "session_id": "sess_abc",
  "timestamp": "2026-04-15T10:30:00Z",
  "type": "PostToolUse",
  "tool_name": "WriteFile",
  "tool_input": {...},
  "tool_output": "...",
  "file_path": "src/auth.ts"
}
```

### Timeline

```bash
GET /api/timeline/123?radius=5
```

### Sessions

```bash
GET /api/sessions?limit=20&offset=0
```

### Statistics

```bash
GET /api/stats
```

```json
{
  "total_sessions": 150,
  "total_observations": 3200,
  "total_summaries": 45,
  "total_user_prompts": 890,
  "total_pending_messages": 12,
  "total_feedback": 34,
  "db_size_mb": 12.5,
  "top_projects": [
    {"project": "backend-api", "sessions": 45},
    {"project": "frontend-app", "sessions": 30}
  ],
  "queue": {
    "total": 12,
    "pending": 5,
    "processing": 3,
    "processed": 4,
    "failed": 0
  }
}
```

### Vector Search

```bash
GET /api/vector_search?q=authentication+middleware&limit=10
GET /api/vector_search?q=auth&limit=10&days=30  # last 30 days only
```

### Collections

```bash
# List collections
GET /api/collections

# Get collection details
GET /api/collections/my-collection

# Query collection with natural language
GET /api/collections/my-collection/query?q=How+do+we+handle+auth

# Export collection
GET /api/collections/my-collection/export?format=md
```

### Projects

```bash
GET /api/projects
```

## WebSocket

Real-time updates via WebSocket:

```javascript
const ws = new WebSocket('ws://localhost:37777/ws');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === 'stats') {
    console.log('Stats update:', msg.data);
  }
};

// Request stats
ws.send(JSON.stringify({action: 'stats'}));

// Ping/pong
ws.send(JSON.stringify({action: 'ping'}));
```

## Screenshots

### Memory Stream

```
┌─────────────────────────────────────────────────────────┐
│  🧠 kimi-mneme — Memory Stream                          │
├─────────────────────────────────────────────────────────┤
│  🔍 Search...                                    [⚙️]   │
├─────────────────────────────────────────────────────────┤
│  ┌─ Observation #1234 ──────────────────────────────┐   │
│  │ 📁 backend-api  🕐 2 min ago                      │   │
│  │ PostToolUse → WriteFile                           │   │
│  │ src/auth.ts — "Fixed JWT validation..."           │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌─ Observation #1233 ──────────────────────────────┐   │
│  │ 📁 backend-api  🕐 3 min ago                      │   │
│  │ UserPromptSubmit                                  │   │
│  │ "Fix the auth bug where tokens aren't validated"  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Search Results

```
┌─────────────────────────────────────────────────────────┐
│  🔍 "auth bug" — 12 results                             │
├─────────────────────────────────────────────────────────┤
│  [All] [Bugfix] [Feature] [Refactor] [Docs] [Test]     │
├─────────────────────────────────────────────────────────┤
│  #456  backend-api  Apr 15  Relevance: 95%              │
│  PostToolUse → WriteFile: src/auth.ts                   │
│  "Fixed JWT validation by adding secret key check"      │
│                                                         │
│  #457  backend-api  Apr 15  Relevance: 88%              │
│  PostToolUseFailure → Shell: npm test                   │
│  "3 tests failed in auth.test.ts"                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Session Checkpoints

```
┌─────────────────────────────────────────────────────────┐
│  📌 Session: sess_abc123 — Checkpoints                  │
├─────────────────────────────────────────────────────────┤
│  Checkpoint #3 (compaction) — 2 hours ago               │
│  Tokens: 5000 → 2000 | Observations: 42                 │
│                                                         │
│  Summary:                                               │
│  Session checkpoint after context compaction.           │
│                                                         │
│  Key Decisions:                                         │
│  • Use FastAPI for API layer                            │
│  • SQLite for local storage                             │
│                                                         │
│  Open Tasks:                                            │
│  • [ ] Add comprehensive tests                          │
│  • [ ] Deploy to staging                                │
├─────────────────────────────────────────────────────────┤
│  Checkpoint #2 (manual) — 3 hours ago                   │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

### Cross-Session Patterns

```
┌─────────────────────────────────────────────────────────┐
│  🔁 Recurring Patterns                                  │
├─────────────────────────────────────────────────────────┤
│  ❌ Recurring error in Shell (3×)                       │
│     Tool 'Shell' failed 3 times. Latest: npm test exit 1│
│     Related: backend-api, src/auth.test.ts              │
│                                                         │
│  ✅ Fix pattern for src/auth.ts (2×)                    │
│     Fixed error in src/auth.ts: JWT validation failed   │
│     Related: src/auth.ts                                │
│                                                         │
│  📝 Decision: Use PostgreSQL (4×)                       │
│     Database choice across multiple sessions            │
│     Related: backend-api                                │
└─────────────────────────────────────────────────────────┘
```
