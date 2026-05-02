#!/usr/bin/env python3
"""Uninstaller for kimi-mneme.

Removes hooks, uninstalls plugin, and optionally deletes data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def get_kimi_dir() -> Path:
    return Path.home() / ".kimi"


def get_mneme_dir() -> Path:
    return get_kimi_dir() / "mneme"


def remove_hooks() -> bool:
    """Remove kimi-mneme hooks from Kimi CLI config."""
    print("🔗 Removing hooks...")

    kimi_config = get_kimi_dir() / "config.toml"

    if not kimi_config.exists():
        print("ℹ️  No Kimi config found")
        return True

    try:
        content = kimi_config.read_text(encoding="utf-8")

        if "kimi-mneme hooks" not in content:
            print("ℹ️  No kimi-mneme hooks found")
            return True

        start = content.find("# === kimi-mneme hooks ===")
        end = content.find("# === end kimi-mneme hooks ===") + len("# === end kimi-mneme hooks ===")

        content = content[:start] + content[end:]
        content = content.strip() + "\n"

        with open(kimi_config, "w", encoding="utf-8") as f:
            f.write(content)

        print("✅ Hooks removed")
        return True

    except Exception as e:
        print(f"❌ Failed to remove hooks: {e}")
        return False


def uninstall_plugin() -> bool:
    """Uninstall the Kimi CLI plugin."""
    print("🔌 Uninstalling plugin...")

    try:
        import subprocess

        result = subprocess.run(
            ["kimi", "plugin", "remove", "kimi-mneme"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print("✅ Plugin uninstalled")
            return True
        else:
            print(f"⚠️  {result.stderr or 'Plugin may not be installed'}")
            return True

    except FileNotFoundError:
        print("⚠️  Kimi CLI not found")
        return True
    except Exception as e:
        print(f"❌ Failed to uninstall plugin: {e}")
        return False


def remove_data() -> bool:
    """Remove all mneme data."""
    print("🗑️  Removing data...")

    mneme_dir = get_mneme_dir()

    if not mneme_dir.exists():
        print("ℹ️  No data directory found")
        return True

    try:
        import shutil

        shutil.rmtree(mneme_dir)
        print(f"✅ Data removed: {mneme_dir}")
        return True

    except Exception as e:
        print(f"❌ Failed to remove data: {e}")
        return False


def main() -> int:
    """Run the uninstaller."""
    parser = argparse.ArgumentParser(description="Uninstall kimi-mneme")
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep database and configuration files",
    )
    args = parser.parse_args()

    print("🧠 Uninstalling kimi-mneme...")
    print()

    remove_hooks()
    uninstall_plugin()

    if not args.keep_data:
        remove_data()
    else:
        print("ℹ️  Data kept (use --keep-data to remove)")

    print("\n✅ Uninstall complete. Restart Kimi CLI for changes to take effect.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
