"""Plugin tools for kimi-mneme.

These are standalone CLI scripts that read JSON from stdin and write JSON to stdout.
They are invoked by the plugin system via `mneme <command>`.

Commands:
    mneme search   → plugin.tools.search
    mneme timeline → plugin.tools.timeline
    mneme get      → plugin.tools.get
"""

from __future__ import annotations

import types

# NOTE: These modules call fix_windows_encoding() at import time which
# mutates sys.stdin. We avoid importing them at package level to prevent
# side effects when the package is imported as a library. Use the CLI
# entry points directly or import inside functions.

__all__ = []


def _lazy_import(name: str) -> types.ModuleType:
    """Lazy import to avoid side effects at package import time."""
    import importlib

    return importlib.import_module(f"plugin.tools.{name}")


def get() -> None:
    """CLI entry point for mneme_get."""
    mod = _lazy_import("get")
    mod.main()


def search() -> None:
    """CLI entry point for mneme_search."""
    mod = _lazy_import("search")
    mod.main()


def timeline() -> None:
    """CLI entry point for mneme_timeline."""
    mod = _lazy_import("timeline")
    mod.main()
