"""Kimi CLI lifecycle hooks for kimi-mneme.

These hooks are called by Kimi CLI at various points in the session lifecycle.
Each hook reads JSON from stdin and exits with code 0 (fail-open design).

Usage as Kimi CLI hooks (configured in ~/.kimi/config.yaml):
    hooks:
      session_start: ["python", "-m", "hooks.session_start"]
      session_end: ["python", "-m", "hooks.session_end"]
      post_tool_use: ["python", "-m", "hooks.post_tool_use"]
      post_tool_use_failure: ["python", "-m", "hooks.post_tool_use_failure"]
      pre_compact: ["python", "-m", "hooks.pre_compact"]
      post_compact: ["python", "-m", "hooks.post_compact"]
      user_prompt_submit: ["python", "-m", "hooks.user_prompt_submit"]
"""

from __future__ import annotations

import types

# NOTE: Hook modules call fix_windows_encoding() at import time which
# mutates sys.stdin. We avoid importing them at package level to prevent
# side effects when the package is imported as a library. Use the CLI
# entry points directly or import inside functions.

__all__ = []


def _lazy_import(name: str) -> types.ModuleType:
    """Lazy import to avoid side effects at package import time."""
    import importlib

    return importlib.import_module(f"hooks.{name}")


def session_start() -> None:
    """Run session_start hook."""
    mod = _lazy_import("session_start")
    mod.main()


def session_end() -> None:
    """Run session_end hook."""
    mod = _lazy_import("session_end")
    mod.main()


def post_tool_use() -> None:
    """Run post_tool_use hook."""
    mod = _lazy_import("post_tool_use")
    mod.main()


def post_tool_use_failure() -> None:
    """Run post_tool_use_failure hook."""
    mod = _lazy_import("post_tool_use_failure")
    mod.main()


def pre_compact() -> None:
    """Run pre_compact hook."""
    mod = _lazy_import("pre_compact")
    mod.main()


def post_compact() -> None:
    """Run post_compact hook."""
    mod = _lazy_import("post_compact")
    mod.main()


def user_prompt_submit() -> None:
    """Run user_prompt_submit hook."""
    mod = _lazy_import("user_prompt_submit")
    mod.main()
