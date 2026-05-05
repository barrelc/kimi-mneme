# Privacy Guide

kimi-mneme takes privacy seriously. By default, sensitive content is excluded from storage.

## Automatic Exclusions

The following patterns are automatically excluded:

- Files matching: `*.env*`, `*.env.local`, `*secret*`, `*password*`, `*token*`, `*api_key*`, `*private_key*`
- Content longer than 100,000 characters (truncated)

## Privacy Tags

Wrap sensitive content in privacy tags to exclude it from storage:

```
User: Here's my database password: <private>super_secret_123</private>
```

The tag and its contents are replaced with `[PRIVATE]` before storage.

Supported tags (configurable):
- `<private>...</private>`
- `<secret>...</secret>`

## Custom Exclusion Patterns

Add to `~/.kimi/mneme/config.json`:

```json
{
  "privacy": {
    "exclude_patterns": [
      "*.local.env",
      "secrets/*",
      "*.pem",
      "*.key",
      "*credential*"
    ]
  }
}
```

## What Gets Stored

| Data | Stored? | Notes |
|------|---------|-------|
| File paths | ✅ Yes | Relative paths preferred |
| Tool names | ✅ Yes | ReadFile, WriteFile, Shell, etc. |
| Tool outputs (success) | ✅ Yes | Sanitized |
| Tool outputs (errors) | ✅ Yes | Helps learn from mistakes |
| User prompts | ✅ Yes | Intent and context |
| File contents | ⚠️ Partial | Only paths, not full content |
| API keys | ❌ No | Automatically excluded |
| Passwords | ❌ No | Automatically excluded |
| `<private>` blocks | ❌ No | Replaced with `[PRIVATE]` |

## What Gets Sent to the AI API

When AI structuring or compression is enabled, the following data is sent to the configured LLM provider (Kimi API, Ollama, or OpenAI-compatible API) **after** sanitization:

### AI Structuring (per observation)
- **Tool name** — e.g., `WriteFile`, `Shell`
- **Tool input** — first 500 chars (file paths, arguments)
- **Tool output** — first 2000 chars (truncated, sanitized)
- **Error message** — first 500 chars (if any)

### AI Compression (per session)
- **Formatted observation summaries** — tool names, file paths, first 500 chars of output per observation
- **Session context** — accumulated observations from the session

### Sanitization Pipeline (applied BEFORE API call)

```
Raw tool output
    ↓
[1] Strip system content — remove <system>, <system_instruction>, <system-reminder>
    ↓
[2] Redact sensitive patterns — API keys, tokens, passwords, private keys
    ↓
[3] Sanitize privacy tags — replace <private>...</private> with [PRIVATE]
    ↓
[4] Truncate — max 2000 chars for structuring, 500 per observation for compression
    ↓
Sent to API
```

### What NEVER leaves your machine

| Data | Sent to API? | Reason |
|------|-------------|--------|
| Full file contents | ❌ No | Only paths extracted |
| `<private>` blocks | ❌ No | Stripped before API call |
| System instructions | ❌ No | Stripped before API call |
| API keys / tokens | ❌ No | Redacted by regex patterns |
| Private keys (PEM) | ❌ No | Redacted by regex patterns |
| Passwords in URLs | ❌ No | Redacted by regex patterns |
| GitHub tokens | ❌ No | Redacted by regex patterns |
| Raw `~/.kimi/credentials` | ❌ No | Only OAuth token is read locally for auth |

> **Important:** The OAuth token from `~/.kimi/credentials/kimi-code.json` is read locally and used only for Kimi API authentication. It is never included in the data sent for structuring or compression. When using Ollama or other local LLMs, no external network calls are made.

## Data Location

All data is stored locally:

```
~/.kimi/mneme/
├── mneme.db          # SQLite database
├── vectors/          # Embeddings cache (optional)
├── config.json       # Configuration
├── backups/          # Automatic backups
└── mneme.log         # Log file
```

> **Note:** `sqlite3` CLI is required for database inspection and internal operations. Install via your system package manager (`apt install sqlite3`, `brew install sqlite3`, `winget install SQLite.SQLite`, etc.).

Nothing is sent to external servers except:
- AI structuring/compression (if enabled, sent to the configured LLM provider)
- You control the provider and can disable AI features entirely

## Disabling AI Features (100% Local Mode)

To keep everything 100% local with zero network calls:

```json
{
  "structuring": {
    "enabled": false
  },
  "compression": {
    "enabled": false
  }
}
```

Or via environment variable:

```bash
export MNEME_STRUCTURING_ENABLED=false
```

### Behavior without AI

| Feature | Behavior |
|---------|----------|
| **Observation storage** | ✅ Raw tool outputs stored locally (always) |
| **Structured metadata** | ⚠️ Heuristic fallback (rule-based type detection, title generation) |
| **Search** | ✅ Full-text (FTS5) + semantic (sqlite-vec) work fully |
| **Context injection** | ✅ Heuristic-based ranking and formatting |
| **Pattern detection** | ⚠️ Regex-based only (no AI semantic analysis) |
| **Session summaries** | ❌ Not generated (raw observations available instead) |

> **Note:** Heuristic structuring provides ~80% of the value with zero network dependency. The main difference is less rich metadata (no AI-generated facts, concepts, or narratives) — search and retrieval still work perfectly.

## Deleting Data

```bash
# Delete all data
rm -rf ~/.kimi/mneme

# Delete specific session
python -m mneme.db.delete --session-id sess_abc123

# Delete observations older than 30 days
python -m mneme.db.cleanup --days 30
```

## Encryption (Optional)

For additional security, enable SQLite encryption:

```json
{
  "db": {
    "encryption": {
      "enabled": true,
      "key": "${MNEME_DB_KEY}"
    }
  }
}
```

Requires `sqlcipher` or `pysqlcipher3`.
