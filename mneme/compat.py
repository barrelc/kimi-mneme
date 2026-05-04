"""Cross-platform compatibility helpers."""

from __future__ import annotations

import io
import sys


def fix_windows_encoding() -> None:
    """Force UTF-8 for stdin/stdout/stderr on Windows.

    On Windows the default console encoding (cp1252/cp866) cannot handle
    Unicode characters emitted by our JSON output. This must be called
    before any read from stdin or write to stdout/stderr.
    """
    if sys.platform != "win32":
        return
    if hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
