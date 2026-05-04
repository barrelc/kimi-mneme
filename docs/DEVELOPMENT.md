# Development Guide

## Setup

```bash
git clone https://github.com/yourusername/kimi-mneme.git
cd kimi-mneme

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements-dev.txt

# Install in editable mode
pip install -e .
```

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
│   └── tools/
│       ├── search.py
│       ├── timeline.py
│       └── get.py
├── mneme/              # Main package
│   ├── core/           # Business logic
│   │   ├── codebase_analyzer.py    # Tree-sitter AST analysis
│   │   ├── project_md.py           # AGENTS.md + PROJECT.md generation
│   │   └── prompts/                # AI prompts & JSON parser
│   ├── db/             # Database layer
│   │   ├── schema.py               # 18 migrations
│   │   ├── store.py                # Raw observations
│   │   ├── structured_store.py     # Structured observations + FTS5
│   │   ├── vector.py               # sqlite-vec + ChromaDB
│   │   ├── collections_store.py    # Knowledge Collections
│   │   └── wire_store.py           # Wire events
│   ├── server/         # Web UI + API
│   │   ├── app.py
│   │   ├── routes.py               # 30+ endpoints
│   │   └── static/
│   │       ├── index.html          # Welcome modal, log drawer
│   │       ├── style.css           # Glassmorphism, skeletons
│   │       └── app.js              # SSE, WebSocket, filters
│   ├── mcp_server.py   # FastMCP — 15 tools
│   ├── cli.py          # CLI commands
│   └── config.py       # Configuration
├── server/             # Legacy server entry (re-exports)
├── tests/              # Test suite (111 tests)
│   ├── test_codebase_analyzer.py   # 15 tests
│   ├── test_collections.py         # 9 tests
│   ├── test_sanitize.py            # Privacy v2
│   ├── test_sqlite_vec.py          # Vector search
│   ├── test_store.py
│   ├── test_structured_store.py    # Dedup v2
│   ├── test_worker.py
│   ├── test_json_parser.py
│   └── test_ai_provider.py
├── docs/               # Documentation
├── README.md
├── LICENSE
├── pyproject.toml
└── requirements.txt
```

## Running Tests

```bash
# All tests (111 tests)
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

# Integration tests (require Kimi CLI)
pytest tests/integration/ -v
```

## Code Style

```bash
# Format
black mneme/ tests/

# Lint
ruff check mneme/ tests/

# Type check
mypy mneme/
```

## Adding a New Hook

1. Create `hooks/<event_name>.py`:

```python
#!/usr/bin/env python3
"""Hook for <EventName>."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.core.store import ObservationStore


def main():
    input_data = json.load(sys.stdin)
    
    store = ObservationStore()
    store.add({
        "session_id": input_data["session_id"],
        "event_type": input_data["hook_event_name"],
        # ... event-specific fields
    })
    
    sys.exit(0)


if __name__ == "__main__":
    main()
```

2. Register in `~/.kimi/config.toml`:

```toml
[[hooks]]
event = "YourEvent"
command = "python3 /path/to/kimi-mneme/hooks/<event_name>.py"
```

## Adding a New Plugin Tool

1. Create `plugin/tools/<tool_name>.py`:

```python
#!/usr/bin/env python3
"""Tool: <tool_name>."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mneme.core.store import ObservationStore


def main():
    params = json.load(sys.stdin)
    
    store = ObservationStore()
    result = store.some_query(params)
    
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

2. Register in `plugin/plugin.json`:

```json
{
  "tools": [
    {
      "name": "mneme_<tool_name>",
      "description": "What this tool does",
      "command": ["python3", "tools/<tool_name>.py"],
      "parameters": {
        "type": "object",
        "properties": {
          "param1": { "type": "string" }
        },
        "required": ["param1"]
      }
    }
  ]
}
```

## Database Migrations

```bash
# Create migration
python -m mneme.db.migrate create "add_user_column"

# Apply migrations
python -m mneme.db.migrate upgrade

# Rollback
python -m mneme.db.migrate downgrade
```

## Release Process

1. Update version in `pyproject.toml`
2. Update `docs/IMPLEMENTATION_PLAN.md` with new metrics
3. Update all docs (README, ARCHITECTURE, TOOLS, WEB_UI, DEVELOPMENT)
4. Run tests: `pytest` (111 tests must pass)
5. Build: `python -m build`
6. Tag: `git tag v2.1.0`
7. Push: `git push origin v2.1.0`

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
sqlite3 ~/.kimi/mneme/mneme.db "SELECT * FROM observations LIMIT 10;"

# Check vector store
python -m mneme.db.vector_stats
```
