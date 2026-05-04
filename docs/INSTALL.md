# Installation Guide

## Prerequisites

- **Python**: 3.10 or higher
- **Kimi Code CLI**: 1.40 or higher (`kimi --version`)
- **pip** or **uv**: for Python package management

## Quick Install (recommended)

### Via `uvx` (one command)

```bash
uvx --from git+https://github.com/barrelc/kimi-mneme.git mneme bootstrap
```

This single command:
- Installs all Python dependencies
- Registers hooks in `~/.kimi/config.toml`
- Installs the Kimi CLI plugin
- Creates the SQLite database
- Starts the web server

### Via `pip`

```bash
pip install kimi-mneme
mneme bootstrap
```

### From source

```bash
git clone https://github.com/barrelc/kimi-mneme.git
cd kimi-mneme
pip install -e .
mneme bootstrap
```

---

## Manual Install

If you prefer to understand each step:

### 1. Install Python Dependencies

```bash
pip install -e .
```

Or with uv:

```bash
uv pip install -e .
```

### 2. Initialize Database

```bash
mneme init
```

### 3. Register Hooks

```bash
mneme bootstrap --no-plugin --no-server
```

Or manually add to `~/.kimi/config.toml`:

```toml
[[hooks]]
event = "SessionStart"
command = "python /path/to/kimi-mneme/hooks/session_start.py"

[[hooks]]
event = "SessionEnd"
command = "python /path/to/kimi-mneme/hooks/session_end.py"

[[hooks]]
event = "PostToolUse"
command = "python /path/to/kimi-mneme/hooks/post_tool_use.py"

[[hooks]]
event = "PostToolUseFailure"
command = "python /path/to/kimi-mneme/hooks/post_tool_use_failure.py"

[[hooks]]
event = "UserPromptSubmit"
command = "python /path/to/kimi-mneme/hooks/user_prompt_submit.py"
```

> **Note**: Use `python` (not `python3`) — the bootstrap command automatically uses the correct Python executable for your system (`sys.executable`).

### 4. Install Plugin

```bash
kimi plugin install /path/to/kimi-mneme/plugin
```

### 5. Start Web Server (optional)

```bash
mneme server
```

The server runs on `http://localhost:37777` by default.

### Platform Notes

**Windows**: The server is started with `CREATE_NEW_PROCESS_GROUP` flag so it survives when the parent console (e.g., Kimi CLI) exits. Logs are written to `~/.kimi/mneme/server.log`.

**macOS/Linux**: The server runs as a background process with `start_new_session=True`. Logs are written to `~/.kimi/mneme/server.log`.

---

## Configuration

Create `~/.kimi/mneme/config.json`:

```json
{
  "db": {
    "path": "~/.kimi/mneme/mneme.db"
  },
  "vector": {
    "path": "~/.kimi/mneme/chroma"
  },
  "compression": {
    "enabled": true,
    "model": "moonshot-v1-8k",
    "api_key": "${MOONSHOT_API_KEY}"
  },
  "injection": {
    "enabled": true,
    "max_tokens": 2000,
    "min_relevance": 0.7,
    "recency_boost_days": 7
  },
  "privacy": {
    "exclude_patterns": ["*.env*", "*secret*", "*password*"]
  }
}
```

### Per-Project Configuration

Create `.mneme.json` in your project root for project-specific settings:

```json
{
  "injection": {
    "max_tokens": 1000,
    "recency_boost_days": 14
  },
  "privacy": {
    "exclude_patterns": ["*.local.env", "secrets/"]
  }
}
```

Project config merges with global config (project values override global).

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MNEME_DB_PATH` | SQLite database path | `~/.kimi/mneme/mneme.db` |
| `MNEME_CHROMA_PATH` | Chroma vector DB path | `~/.kimi/mneme/chroma` |
| `MNEME_SERVER_PORT` | Web server port | `37777` |
| `MOONSHOT_API_KEY` | API key for AI compression | — |
| `MNEME_LOG_LEVEL` | Logging level | `INFO` |
| `MNEME_SERVER_HOST` | Web server host | `127.0.0.1` |

---

## Verify Installation

```bash
# Check mneme CLI
mneme stats

# Check hooks
kimi
/hooks

# Check plugin
kimi plugin list

# Check web server
curl http://localhost:37777/api/health
```

---

## Uninstall

```bash
# Remove hooks, plugin, and data
python scripts/uninstall.py

# Or keep data
python scripts/uninstall.py --keep-data
```

Or manually:

```bash
# Remove hooks from ~/.kimi/config.toml
# Remove plugin
kimi plugin remove kimi-mneme
# Remove data
rm -rf ~/.kimi/mneme
```
