#!/usr/bin/env python3
"""Hook: SessionStart — initialize session, inject context, auto-start server."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import traceback
from pathlib import Path

# Ensure mneme package is importable — it may be installed via uv tool
# or available in the Python environment that runs this hook
try:
    from mneme.config import load_config
    from mneme.core.extractor import Extractor
except ImportError:
    # Fallback: try to find mneme in common uv tool locations
    import site
    uv_tool_paths = [
        Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "kimi-mneme" / "Lib" / "site-packages",
        Path.home() / ".local" / "share" / "uv" / "tools" / "kimi-mneme" / "lib" / "python3.10" / "site-packages",
    ]
    for p in uv_tool_paths:
        if p.exists():
            sys.path.insert(0, str(p))
            break
    from mneme.config import load_config
    from mneme.core.extractor import Extractor


def _is_server_running(host: str, port: int) -> bool:
    """Check if the mneme server is already running."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _start_server() -> None:
    """Start the mneme web server in background if not running."""
    # Log to file for debugging
    log_path = Path.home() / ".kimi" / "mneme" / "session_start.log"
    
    try:
        config = load_config()
        server_cfg = config.get("server", {})
        
        if not server_cfg.get("enabled", True):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("Server disabled in config\n")
            return
        
        if not server_cfg.get("auto_start", True):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("Auto-start disabled in config\n")
            return
        
        host = server_cfg.get("host", "127.0.0.1")
        port = server_cfg.get("port", 37777)
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Checking server at {host}:{port}...\n")
        
        if _is_server_running(host, port):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("Server already running\n")
            return  # Already running
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("Starting server...\n")
        
        # Use the same Python executable that runs this hook
        python_exe = sys.executable
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Python: {python_exe}\n")
        
        if sys.platform == "win32":
            # CREATE_NO_WINDOW = 0x08000000 — no console popup
            subprocess.Popen(
                [python_exe, "-c", "from mneme.server.app import main; main()"],
                creationflags=0x08000000,
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
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("Server started successfully\n")
            
    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"ERROR starting server: {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")


def main() -> None:
    """Handle SessionStart hook event."""
    try:
        # Auto-start server if configured
        _start_server()
        
        # Force UTF-8 encoding for stdin on Windows
        if sys.platform == "win32":
            import io
            sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
        
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
