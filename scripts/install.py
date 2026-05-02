#!/usr/bin/env python3
"""Installer for kimi-mneme.

Deprecated: use `mneme bootstrap` instead.
This script delegates to the bootstrap command for backward compatibility.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run the installer by delegating to `mneme bootstrap`."""
    parser = argparse.ArgumentParser(description="Install kimi-mneme")
    parser.add_argument("--no-server", action="store_true", help="Don't start web server")
    parser.add_argument("--no-plugin", action="store_true", help="Don't install plugin")
    args = parser.parse_args()

    print("🧠 Installing kimi-mneme...")
    print()
    print("ℹ️  This installer delegates to `mneme bootstrap`.")
    print("   You can also run: mneme bootstrap")
    print()

    # Build bootstrap command
    cmd = [sys.executable, "-m", "mneme.cli", "bootstrap"]
    if args.no_server:
        cmd.append("--no-server")
    if args.no_plugin:
        cmd.append("--no-plugin")

    # Ensure mneme is importable
    project_root = Path(__file__).parent.parent.resolve()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root)

    try:
        result = subprocess.run(cmd, env=env)
        return result.returncode
    except Exception as e:
        print(f"❌ Failed to run bootstrap: {e}")
        print(f"   Try running manually: python -m mneme.cli bootstrap")
        return 1


if __name__ == "__main__":
    sys.exit(main())
