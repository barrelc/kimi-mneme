# Development Guide

## Setup

```bash
git clone https://github.com/barrelc/kimi-mneme.git
cd kimi-mneme

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

# Install in editable mode with dev dependencies
uv pip install -e ".[dev]"
# Or with pip:
pip install -e ".[dev]"
```

> **Note:** `sqlite3` CLI is required for database inspection and internal operations. Install via your system package manager (`apt install sqlite3`, `brew install sqlite3`, `winget install SQLite.SQLite`, etc.).

## Project Structure

```
kimi-mneme/
├── hooks/              # Kimi CLI lifecycle hook scripts
│   ├── session_start.py
│   ├── session_end.py
│   ├── post_tool_use.py
│   ├── post_tool_use_failure.py
│   ├── pre_compact.py
│   ├── post_compact.py
│   └── user_prompt_submit.py
├── plugin/             # Kimi CLI plugin
│   ├── plugin.json
│   └── config.json
├── mneme/              # Main package
│   ├── core/           # Business logic
│   │   ├── ai_provider.py          # ConfigurableAIProvider + HybridProvider
│   │   ├── codebase_analyzer.py    # Tree-sitter AST analysis
│   │   ├── compressor.py           # AI session compression
│   │   ├── extractor.py            # Raw observation extraction
│   │   ├── heuristic_structuring.py# Rule-based structuring fallback
│   │   ├── injector.py             # Context injection at session start
│   │   ├── llm_client.py           # Unified LLM client (Kimi/Ollama/OpenAI)
│   │   ├── project_md.py           # AGENTS.md + PROJECT.md generation
│   │   ├── sanitize.py             # Privacy filtering (3-layer)
│   │   ├── session_summary.py      # Session summary generation
│   │   ├── summarizer.py           # Text summarization
│   │   ├── worker.py               # Background StructuringWorker
│   │   └── prompts/                # AI prompts & JSON parser
│   │       ├── json_parser.py
│   │       └── observation_prompt.py
│   ├── db/             # Database layer
│   │   ├── schema.py               # 18 migrations
│   │   ├── store.py                # Raw observations + pending queue
│   │   ├── structured_store.py     # Structured observations + FTS5
│   │   ├── vector.py               # sqlite-vec embeddings
│   │   ├── collections_store.py    # Knowledge Collections
│   │   └── wire_store.py           # Wire events
│   ├── server/         # Web UI + API
│   │   ├── app.py                  # FastAPI app + lifespan
│   │   ├── routes.py               # 30+ REST endpoints
│   │   └── static/
│   │       ├── index.html
│   │       ├── style.css
│   │       └── app.js
│   ├── wire/           # Wire protocol (MCP logs)
│   │   ├── indexer.py
│   │   ├── models.py
│   │   ├── parser.py
│   │   ├── reader.py
│   │   └── watcher.py
│   ├── mcp_server.py   # FastMCP — 15 tools
│   ├── cli.py          # CLI commands (bootstrap, server, stats, etc.)
│   ├── config.py       # Configuration management
│   ├── compat.py       # Version compatibility
│   └── updater.py      # Auto-update
├── tests/              # Test suite (118 tests)
│   ├── test_ai_provider.py
│   ├── test_codebase_analyzer.py
│   ├── test_collections.py
│   ├── test_json_parser.py
│   ├── test_sanitize.py
│   ├── test_sqlite_vec.py
│   ├── test_store.py
│   ├── test_structured_store.py
│   ├── test_updater.py
│   └── test_worker.py
├── docs/               # Documentation
├── README.md
├── LICENSE
├── pyproject.toml
└── scripts/
    ├── install.py
    └── uninstall.py
```

## Running Tests

```bash
# All tests (118 tests)
pytest

# Quick check
pytest -q

# With coverage
pytest --cov=mneme --cov-report=html

# Specific test files
pytest tests/test_codebase_analyzer.py -v
pytest tests/test_collections.py -v
pytest tests/test_sqlite_vec.py -v
pytest tests/test_sanitize.py -v
pytest tests/test_worker.py -v
pytest tests/test_json_parser.py -v
pytest tests/test_ai_provider.py -v
```

## Code Style

```bash
# Format (ruff)
ruff format mneme/ tests/

# Lint (ruff)
ruff check mneme/ tests/
```

> **Note:** We use `ruff` for both formatting and linting. `black` and `mypy` are not required.

## Adding a New Hook

1. Create `hooks/<event_name>.py`:

```python
#!/usr/bin/env python3
"""Hook for <EventName>."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.db.store import ObservationStore


def main():
    input_data = json.load(sys.stdin)
    
    store = ObservationStore()
    store.add_observation({
        "session_id": input_data["session_id"],
        "event_type": input_data["hook_event_name"],
        # ... event-specific fields
    })
    
    sys.exit(0)


if __name__ == "__main__":
    main()
```

2. Register via `mneme bootstrap` or manually in `~/.kimi/config.toml`:

```toml
[[hooks]]
event = "YourEvent"
command = "python /path/to/kimi-mneme/hooks/<event_name>.py"
```

## Adding a New MCP Tool

Edit `mneme/mcp_server.py`:

```python
@mcp.tool()
def my_new_tool(query: str, limit: int = 10) -> str:
    """Description of what this tool does."""
    from mneme.db.store import ObservationStore
    store = ObservationStore()
    results = store.search(query, limit=limit)
    return json.dumps(results, ensure_ascii=False)
```

## Release Process

1. Update version in `pyproject.toml`, `mneme/__init__.py`, `plugin/plugin.json`
2. Sync version in README.md (`<!-- VERSION -->...<!-- /VERSION -->`)
3. Run tests: `pytest` (all 118 tests must pass)
4. Build: `uv build`
5. Tag: `git tag v2.1.0`
6. Push: `git push origin main && git push origin v2.1.0`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite
6. Submit a pull request

## Debugging

```bash
# Enable debug logging
export MNEME_LOG_LEVEL=DEBUG

# Run hook manually with test data
echo '{"session_id": "test", "cwd": "/tmp", "hook_event_name": "SessionStart", "source": "startup"}' | python hooks/session_start.py

# Inspect database
python -c "import sqlite3; conn=sqlite3.connect('~/.kimi/mneme/mneme.db'); [print(r) for r in conn.execute('SELECT * FROM observations LIMIT 10').fetchall()]"
# Or if sqlite3 CLI is installed: sqlite3 ~/.kimi/mneme/mneme.db "SELECT * FROM observations LIMIT 10;"

# Check vector store status
python -c "from mneme.db.vector import SQLiteVecStore; v=SQLiteVecStore(); print(v.get_stats())"
```
