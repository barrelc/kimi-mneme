#!/usr/bin/env python3
"""Hook: SessionStart — initialize session, inject context, auto-start server."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    
    try:
        # Use the same Python executable that runs this hook
        python_exe = sys.executable
        if sys.platform == "win32":
            # CREATE_NO_WINDOW = 0x08000000 — no console popup
            subprocess.Popen(
                [python_exe, "-m", "mneme.server"],
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
    except Exception:
        pass  # Fail silently — server is optional


def main() -> None:
    """Handle SessionStart hook event."""
    try:
        # Auto-start server if configured
        _start_server()
        
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
