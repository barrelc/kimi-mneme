"""Auto-update functionality for kimi-mneme.

Checks PyPI for newer versions and supports self-upgrade.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from mneme import __version__

PYPI_URL = "https://pypi.org/pypi/kimi-mneme/json"
CACHE_FILE = Path.home() / ".kimi" / "mneme" / ".version_cache"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _get_cache() -> dict:
    """Read cached version check."""
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _set_cache(data: dict) -> None:
    """Write version check cache."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def fetch_latest_version() -> str | None:
    """Fetch latest version from PyPI."""
    try:
        req = Request(PYPI_URL, headers={"User-Agent": f"kimi-mneme/{__version__}"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["info"]["version"]
    except Exception:
        return None


def get_latest_version(*, use_cache: bool = True) -> str | None:
    """Get latest version with caching."""
    if use_cache:
        cache = _get_cache()
        if cache.get("version") and time.time() - cache.get("checked", 0) < CACHE_TTL_SECONDS:
            return cache["version"]

    latest = fetch_latest_version()
    if latest:
        _set_cache({"version": latest, "checked": time.time()})
    return latest


def is_update_available() -> tuple[bool, str | None]:
    """Check if a newer version is available.

    Returns (update_available, latest_version).
    """
    latest = get_latest_version()
    if not latest:
        return False, None

    # Simple string comparison works for semver-like versions
    # For more robust comparison we'd use packaging.version
    return _version_greater(latest, __version__), latest


def _version_greater(v1: str, v2: str) -> bool:
    """Compare two version strings."""

    def _normalize(v: str) -> list:
        parts = []
        for part in v.split("."):
            # Split numeric and non-numeric
            num = ""
            rest = ""
            for ch in part:
                if ch.isdigit():
                    num += ch
                else:
                    rest += ch
            parts.append((int(num) if num else 0, rest))
        return parts

    return _normalize(v1) > _normalize(v2)


def upgrade_package() -> bool:
    """Upgrade kimi-mneme via pip.

    Returns True on success.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "kimi-mneme"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def print_update_notice(latest: str) -> None:
    """Print a friendly update notice."""
    print(f"""
+-----------------------------------------+
|  New version available: {latest:<8}          |
|  Current: {__version__:>8}                       |
|                                         |
|  Run: mneme update --upgrade            |
|     or: pip install --upgrade kimi-mneme|
+-----------------------------------------+
""")
