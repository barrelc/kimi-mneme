"""AST-based codebase analysis using tree-sitter.

Provides smart_search, smart_outline, smart_unfold functionality
similar to tree-sitter integration in other memory systems.

Graceful degradation: if tree-sitter grammar is not installed,
falls back to regex-based search.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

# Tree-sitter imports (optional)
try:
    from tree_sitter import Language, Parser

    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False

# Language imports (each is optional)
_LANGUAGE_MODULES: dict[str, Any] = {}

for _lang, _module_name in [
    ("python", "tree_sitter_python"),
    ("javascript", "tree_sitter_javascript"),
    ("typescript", "tree_sitter_typescript"),
    ("rust", "tree_sitter_rust"),
    ("go", "tree_sitter_go"),
]:
    with contextlib.suppress(ImportError):
        _LANGUAGE_MODULES[_lang] = __import__(_module_name)


@dataclass
class Symbol:
    """A code symbol extracted via AST."""

    name: str
    kind: str  # "function", "class", "method", "interface", "struct", etc.
    signature: str
    docstring: str | None
    file_path: str
    line_start: int
    line_end: int
    body: str | None = None


# File extension → language mapping
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
}

# AST node types that define symbols per language
_SYMBOL_NODE_TYPES: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "function": "function",
        "class_declaration": "class",
        "class": "class",
        "method_definition": "method",
    },
    "typescript": {
        "function_declaration": "function",
        "function": "function",
        "class_declaration": "class",
        "class": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "impl_item": "impl",
        "trait_item": "trait",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
}


def _detect_language(file_path: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(ext)


def _get_parser(language: str) -> Parser | None:
    """Get a tree-sitter parser for the given language."""
    if not _TS_AVAILABLE:
        return None
    mod = _LANGUAGE_MODULES.get(language)
    if not mod:
        return None
    try:
        lang = Language(mod.language())
        return Parser(lang)
    except Exception as e:
        logger.debug(f"Failed to create parser for {language}: {e}")
        return None


def _extract_docstring(body_node: Any, source_bytes: bytes) -> str | None:
    """Extract docstring from function/class body (Python-style)."""
    if not body_node or not body_node.children:
        return None
    first = body_node.children[0]
    if first.type == "expression_statement":
        inner = first.children[0] if first.children else None
        if inner and inner.type in ("string", "string_literal"):
            text = source_bytes[inner.start_byte : inner.end_byte].decode("utf-8", errors="replace")
            return text.strip("'\"\n ")
    return None


def _extract_signature(node: Any, source_bytes: bytes) -> str:
    """Extract a human-readable signature from a symbol node."""
    name_node = node.child_by_field_name("name")
    name = name_node.text.decode("utf-8", errors="replace") if name_node else "unknown"

    params_node = node.child_by_field_name("parameters")
    params = ""
    if params_node:
        params = source_bytes[params_node.start_byte : params_node.end_byte].decode(
            "utf-8", errors="replace"
        )

    ret_node = node.child_by_field_name("return_type")
    ret = ""
    if ret_node:
        ret_text = source_bytes[ret_node.start_byte : ret_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        ret = f" -> {ret_text}"

    return f"{name}{params}{ret}"


def _extract_symbol(node: Any, source_bytes: bytes, file_path: str, language: str) -> Symbol | None:
    """Extract a Symbol from an AST node."""
    lang_map = _SYMBOL_NODE_TYPES.get(language, {})
    kind = lang_map.get(node.type)
    if not kind:
        return None

    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    name = name_node.text.decode("utf-8", errors="replace")
    signature = _extract_signature(node, source_bytes)

    body_node = node.child_by_field_name("body")
    docstring = _extract_docstring(body_node, source_bytes) if body_node else None

    body = None
    if body_node:
        body = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    return Symbol(
        name=name,
        kind=kind,
        signature=signature,
        docstring=docstring,
        file_path=file_path,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        body=body,
    )


def _walk_tree(node: Any, source_bytes: bytes, file_path: str, language: str) -> list[Symbol]:
    """Walk AST tree and extract all symbols."""
    symbols: list[Symbol] = []

    def _walk(n: Any) -> None:
        sym = _extract_symbol(n, source_bytes, file_path, language)
        if sym:
            symbols.append(sym)
        for child in n.children:
            _walk(child)

    _walk(node)
    return symbols


class CodebaseAnalyzer:
    """Analyze codebase using tree-sitter AST parsing."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}

    def _get_cached_parser(self, language: str) -> Parser | None:
        if language not in self._parsers:
            self._parsers[language] = _get_parser(language)
        return self._parsers[language]

    def scan_file(self, file_path: str) -> list[Symbol]:
        """Scan a single file and return all symbols."""
        path = Path(file_path)
        if not path.exists():
            return []

        language = _detect_language(file_path)
        if not language:
            return []

        try:
            source = path.read_bytes()
        except Exception as e:
            logger.debug(f"Failed to read {file_path}: {e}")
            return []

        # Try tree-sitter first
        parser = self._get_cached_parser(language)
        if parser:
            try:
                tree = parser.parse(source)
                return _walk_tree(tree.root_node, source, file_path, language)
            except Exception as e:
                logger.debug(f"Tree-sitter failed for {file_path}: {e}")

        # Fallback to regex
        return self._regex_scan(source.decode("utf-8", errors="replace"), file_path, language)

    def _regex_scan(self, source: str, file_path: str, language: str) -> list[Symbol]:
        """Fallback regex-based symbol extraction."""
        symbols: list[Symbol] = []

        if language == "python":
            # Match: def name(params) -> return:
            for match in re.finditer(r"^def\s+(\w+)\s*\([^)]*\)(?:\s*->\s*[^:]+)?", source, re.M):
                line = source[: match.start()].count("\n") + 1
                symbols.append(
                    Symbol(
                        name=match.group(1),
                        kind="function",
                        signature=match.group(0).strip(),
                        docstring=None,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                    )
                )
            # Match: class Name:
            for match in re.finditer(r"^class\s+(\w+)(?:\([^)]*\))?:", source, re.M):
                line = source[: match.start()].count("\n") + 1
                symbols.append(
                    Symbol(
                        name=match.group(1),
                        kind="class",
                        signature=match.group(0).strip(),
                        docstring=None,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                    )
                )

        elif language in ("javascript", "typescript"):
            for match in re.finditer(r"function\s+(\w+)\s*\([^)]*\)", source):
                line = source[: match.start()].count("\n") + 1
                symbols.append(
                    Symbol(
                        name=match.group(1),
                        kind="function",
                        signature=match.group(0).strip(),
                        docstring=None,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                    )
                )
            for match in re.finditer(r"class\s+(\w+)", source):
                line = source[: match.start()].count("\n") + 1
                symbols.append(
                    Symbol(
                        name=match.group(1),
                        kind="class",
                        signature=match.group(0).strip(),
                        docstring=None,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                    )
                )

        return symbols

    def scan_project(
        self,
        path: str,
        languages: list[str] | None = None,
        max_files: int = 100,
    ) -> list[Symbol]:
        """Scan a project directory for symbols.

        Args:
            path: Project root directory.
            languages: List of languages to scan (e.g., ["python", "javascript"]).
                      If None, scans all supported languages.
            max_files: Maximum files to scan.

        Returns:
            List of all symbols found.
        """
        root = Path(path)
        if not root.exists():
            return []

        target_exts: set[str] = set()
        if languages:
            for lang in languages:
                for ext, mapped in _EXTENSION_MAP.items():
                    if mapped == lang:
                        target_exts.add(ext)
        else:
            target_exts = set(_EXTENSION_MAP.keys())

        symbols: list[Symbol] = []
        scanned = 0

        for ext in target_exts:
            for file_path in root.rglob(f"*{ext}"):
                if scanned >= max_files:
                    break
                # Skip common non-source directories
                parts = set(file_path.parts)
                if parts & {
                    "node_modules",
                    ".venv",
                    "venv",
                    "__pycache__",
                    ".git",
                    "dist",
                    "build",
                }:
                    continue
                symbols.extend(self.scan_file(str(file_path)))
                scanned += 1

        logger.info(f"Scanned {scanned} files, found {len(symbols)} symbols in {path}")
        return symbols

    def search_symbols(
        self,
        query: str,
        path: str,
        languages: list[str] | None = None,
        max_results: int = 20,
        file_pattern: str | None = None,
    ) -> list[Symbol]:
        """Search for symbols matching query.

        Args:
            query: Search term (matches symbol name).
            path: Project root or file path.
            languages: Filter by languages.
            max_results: Max symbols to return.
            file_pattern: Substring filter for file paths.

        Returns:
            Matching symbols sorted by relevance.
        """
        query_lower = query.lower()

        # If path is a file, scan just that file
        p = Path(path)
        if p.is_file():
            all_symbols = self.scan_file(str(p))
        else:
            all_symbols = self.scan_project(str(p), languages=languages)

        # Filter by query and file_pattern
        results: list[tuple[int, Symbol]] = []
        for sym in all_symbols:
            if file_pattern and file_pattern not in sym.file_path:
                continue

            score = 0
            name_lower = sym.name.lower()
            if name_lower == query_lower:
                score = 100  # Exact match
            elif query_lower in name_lower:
                score = 50  # Substring match
            elif query_lower in sym.signature.lower():
                score = 20  # In signature
            elif query_lower in (sym.docstring or "").lower():
                score = 10  # In docstring

            if score > 0:
                results.append((score, sym))

        # Sort by score descending, then by name
        results.sort(key=lambda x: (-x[0], x[1].name))
        return [sym for _, sym in results[:max_results]]

    def get_outline(self, file_path: str) -> dict[str, Any]:
        """Get structural outline of a file.

        Returns:
            Dict with file info and list of symbols (names + signatures only).
        """
        symbols = self.scan_file(file_path)
        return {
            "file_path": file_path,
            "language": _detect_language(file_path),
            "symbol_count": len(symbols),
            "symbols": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "signature": s.signature,
                    "line": s.line_start,
                }
                for s in symbols
            ],
        }

    def get_symbol_body(self, file_path: str, symbol_name: str) -> Symbol | None:
        """Get full body of a specific symbol.

        Args:
            file_path: Path to source file.
            symbol_name: Name of the symbol to find.

        Returns:
            Symbol with body, or None if not found.
        """
        symbols = self.scan_file(file_path)
        for sym in symbols:
            if sym.name == symbol_name:
                return sym
        return None


def get_analyzer() -> CodebaseAnalyzer:
    """Get or create a CodebaseAnalyzer instance."""
    return CodebaseAnalyzer()
