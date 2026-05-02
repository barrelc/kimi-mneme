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
│   └── user_prompt_submit.py
├── plugin/             # Kimi CLI plugin
│   ├── plugin.json
│   └── tools/
│       ├── search.py
│       ├── timeline.py
│       └── get.py
├── server/             # Web UI + API
│   ├── app.py
│   ├── routes.py
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── db/                 # Database layer
│   ├── __init__.py
│   ├── schema.py
│   ├── store.py
│   └── migrations/
├── core/               # Business logic
│   ├── __init__.py
│   ├── extractor.py
│   ├── compressor.py
│   ├── injector.py
│   └── sanitize.py
├── config/             # Configuration
│   └── default.json
├── scripts/            # Install/uninstall
│   ├── install.py
│   └── uninstall.py
├── tests/              # Test suite
│   ├── test_hooks.py
│   ├── test_store.py
│   ├── test_search.py
│   └── test_compressor.py
├── docs/               # Documentation
├── README.md
├── LICENSE
├── pyproject.toml
└── requirements.txt
```

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=mneme --cov-report=html

# Specific test
pytest tests/test_store.py -v

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
2. Update `CHANGELOG.md`
3. Run tests: `pytest`
4. Build: `python -m build`
5. Tag: `git tag v1.0.0`
6. Push: `git push origin v1.0.0`

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
