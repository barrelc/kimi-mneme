# Configuration

## Configuration File

Default location: `~/.kimi/mneme/config.json`

Created automatically on first run with sensible defaults.

## Full Configuration Reference

```json
{
  "db": {
    "path": "~/.kimi/mneme/mneme.db",
    "backup_enabled": true,
    "backup_interval_days": 7
  },
  "vector": {
    "path": "~/.kimi/mneme/vectors",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "chunk_size": 512,
    "chunk_overlap": 50
  },
  "llm": {
    "provider": "kimi",
    "model": "kimi-k2.5",
    "base_url": null,
    "api_key": null,
    "timeout": 60.0,
    "options": {}
  },
  "compression": {
    "enabled": true,
    "provider": null,
    "model": null,
    "batch_size": 10,
    "min_observations": 5,
    "trigger": "session_end"
  },
  "structuring": {
    "enabled": true,
    "provider": null,
    "model": null,
    "fallback_to_heuristic": true,
    "heuristic_threshold_chars": 300,
    "batch_size": 5,
    "worker_interval_seconds": 5,
    "max_retry_count": 3
  },
  "injection": {
    "enabled": true,
    "max_tokens": 1500,
    "min_relevance": 0.7,
    "max_results": 2,
    "recency_boost_days": 7,
    "format": "markdown",
    "use_vector": false
  },
  "server": {
    "enabled": true,
    "auto_start": true,
    "host": "127.0.0.1",
    "port": 37777,
    "cors_origins": ["http://localhost:37777", "http://127.0.0.1:37777"],
    "loop": "auto"
  },
  "mcp": {
    "enabled": true,
    "auto_start": false,
    "transport": "stdio",
    "port": 37778
  },
  "privacy": {
    "exclude_tags": ["<private>", "<secret>"],
    "exclude_patterns": [
      "*.env*",
      "*.env.local",
      "*secret*",
      "*password*",
      "*token*",
      "*api_key*",
      "*private_key*"
    ],
    "max_content_length": 100000
  },
  "hooks": {
    "fire_and_forget": true,
    "timeout_seconds": 30,
    "batch_writes": true,
    "batch_interval_seconds": 5
  },
  "logging": {
    "level": "INFO",
    "file": "~/.kimi/mneme/mneme.log",
    "max_size_mb": 10,
    "backup_count": 5
  }
}
```

## Configuration Sections

### Database

> **Note:** `sqlite3` CLI is required for database inspection and internal operations. Install via your system package manager (`apt install sqlite3`, `brew install sqlite3`, `winget install SQLite.SQLite`, etc.).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db.path` | string | `~/.kimi/mneme/mneme.db` | SQLite database file path |
| `db.backup_enabled` | boolean | `true` | Enable automatic backups |
| `db.backup_interval_days` | integer | `7` | Days between backups |

### Vector Store

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `vector.path` | string | `~/.kimi/mneme/vectors` | Vector store directory (embeddings cache) |
| `vector.embedding_model` | string | `sentence-transformers/all-MiniLM-L6-v2` | Model for embeddings |
| `vector.chunk_size` | integer | `512` | Text chunk size for embedding |
| `vector.chunk_overlap` | integer | `50` | Overlap between chunks |

### LLM (Global Settings)

The `llm` section defines the default provider for all AI-powered features (structuring, compression). Individual sections (`compression`, `structuring`) can override these with their own `provider` and `model`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `llm.provider` | string | `kimi` | LLM provider: `kimi`, `ollama`, `openai_compatible` |
| `llm.model` | string | `kimi-k2.5` | Model name (provider-specific) |
| `llm.base_url` | string | `null` | Custom base URL for the API |
| `llm.api_key` | string | `null` | API key or token |
| `llm.timeout` | float | `60.0` | Request timeout in seconds |
| `llm.options` | object | `{}` | Provider-specific extra options |

#### Provider Examples

**Kimi** (default, uses OAuth token from kimi-cli):
```json
{
  "llm": {
    "provider": "kimi",
    "model": "kimi-k2.5"
  }
}
```

**Ollama** (local):
```json
{
  "llm": {
    "provider": "ollama",
    "model": "llama3.2",
    "base_url": "http://localhost:11434"
  }
}
```

**OpenAI-compatible** (vLLM, LM Studio, etc.):
```json
{
  "llm": {
    "provider": "openai_compatible",
    "model": "qwen2.5-coder",
    "base_url": "http://localhost:8000/v1",
    "api_key": "sk-optional"
  }
}
```

### Compression (AI Summarization)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `compression.enabled` | boolean | `true` | Enable AI compression |
| `compression.provider` | string | `null` | Override `llm.provider` (null = use global) |
| `compression.model` | string | `null` | Override `llm.model` (null = use global) |
| `compression.batch_size` | integer | `10` | Observations per batch |
| `compression.min_observations` | integer | `5` | Min observations to compress |
| `compression.trigger` | string | `session_end` | When to compress: `session_end`, `threshold`, `manual` |

### Structuring

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `structuring.enabled` | boolean | `true` | Enable AI structuring |
| `structuring.provider` | string | `null` | Override `llm.provider` (null = use global) |
| `structuring.model` | string | `null` | Override `llm.model` (null = use global) |
| `structuring.fallback_to_heuristic` | boolean | `true` | Use heuristic when AI fails |
| `structuring.heuristic_threshold_chars` | integer | `300` | Use heuristic for short outputs |
| `structuring.batch_size` | integer | `5` | Observations per batch |
| `structuring.worker_interval_seconds` | integer | `5` | Worker poll interval |
| `structuring.max_retry_count` | integer | `3` | Max retries per observation |

### Context Injection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `injection.enabled` | boolean | `true` | Inject past context at session start |
| `injection.max_tokens` | integer | `1500` | Max tokens to inject |
| `injection.min_relevance` | float | `0.7` | Minimum relevance score (0.0–1.0) |
| `injection.max_results` | integer | `2` | Max sessions to inject |
| `injection.recency_boost_days` | integer | `7` | Only consider sessions within N days |
| `injection.format` | string | `markdown` | Output format: `markdown`, `json`, `plain` |
| `injection.use_vector` | boolean | `false` | Use vector search for relevance scoring |

### Web Server

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.enabled` | boolean | `true` | Start web server |
| `server.auto_start` | boolean | `true` | Auto-start server on launch |
| `server.host` | string | `127.0.0.1` | Bind address |
| `server.port` | integer | `37777` | Port number |
| `server.cors_origins` | array | `["http://localhost:37777", "http://127.0.0.1:37777"]` | Allowed CORS origins |

| `server.loop` | string | `auto` | Event loop: `auto`, `asyncio`, `winloop` (Windows only) |

### MCP Server

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mcp.enabled` | boolean | `true` | Enable MCP server |
| `mcp.auto_start` | boolean | `false` | Auto-start MCP with FastAPI |
| `mcp.transport` | string | `stdio` | Transport: `stdio` or `sse` |
| `mcp.port` | integer | `37778` | Port for SSE transport |

### Privacy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `privacy.exclude_tags` | array | `["<private>", "<secret>"]` | HTML-like tags to exclude |
| `privacy.exclude_patterns` | array | `["*.env*", ...]` | Glob patterns to exclude |
| `privacy.max_content_length` | integer | `100000` | Max characters to store |

### Hooks

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `hooks.fire_and_forget` | boolean | `true` | Non-blocking hook execution |
| `hooks.timeout_seconds` | integer | `30` | Hook timeout |
| `hooks.batch_writes` | boolean | `true` | Batch DB writes |
| `hooks.batch_interval_seconds` | integer | `5` | Batch flush interval |

### Logging

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `logging.level` | string | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |
| `logging.file` | string | `~/.kimi/mneme/mneme.log` | Log file path |
| `logging.max_size_mb` | integer | `10` | Max log file size |
| `logging.backup_count` | integer | `5` | Number of backup files |

## Environment Variables

All config values can be overridden via environment variables:

```bash
# Database
export MNEME_DB_PATH="/custom/path/mneme.db"

# Vector store
# Vector store (embeddings cache, optional)
# export MNEME_VECTOR_PATH="/custom/path/vectors"

# LLM provider
export MNEME_LLM_PROVIDER="ollama"
export MNEME_LLM_MODEL="llama3.2"
export MNEME_LLM_BASE_URL="http://localhost:11434"
export MNEME_LLM_API_KEY="sk-..."

# Structuring
export MNEME_STRUCTURING_ENABLED="true"

# Server
export MNEME_SERVER_PORT="37777"
export MNEME_SERVER_HOST="0.0.0.0"

# Logging
export MNEME_LOG_LEVEL="DEBUG"
```

Environment variables take precedence over config file values.

## Per-Project Configuration

Create `.mneme.json` in project root for project-specific settings:

```json
{
  "llm": {
    "provider": "ollama",
    "model": "codellama"
  },
  "privacy": {
    "exclude_patterns": ["*.local.env", "secrets/"]
  },
  "injection": {
    "max_tokens": 1000,
    "recency_boost_days": 14,
    "include_patterns": true
  },
  "compression": {
    "min_observations": 3
  }
}
```

Project config merges with global config (project values override global). The file is searched in:
1. Current working directory
2. Parent directories (up to filesystem root)

This makes it work automatically when you `cd` into a project.
