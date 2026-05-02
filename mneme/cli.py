"""CLI entry point for kimi-mneme."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click


def get_project_root() -> Path:
    """Get the project root directory (where mneme package lives).

    When installed via uvx/pip, plugin files are in the package directory.
    When running from source, they're in the repo root.
    """
    # Package directory (where mneme/ is installed)
    package_dir = Path(__file__).parent.parent.resolve()

    # Check if plugin directory exists alongside the package (source install)
    source_plugin = package_dir / "plugin"
    if source_plugin.exists():
        return package_dir

    # When installed via uvx/pip, plugin files are inside the package
    # Look for plugin in the installed package
    installed_plugin = Path(__file__).parent / "plugin"
    if installed_plugin.exists():
        return Path(__file__).parent

    # Fallback: return package dir and let caller handle missing plugin
    return package_dir


def get_kimi_dir() -> Path:
    """Get the Kimi CLI configuration directory."""
    return Path.home() / ".kimi"


def get_mneme_dir() -> Path:
    """Get the mneme data directory."""
    return get_kimi_dir() / "mneme"


@click.group()
@click.version_option(version="1.1.0", prog_name="mneme")
def main() -> None:
    """kimi-mneme — Persistent memory for Kimi Code CLI."""
    pass


@main.command()
@click.option("--port", default=37777, help="Server port")
@click.option("--host", default="127.0.0.1", help="Server host")
def server(port: int, host: str) -> None:
    """Start the web server."""
    import uvicorn

    from mneme.server.app import create_app

    app = create_app()
    uvicorn.run(app, host=host, port=port)


@main.command()
def update() -> None:
    """Update hooks and config to latest version."""
    click.echo(" Updating kimi-mneme...")
    
    # Re-run bootstrap steps
    steps = [
        ("Database", _init_database),
        ("Configuration", _create_default_config),
        ("Hooks", _register_hooks),
        ("Plugin", _install_plugin),
    ]
    
    all_ok = True
    for name, step in steps:
        click.echo(f"\n Step: {name}")
        click.echo("-" * 30)
        if not step():
            all_ok = False
    
    click.echo("\n Update complete!")
    click.echo("Please restart Kimi CLI for changes to take effect.")


@main.command()
def init() -> None:
    """Initialize the database."""
    from mneme.config import load_config
    from mneme.db.schema import init_db

    config = load_config()
    init_db(config["db"]["path"])
    click.echo(" Database initialized")


@main.command()
@click.option("--days", default=30, help="Delete observations older than N days")
def cleanup(days: int) -> None:
    """Clean up old observations."""
    import sqlite3

    from mneme.config import load_config

    config = load_config()
    db_path = config["db"]["path"]

    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "DELETE FROM observations WHERE created_at < datetime('now', '-' || ? || ' days')",
        (days,),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    click.echo(f"  Deleted {deleted} observations older than {days} days")


@main.command()
def stats() -> None:
    """Show database statistics."""
    from mneme.db.store import ObservationStore

    store = ObservationStore()
    data = store.get_stats()

    click.echo(" kimi-mneme Statistics")
    click.echo("-" * 30)
    click.echo(f"Sessions:      {data['total_sessions']}")
    click.echo(f"Observations:  {data['total_observations']}")
    click.echo(f"Summaries:     {data['total_summaries']}")
    click.echo(f"DB Size:       {data['db_size_mb']} MB")

    if data.get("top_projects"):
        click.echo("\nTop Projects:")
        for p in data["top_projects"]:
            click.echo(f"  {p['project']}: {p['count']} sessions")


# ---------------------------------------------------------------------------
# Bootstrap command — one-shot setup
# ---------------------------------------------------------------------------


def _init_database() -> bool:
    """Initialize the SQLite database."""
    click.echo("  Initializing database...")
    mneme_dir = get_mneme_dir()
    mneme_dir.mkdir(parents=True, exist_ok=True)
    db_path = mneme_dir / "mneme.db"

    try:
        from mneme.db.schema import init_db

        init_db(str(db_path))
        click.echo(f" Database initialized at {db_path}")
        return True
    except Exception as e:
        click.echo(f" Failed to initialize database: {e}")
        return False


def _create_default_config() -> bool:
    """Create default configuration file."""
    click.echo("  Creating default configuration...")
    config_dir = get_mneme_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    if config_path.exists():
        click.echo("  Config already exists, skipping")
        return True

    default_config = {
        "db": {"path": str(config_dir / "mneme.db")},
        "vector": {"path": str(config_dir / "chroma")},
        "compression": {
            "enabled": True,
            "api_key": "${MOONSHOT_API_KEY}",
        },
        "server": {"port": 37777},
    }

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        click.echo(f" Config created at {config_path}")
        return True
    except Exception as e:
        click.echo(f" Failed to create config: {e}")
        return False


def _register_hooks() -> bool:
    """Register hooks in Kimi CLI config.

    Hooks are copied to ~/.kimi/mneme/hooks/ so they survive uvx cache
    purges and remain at a stable path.
    """
    click.echo("Registering hooks...")

    kimi_config = get_kimi_dir() / "config.toml"
    project_root = get_project_root()
    source_hooks_dir = project_root / "hooks"

    # Copy hooks to a stable location inside ~/.kimi/mneme/hooks
    stable_hooks_dir = get_mneme_dir() / "hooks"
    stable_hooks_dir.mkdir(parents=True, exist_ok=True)

    hooks = [
        ("SessionStart", "session_start.py"),
        ("SessionEnd", "session_end.py"),
        ("PostToolUse", "post_tool_use.py"),
        ("PostToolUseFailure", "post_tool_use_failure.py"),
        ("UserPromptSubmit", "user_prompt_submit.py"),
    ]

    for _, script in hooks:
        src = source_hooks_dir / script
        dst = stable_hooks_dir / script
        if src.exists():
            shutil.copy2(src, dst)

    python_exe = sys.executable
    hook_entries = []
    for event, script in hooks:
        script_path = stable_hooks_dir / script
        # Use forward slashes in paths to avoid TOML escape issues on Windows
        cmd = f"{python_exe} {script_path}".replace("\\", "/")
        hook_entries.append(f'[[hooks]]\nevent = "{event}"\ncommand = "{cmd}"\n')

    hook_block = (
        "\n# === kimi-mneme hooks ===\n"
        + "\n".join(hook_entries)
        + "# === end kimi-mneme hooks ===\n"
    )

    try:
        if kimi_config.exists():
            content = kimi_config.read_text(encoding="utf-8")

            # Backup original config
            backup_path = get_kimi_dir() / "config.toml.backup"
            shutil.copy2(kimi_config, backup_path)

            # Remove existing kimi-mneme hook block
            if "kimi-mneme hooks" in content:
                click.echo("Hooks already registered, updating...")
                start = content.find("# === kimi-mneme hooks ===")
                end = content.find("# === end kimi-mneme hooks ===") + len(
                    "# === end kimi-mneme hooks ==="
                )
                content = content[:start] + content[end:]

            # Remove bare `hooks = []` which conflicts with [[hooks]] tables
            import re

            content = re.sub(r"\n?hooks\s*=\s*\[\]\s*\n?", "\n", content)

            content = content.rstrip() + "\n" + hook_block
        else:
            content = hook_block

        # NOTE: Do NOT use utf-8-sig (BOM) — tomlkit in Kimi CLI chokes on \ufeff
        with open(kimi_config, "w", encoding="utf-8") as f:
            f.write(content)

        click.echo(f"Hooks registered in {kimi_config}")
        return True

    except Exception as e:
        click.echo(f"Failed to register hooks: {e}")
        return False


def _install_plugin() -> bool:
    """Install the Kimi CLI plugin."""
    click.echo(" Installing plugin...")

    plugin_dir = get_project_root() / "plugin"

    if not plugin_dir.exists():
        click.echo(" Plugin directory not found")
        return False

    # Generate plugin.json with correct python executable
    _generate_plugin_json(plugin_dir)

    try:
        result = subprocess.run(
            ["kimi", "plugin", "install", str(plugin_dir)],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            click.echo(" Plugin installed")
            return True
        else:
            click.echo(f"  Plugin install output: {result.stdout or result.stderr}")
            # Don't fail — plugin might already be installed
            return True

    except FileNotFoundError:
        click.echo("  Kimi CLI not found in PATH. Please install plugin manually:")
        click.echo(f"   kimi plugin install {plugin_dir}")
        return True
    except Exception as e:
        click.echo(f" Failed to install plugin: {e}")
        return False


def _generate_plugin_json(plugin_dir: Path) -> None:
    """Generate plugin.json with the correct Python executable."""
    python_exe = sys.executable
    plugin_json = {
        "name": "kimi-mneme",
        "version": "1.1.0",
        "description": "Persistent memory plugin for Kimi Code CLI — search and retrieve past session context",
        "tools": [
            {
                "name": "mneme_search",
                "description": "Search memory index with full-text queries. Returns compact index with IDs, timestamps, types, and snippets. Use this as the first step in progressive disclosure.",
                "command": [python_exe, str(plugin_dir / "tools" / "search.py")],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query — natural language or keywords",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["bugfix", "feature", "refactor", "docs", "test"],
                            "description": "Filter by observation type",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "description": "Maximum results (default: 10, max: 50)",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "ISO date filter (inclusive), e.g. 2026-04-01",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "ISO date filter (inclusive), e.g. 2026-05-01",
                        },
                        "project": {
                            "type": "string",
                            "description": "Filter by project/directory name",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "mneme_timeline",
                "description": "Get chronological context around a specific observation. Shows what happened before and after. Use after mneme_search to understand context.",
                "command": [python_exe, str(plugin_dir / "tools" / "timeline.py")],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "observation_id": {
                            "type": "integer",
                            "description": "Center observation ID from search results",
                        },
                        "radius": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of observations before/after (default: 5, max: 20)",
                        },
                    },
                    "required": ["observation_id"],
                },
            },
            {
                "name": "mneme_get",
                "description": "Fetch full observation details by IDs. Always batch multiple IDs in one call. Use as the final step after identifying relevant observations.",
                "command": [python_exe, str(plugin_dir / "tools" / "get.py")],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Array of observation IDs to fetch",
                        },
                    },
                    "required": ["ids"],
                },
            },
        ],
    }

    with open(plugin_dir / "plugin.json", "w", encoding="utf-8") as f:
        json.dump(plugin_json, f, indent=2)


def _start_server() -> bool:
    """Start the web server."""
    from mneme.config import load_config

    config = load_config()
    server_cfg = config.get("server", {})

    if not server_cfg.get("auto_start", True):
        click.echo(" Auto-start disabled in config")
        return True

    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 37777)

    # Check if already running
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            click.echo(f" Server already running at http://{host}:{port}")
            return True
    except OSError:
        pass  # Not running, start it

    click.echo(" Starting web server...")

    try:
        if sys.platform == "win32":
            # Use CREATE_NO_WINDOW instead of CREATE_NEW_CONSOLE to avoid popup
            subprocess.Popen(
                [sys.executable, "-m", "mneme.server"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [sys.executable, "-m", "mneme.server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        click.echo(f" Web server started at http://{host}:{port}")
        return True

    except Exception as e:
        click.echo(f"  Failed to start server: {e}")
        click.echo("   Start manually: python -m mneme.server")
        return True


@main.command()
@click.option("--no-server", is_flag=True, help="Don't start web server")
@click.option("--no-plugin", is_flag=True, help="Don't install plugin")
def bootstrap(no_server: bool, no_plugin: bool) -> None:
    """One-shot setup for kimi-mneme.

    Registers hooks, installs plugin, initializes database, and starts web server.
    Safe to run multiple times — idempotent.
    """
    click.echo(" Bootstrapping kimi-mneme...")
    click.echo(f" Version: 1.1.0")
    click.echo(f" Python: {sys.executable}")
    click.echo()

    steps = [
        ("Database", _init_database),
        ("Configuration", _create_default_config),
        ("Hooks", _register_hooks),
    ]

    if not no_plugin:
        steps.append(("Plugin", _install_plugin))

    if not no_server:
        steps.append(("Server", _start_server))

    all_ok = True
    for name, step in steps:
        click.echo(f"\n Step: {name}")
        click.echo("-" * 30)
        if not step():
            all_ok = False
            click.echo(f"  Step '{name}' had issues, continuing...")

    click.echo("\n" + "=" * 50)
    click.echo(" kimi-mneme bootstrapped successfully!")
    click.echo("=" * 50)
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Restart Kimi CLI: kimi")
    click.echo("  2. Visit web UI: http://localhost:37777")
    click.echo("  3. Set your API key for AI compression:")
    click.echo("     export MOONSHOT_API_KEY=your-key")
    click.echo()
    click.echo("Commands:")
    click.echo("  mneme stats      Show database statistics")
    click.echo("  mneme server     Start web server")
    click.echo("  mneme cleanup    Clean old observations")
    click.echo()
    click.echo("Files:")
    click.echo(f"  Config:  {get_mneme_dir() / 'config.json'}")
    click.echo(f"  DB:      {get_mneme_dir() / 'mneme.db'}")
    click.echo(f"  Logs:    {get_mneme_dir() / 'mneme.log'}")
    click.echo()

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
