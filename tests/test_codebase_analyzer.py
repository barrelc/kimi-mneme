"""Tests for tree-sitter codebase analyzer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mneme.core.codebase_analyzer import (
    CodebaseAnalyzer,
    _detect_language,
    get_analyzer,
)


class TestDetectLanguage:
    def test_python(self):
        assert _detect_language("test.py") == "python"

    def test_javascript(self):
        assert _detect_language("test.js") == "javascript"

    def test_typescript(self):
        assert _detect_language("test.ts") == "typescript"
        assert _detect_language("test.tsx") == "typescript"

    def test_rust(self):
        assert _detect_language("test.rs") == "rust"

    def test_go(self):
        assert _detect_language("test.go") == "go"

    def test_unknown(self):
        assert _detect_language("test.txt") is None


class TestCodebaseAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return CodebaseAnalyzer()

    @pytest.fixture
    def temp_py_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('''
def authenticate(username: str, password: str) -> bool:
    """Check user credentials."""
    return verify(password)

class AuthMiddleware:
    """Middleware for auth."""
    def process(self, request):
        pass

_private = 1
''')
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)

    def test_scan_file_python(self, analyzer, temp_py_file):
        symbols = analyzer.scan_file(temp_py_file)
        names = {s.name for s in symbols}
        assert "authenticate" in names
        assert "AuthMiddleware" in names
        assert "process" in names

    def test_symbol_details(self, analyzer, temp_py_file):
        symbols = analyzer.scan_file(temp_py_file)
        auth = next(s for s in symbols if s.name == "authenticate")
        assert auth.kind == "function"
        assert "username: str" in auth.signature
        assert "-> bool" in auth.signature
        assert auth.docstring == "Check user credentials."
        assert auth.line_start > 0

    def test_get_outline(self, analyzer, temp_py_file):
        outline = analyzer.get_outline(temp_py_file)
        assert outline["language"] == "python"
        assert outline["symbol_count"] >= 3
        names = {s["name"] for s in outline["symbols"]}
        assert "authenticate" in names

    def test_get_symbol_body(self, analyzer, temp_py_file):
        symbol = analyzer.get_symbol_body(temp_py_file, "authenticate")
        assert symbol is not None
        assert symbol.name == "authenticate"
        assert "def authenticate" in (symbol.body or "")

    def test_search_symbols(self, analyzer, temp_py_file):
        results = analyzer.search_symbols("auth", temp_py_file)
        names = {r.name for r in results}
        assert "authenticate" in names or "AuthMiddleware" in names

    def test_search_no_match(self, analyzer, temp_py_file):
        results = analyzer.search_symbols("xyz_nonexistent", temp_py_file)
        assert len(results) == 0

    def test_scan_project(self, analyzer):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.py").write_text("def hello(): pass\n")
            Path(tmpdir, "test.js").write_text("function hello() {}\n")
            symbols = analyzer.scan_project(tmpdir, max_files=10)
            assert len(symbols) >= 1

    def test_regex_fallback(self, analyzer):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def fallback_test():\n    pass\n")
            path = f.name

        # Force regex by using unknown language
        symbols = analyzer._regex_scan(
            Path(path).read_text(), path, "python"
        )
        names = {s.name for s in symbols}
        assert "fallback_test" in names
        Path(path).unlink(missing_ok=True)

    def test_get_analyzer_singleton(self):
        a1 = get_analyzer()
        a2 = get_analyzer()
        assert isinstance(a1, CodebaseAnalyzer)
        assert isinstance(a2, CodebaseAnalyzer)
