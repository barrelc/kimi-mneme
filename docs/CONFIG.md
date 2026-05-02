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
    "path": "~/.kimi/mneme/chroma",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "chunk_size": 512,
    "chunk_overlap": 50
  },
  "compression": {
    "enabled": true,
    "provider": "moonshot",
    "model": "moonshot-v1-8k",
    "api_key": "${MOONSHOT_API_KEY}",
    "batch_size": 10,
    "min_observations": 5,
    "trigger": "session_end"
  },
  "injection": {
    "enabled": true,
    "max_tokens": 2000,
    "min_relevance": 0.7,
    "max_results": 5,
    "recency_boost_days": 7,
    "format": "markdown",
    "include_patterns": true,
    "include_checkpoints": true
  },
  "server": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 37777,
    "cors_origins": ["http://localhost:37777"],
    "auth_token": null
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

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db.path` | string | `~/.kimi/mneme/mneme.db` | SQLite database file path |
| `db.backup_enabled` | boolean | `true` | Enable automatic backups |
| `db.backup_interval_days` | integer | `7` | Days between backups |

### Vector Store

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `vector.path` | string | `~/.kimi/mneme/chroma` | Chroma DB directory |
| `vector.embedding_model` | string | `sentence-transformers/all-MiniLM-L6-v2` | Model for embeddings |
| `vector.chunk_size` | integer | `512` | Text chunk size for embedding |
| `vector.chunk_overlap` | integer | `50` | Overlap between chunks |

### Compression (AI Summarization)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `compression.enabled` | boolean | `true` | Enable AI compression |
| `compression.provider` | string | `moonshot` | LLM provider |
| `compression.model` | string | `moonshot-v1-8k` | Model name |
| `compression.api_key` | string | `${MOONSHOT_API_KEY}` | API key (supports env var) |
| `compression.batch_size` | integer | `10` | Observations per batch |
| `compression.min_observations` | integer | `5` | Min observations to compress |
| `compression.trigger` | string | `session_end` | When to compress: `session_end`, `threshold`, `manual` |

### Context Injection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `injection.enabled` | boolean | `true` | Inject past context at session start |
| `injection.max_tokens` | integer | `2000` | Max tokens to inject |
| `injection.min_relevance` | float | `0.7` | Minimum relevance score (0.0–1.0) |
| `injection.max_results` | integer | `5` | Max sessions to inject |
| `injection.recency_boost_days` | integer | `7` | Only consider sessions within N days |
| `injection.format` | string | `markdown` | Output format: `markdown`, `json`, `plain` |
| `injection.include_patterns` | boolean | `true` | Include cross-session patterns in injection |
| `injection.include_checkpoints` | boolean | `true` | Include session checkpoints in injection |

### Web Server

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.enabled` | boolean | `true` | Start web server |
| `server.host` | string | `127.0.0.1` | Bind address |
| `server.port` | integer | `37777` | Port number |
| `server.cors_origins` | array | `["http://localhost:37777"]` | Allowed CORS origins |
| `server.auth_token` | string | `null` | Optional Bearer token |

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
export MNEME_CHROMA_PATH="/custom/path/chroma"

# Compression
export MOONSHOT_API_KEY="sk-..."
export MNEME_COMPRESSION_ENABLED="true"

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
