# Architecture

## System Overview

kimi-mneme consists of 4 layers that work together to capture, compress, store, and retrieve coding session context.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Kimi Code CLI                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Lifecycle   │  │   Plugin     │  │      User Prompts        │  │
│  │   Hooks      │  │   Tools      │  │                          │  │
│  │  (7 hooks) │  │ (3 commands) │  │                          │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
└─────────┼─────────────────┼─────────────────────────────────────────┘
          │                 │
          ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Core Engine                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Extractor   │  │  Compressor  │  │       Injector           │  │
│  │              │  │              │  │                          │  │
│  │ - Parse tool │  │ - Semantic   │  │ - Query relevant         │  │
│  │   calls      │  │   summary    │  │   context                │  │
│  │ - Extract    │  │ - Keyword    │  │ - Format for LLM         │  │
│  │   file paths │  │   extraction │  │ - Inject at session      │  │
│  │ - Capture    │  │ - Token      │  │   start                  │  │
│  │   errors     │  │   counting   │  │ - Cross-session patterns │  │
│  │ - Detect     │  │              │  │                          │  │
│  │   truncation │  │              │  │                          │  │
│  │ - Checkpoint │  │              │  │                          │  │
│  │   on compact│  │              │  │                          │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
└─────────┼─────────────────┼─────────────────────────────────────────┘
          │                 │
          ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Storage Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │   SQLite     │  │  sqlite-vec  │  │      Web Server          │  │
│  │              │  │   (vectors)  │  │                          │  │
│  │ - Sessions   │  │              │  │ - FastAPI app            │  │
│  │ - Observations│  │ - Embeddings │  │ - REST API               │  │
│  │ - Summaries  │  │ - Similarity │  │ - WebSocket for          │  │
│  │ - Checkpoints│  │   search     │  │   real-time updates      │  │
│  │ - Patterns   │  │              │  │                          │  │
│  │ - Compaction │  │              │  │                          │  │
│  │ - Truncated  │  │              │  │                          │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Capture (Session Recording)

```
User runs kimi → SessionStart hook fires → Create session record
     ↓
User sends prompt → UserPromptSubmit hook → Store prompt
     ↓
AI uses tool → PostToolUse hook → Extract and store observation
     ↓
Context compaction → PostCompact hook → Create checkpoint
     ↓
Session ends → SessionEnd hook → Mark session complete + detect patterns
```

### 2. Compression (AI Summarization)

```
Raw observations → Sanitization pipeline (3-layer privacy filter)
     ↓
Extractor (clean & structure)
     ↓
Compressor (configurable LLM: Kimi/Ollama/OpenAI-compatible) → Semantic summary
     ↓
Store summary + keywords in SQLite
     ↓
Generate embedding → Store in sqlite-vec
```

**Sanitization pipeline** (applied before any AI processing):
1. **Strip system content** — remove `<system>`, `<system_instruction>`, `<system-reminder>` tags
2. **Redact sensitive patterns** — API keys, tokens, passwords, private keys via regex
3. **Sanitize privacy tags** — replace `<private>...</private>` with `[PRIVATE]`
4. **Truncate** — limit content length before API call

### 3. Retrieval (Context Injection)

```
New session starts → SessionStart hook
     ↓
Check for previous checkpoints → Inject resume context
     ↓
Query cross-session patterns → Inject recurring patterns
     ↓
Injector queries sqlite-vec (vector search)
     ↓
Rank by relevance + recency
     ↓
Format as context block
     ↓
Inject into system prompt
```

### 4. Search (AI-Initiated)

```
User asks "find that auth bug" → AI calls mneme_search
     ↓
Plugin tool → Hybrid search (SQLite FTS + sqlite-vec vectors)
     ↓
Progressive disclosure:
  Layer 1: Compact index (~50 tokens/result)
  Layer 2: Timeline around results
  Layer 3: Full details for selected IDs
     ↓
Return to AI
```

## Database Schema

### SQLite

> **Note:** `sqlite3` CLI is required for database inspection and internal operations. Install via your system package manager (`apt install sqlite3`, `brew install sqlite3`, `winget install SQLite.SQLite`, etc.).

```sql
-- Sessions table
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    cwd TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT,
    token_count INTEGER,
    project TEXT
);

-- Observations table (raw events)
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- PostToolUse, UserPromptSubmit, etc.
    tool_name TEXT,
    tool_input TEXT,
    tool_output TEXT,
    error TEXT,
    file_path TEXT,
    prompt TEXT,
    agent_name TEXT,
    content_hash TEXT,         -- SHA-256 for deduplication
    discovery_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Summaries table (AI-compressed)
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    observation_ids TEXT,  -- JSON array of source observation IDs
    content TEXT NOT NULL,
    keywords TEXT,  -- JSON array
    embedding_id TEXT  -- vec table reference
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Session checkpoints (for resume after compaction/crash)
CREATE TABLE session_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    checkpoint_number INTEGER NOT NULL DEFAULT 1,
    checkpoint_type TEXT NOT NULL DEFAULT 'auto'
        CHECK(checkpoint_type IN ('auto', 'manual', 'compaction', 'crash')),
    summary TEXT NOT NULL,
    key_decisions TEXT,        -- JSON array
    open_tasks TEXT,           -- JSON array
    token_count INTEGER,
    observation_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Compaction events (context compaction tracking)
CREATE TABLE compaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    compacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tokens_before INTEGER,
    tokens_after INTEGER,
    observations_dropped INTEGER,
    summary_generated TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Cross-session patterns (errors, fixes, decisions)
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type TEXT NOT NULL
        CHECK(pattern_type IN ('error', 'fix', 'decision', 'preference', 'architecture')),
    pattern_hash TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    first_seen_session_id TEXT,
    last_seen_session_id TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    related_files TEXT,        -- JSON array
    related_observation_ids TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Truncated tool outputs (>100K chars)
CREATE TABLE truncated_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    original_size INTEGER NOT NULL,
    truncated_size INTEGER NOT NULL,
    summary TEXT,
    head_preview TEXT,
    tail_preview TEXT,
    line_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE
);

-- Structured observations (AI/heuristic structured metadata)
CREATE TABLE structured_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    type TEXT NOT NULL
        CHECK(type IN ('bugfix', 'feature', 'refactor', 'change', 'discovery', 'decision')),
    title TEXT NOT NULL,
    subtitle TEXT,
    facts TEXT,          -- JSON array of strings
    narrative TEXT,      -- Brief description (1-2 sentences)
    concepts TEXT,       -- JSON array: how-it-works, why-it-exists, etc.
    files_read TEXT,     -- JSON array of file paths
    files_modified TEXT, -- JSON array of file paths
    content_hash TEXT NOT NULL,
    discovery_tokens INTEGER DEFAULT 0,
    raw_observation_id INTEGER,
    source TEXT DEFAULT 'ai'  -- 'ai', 'heuristic', 'manual'
        CHECK(source IN ('ai', 'heuristic', 'manual')),
    model TEXT,          -- 'kimi-k2.5', 'heuristic', etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (raw_observation_id) REFERENCES observations(id) ON DELETE SET NULL,
    UNIQUE(session_id, content_hash)
);

-- Soft dedup links between structured observations and raw observations
CREATE TABLE structured_observation_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_structured_id INTEGER NOT NULL,
    linked_raw_observation_id INTEGER,
    content_hash TEXT NOT NULL,
    link_type TEXT DEFAULT 'soft' CHECK(link_type IN ('soft', 'hard')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (existing_structured_id) REFERENCES structured_observations(id) ON DELETE CASCADE,
    FOREIGN KEY (linked_raw_observation_id) REFERENCES observations(id) ON DELETE CASCADE
);

-- Vector sync state (watermark-based)
CREATE TABLE vec_sync_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    last_synced_id INTEGER DEFAULT 0,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge collections
CREATE TABLE observation_collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    project TEXT,
    query TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Collection items
CREATE TABLE collection_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    item_type TEXT DEFAULT 'structured' CHECK(item_type IN ('structured', 'raw')),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES observation_collections(id) ON DELETE CASCADE,
    FOREIGN KEY (observation_id) REFERENCES structured_observations(id) ON DELETE CASCADE,
    UNIQUE(collection_id, observation_id)
);

-- Full-text search index (raw observations)
CREATE VIRTUAL TABLE observations_fts USING fts5(
    content='observations',
    content_rowid='id',
    tool_name, tool_input, tool_output
);

-- Full-text search index (structured observations)
CREATE VIRTUAL TABLE structured_observations_fts USING fts5(
    title,
    subtitle,
    narrative,
    facts,
    concepts,
    content='structured_observations',
    content_rowid='id'
);
```

### sqlite-vec Vector DB

```python
# Collection: mneme_observations
{
    "ids": ["obs_123", "obs_124", ...],
    "embeddings": [[0.1, 0.2, ...], ...],
    "metadatas": [
        {
            "session_id": "sess_abc",
            "event_type": "PostToolUse",
            "tool_name": "WriteFile",
            "file_path": "/project/src/auth.ts",
            "timestamp": "2026-05-02T10:00:00Z"
        },
        ...
    ],
    "documents": ["Created auth middleware...", ...]
}
```

## Hook Events

| Event | Trigger | Data Captured |
|-------|---------|---------------|
| `SessionStart` | New/resumed session | `session_id`, `cwd`, `source` |
| `UserPromptSubmit` | User sends message | `prompt` |
| `PreToolUse` | Before tool execution | `tool_name`, `tool_input` |
| `PostToolUse` | After successful tool | `tool_name`, `tool_input`, `tool_output` |
| `PostToolUseFailure` | After failed tool | `tool_name`, `tool_input`, `error` |
| `SubagentStart` | Subagent launched | `agent_name`, `prompt` |
| `SubagentStop` | Subagent completed | `agent_name`, `response` |
| `PreCompact` | Before context compaction | `trigger`, `token_count` |
| `PostCompact` | After compaction | `trigger`, `estimated_token_count` |
| `Stop` | Agent turn ends | `stop_hook_active` |
| `StopFailure` | Turn ended with error | `error_type`, `error_message` |
| `SessionEnd` | Session closed | `reason` |
| `Notification` | Notification delivered | `sink`, `type`, `title`, `body` |

## Plugin Tools

| Tool | Purpose | Parameters |
|------|---------|------------|
| `mneme_search` | Search memory index | `query`, `type`, `limit`, `date_from`, `date_to` |
| `mneme_timeline` | Get chronological context | `observation_id`, `radius` |
| `mneme_get` | Fetch full observation details | `ids` (array) |

## MCP Tools (15 total)

| Tool | Purpose |
|------|---------|
| `memory_search` | FTS5 search over structured observations |
| `memory_semantic_search` | sqlite-vec semantic search (with `days` recency filter) |
| `memory_recall` | Get full observation by ID |
| `memory_timeline` | Chronological observations for a session |
| `memory_stats` | Memory statistics |
| `memory_by_concept` | Search by concept tag |
| `memory_by_file` | Find observations related to a file |
| `memory_workflow` | **How to use memory effectively** (3-step guide) |
| `smart_search` | Tree-sitter AST symbol search |
| `smart_outline` | File structural outline |
| `smart_unfold` | Symbol body extraction |
| `memory_build_collection` | Create knowledge collection |
| `memory_list_collections` | List collections |
| `memory_export_collection` | Export collection (md/json/plain) |
| `memory_query_collection` | **Semantic Q&A over collection** |

## Progressive Disclosure

To minimize token usage, search follows a 3-layer pattern:

```
Layer 1: mneme_search
  → Returns compact index: id, timestamp, type, snippet
  → ~50-100 tokens per result

Layer 2: mneme_timeline
  → Returns context around specific observation
  → ~200-500 tokens per result

Layer 3: mneme_get
  → Returns full observation details
  → ~500-1000 tokens per result

Total savings: ~10x vs fetching everything upfront
```

## Session Checkpoint & Resume

When Kimi CLI compacts context mid-session, mneme creates a checkpoint:

```
PostCompact hook fires
     ↓
Record compaction event (tokens_before, tokens_after)
     ↓
Extract key decisions from recent observations
     ↓
Extract open tasks from user prompts
     ↓
Create checkpoint with summary + decisions + tasks
     ↓
On next SessionStart: inject checkpoint context
```

Resume context format:
```markdown
## 📌 Session Resume Context
**Checkpoint #3** (compaction)

### Summary
Session checkpoint after context compaction. Tokens reduced from 5000 to 2000.

### Key Decisions
- Use FastAPI for API layer
- SQLite for local storage

### Open Tasks
- [ ] Add comprehensive tests
- [ ] Deploy to staging
```

## Cross-Session Pattern Detection

mneme automatically detects recurring patterns across sessions:

| Pattern Type | Detection Method | Example |
|-------------|------------------|---------|
| `error` | Same tool fails ≥2 times | "Recurring error in Shell: npm test" |
| `fix` | Error followed by success on same file | "Fixed error in src/auth.ts" |
| `decision` | User prompt contains decision keywords | "Decided to use PostgreSQL" |
| `preference` | Repeated coding style choices | "Prefer TypeScript over JavaScript" |
| `architecture` | Structural decisions | "Use repository pattern for DB access" |

Patterns are injected into new sessions as "Recurring Patterns" section.

## Privacy Model

Content wrapped in `<private>...</private>` tags is excluded from storage:

```python
def sanitize_content(text: str) -> str:
    """Remove private blocks before storage."""
    import re
    return re.sub(r'<private>.*?</private>', '[PRIVATE]', text, flags=re.DOTALL)
```

Additional exclusion via patterns in config:

```json
{
  "privacy": {
    "exclude_patterns": ["*.env*", "*secret*", "*password*", "*token*"]
  }
}
```

## Compression Strategy

Raw observations are compressed when:
- Session ends
- Token count exceeds threshold
- Explicitly requested

Compression prompt:

```
Summarize the following coding session observations into a concise,
semantic summary. Include:
- What was accomplished
- Key files modified
- Important decisions made
- Any errors or blockers

Observations:
{observations}

Summary:
```

## Cross-Platform Support

### Platform-Specific Components

| Component | Windows | macOS | Linux | iOS/BSD |
|-----------|---------|-------|-------|---------|
| Filesystem Watcher | `WindowsApiObserver` | `FSEventsObserver` | `InotifyObserver` | `PollingObserver` |
| Event Loop | `winloop` (optional) | `asyncio` | `asyncio` | `asyncio` |
| Process Launch | `CREATE_NEW_PROCESS_GROUP` | `start_new_session` | `start_new_session` | `start_new_session` |
| Server Logs | `~/.kimi/mneme/server.log` | `~/.kimi/mneme/server.log` | `~/.kimi/mneme/server.log` | `~/.kimi/mneme/server.log` |

### Windows Notes

- **Process survival**: Server uses `CREATE_NEW_PROCESS_GROUP` flag to survive parent console closure
- **No console window**: `CREATE_NO_WINDOW` prevents popup console window
- **Event loop**: Optional `winloop` package provides better async performance than default `asyncio`
- **Background scan**: Disabled by default on large databases to prevent startup overload

### macOS/Linux Notes

- **Session management**: `start_new_session=True` detaches from parent session
- **Logs**: Server stdout/stderr redirected to `~/.kimi/mneme/server.log`

## Performance Considerations

| Metric | Target |
|--------|--------|
| Hook execution | < 100ms (fire-and-forget) |
| Search query | < 500ms |
| Vector search | < 200ms |
| Collection query | < 500ms |
| Web UI load | < 1s |
| DB size growth | ~1MB per 100 sessions |
| Checkpoint creation | < 50ms |
| Pattern detection | < 100ms (async) |

## Security

- All hook commands run in isolated subprocess
- Database is local-only (no network access)
- API key stored in config or env var, not in code
- Privacy tags prevent accidental data leakage
- Truncated outputs preserve head/tail previews without full content
