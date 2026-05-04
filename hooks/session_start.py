#!/usr/bin/env python3
"""Hook: SessionStart — initialize session, inject context, auto-start server."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

# Ensure mneme package is importable — it may be installed via uv tool
# or available in the Python environment that runs this hook
try:
    from mneme.config import load_config
    from mneme.core.extractor import Extractor
except ImportError:
    # Fallback: try to find mneme in common uv tool locations
    uv_tool_paths = [
        Path.home()
        / "AppData"
        / "Roaming"
        / "uv"
        / "tools"
        / "kimi-mneme"
        / "Lib"
        / "site-packages",
        Path.home()
        / ".local"
        / "share"
        / "uv"
        / "tools"
        / "kimi-mneme"
        / "lib"
        / "python3.10"
        / "site-packages",
    ]
    for p in uv_tool_paths:
        if p.exists():
            sys.path.insert(0, str(p))
            break
    from mneme.config import load_config
    from mneme.core.extractor import Extractor

from mneme.wire.watcher import get_global_watcher


def _is_server_running(host: str, port: int) -> bool:
    """Check if the mneme server is already running."""
    try:
        # Short timeout to avoid blocking Kimi CLI startup
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except OSError:
        return False


def _start_server() -> None:
    """Start the mneme web server in background if not running."""
    try:
        config = load_config()
        server_cfg = config.get("server", {})

        if not server_cfg.get("enabled", True):
            return

        if not server_cfg.get("auto_start", True):
            return

        host = server_cfg.get("host", "127.0.0.1")
        port = server_cfg.get("port", 37777)

        if _is_server_running(host, port):
            return  # Already running

        python_exe = sys.executable

        if sys.platform == "win32":
            # CREATE_NO_WINDOW — no console popup
            subprocess.Popen(
                [python_exe, "-c", "from mneme.server.app import main; main()"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [python_exe, "-m", "mneme.server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    except Exception:
        pass  # Fail silently — don't block Kimi CLI startup


def main() -> None:
    """Handle SessionStart hook event."""
    try:
        # Auto-start server if configured
        _start_server()

        # Start wire watcher to index session traces from ~/.kimi/sessions/
        try:
            watcher = get_global_watcher()
            watcher.start()
        except Exception:
            pass  # Fail silently — don't block Kimi CLI

        # Force UTF-8 encoding on Windows
        from mneme.compat import fix_windows_encoding

        fix_windows_encoding()

        input_data = json.load(sys.stdin)

        extractor = Extractor()
        result = extractor.handle_session_start(input_data)

        if result:
            print(result)

        sys.exit(0)

    except Exception as e:
        # Fail-open: log error but don't block session
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
