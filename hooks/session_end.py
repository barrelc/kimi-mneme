#!/usr/bin/env python3
"""Hook: SessionEnd — finalize session, trigger compression, stop server."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mneme.config import load_config
from mneme.core.extractor import Extractor


def _is_server_running(host: str, port: int) -> bool:
    """Check if the mneme server is running."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _stop_server() -> None:
    """Stop the mneme web server if running."""
    config = load_config()
    server_cfg = config.get("server", {})
    
    if not server_cfg.get("enabled", True):
        return
    
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 37777)
    
    if not _is_server_running(host, port):
        return  # Already stopped
    
    try:
        # Find and kill the uvicorn/mneme.server process
        if sys.platform == "win32":
            # Kill by port using netstat + taskkill
            result = subprocess.run(
                ["netstat", "-ano", "|", "findstr", f":{port}"],
                capture_output=True,
                text=True,
                shell=True,
            )
            for line in result.stdout.splitlines():
                if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                        break
        else:
            # Unix: kill processes matching mneme.server
            subprocess.run(
                ["pkill", "-f", "mneme.server"],
                capture_output=True,
            )
    except Exception:
        pass  # Fail silently — server might already be stopped


def main() -> None:
    """Handle SessionEnd hook event."""
    try:
        input_data = json.load(sys.stdin)

        extractor = Extractor()
        extractor.handle_session_end(input_data)
        
        # Stop server on session end
        _stop_server()

        sys.exit(0)

    except Exception as e:
        print(f"kimi-mneme hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
