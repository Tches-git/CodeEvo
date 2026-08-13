"""Read-only repository workspace and Tree-sitter code intelligence tools."""
import hashlib
import os
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional


IGNORED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".idea", ".vscode", ".venv", "venv",
    "node_modules", "vendor", "dist", "build", "coverage", "__pycache__",
})
SENSITIVE_NAMES = frozenset({
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json",
    "id_rsa", "id_ed25519", "known_hosts",
})
SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".jks"})
INDEXED_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp",
    ".html", ".java", ".js", ".jsx", ".json", ".kt", ".kts",
    ".md", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".swift",
    ".toml", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
})
LANGUAGES = {
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".cs": "c_sharp", ".go": "go", ".java": "java", ".js": "javascript",
    ".jsx": "javascript", ".kt": "kotlin", ".kts": "kotlin",
    ".php": "php", ".py": "python", ".rb": "ruby", ".rs": "rust",
    ".swift": "swift", ".ts": "typescript", ".tsx": "tsx",
}
SYMBOL_KINDS = {
    "class_definition": "class",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_item": "trait",
    "struct_item": "struct",
    "enum_item": "enum",
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "method_definition": "method",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "type_alias_declaration": "type",
}
CALL_NODE_TYPES = frozenset({"call", "call_expression", "method_invocation"})
IDENTIFIER_NODE_TYPES = frozenset({
    "identifier", "field_identifier", "property_identifier", "type_identifier",
})
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class WorkspaceSecurityError(ValueError):
    """A requested path is outside the configured read-only repository scope."""


def _walk_tree(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _node_text(source: bytes, node, limit: int = 500) -> str:
    return source[node.start_byte:node.end_byte].decode(
        "utf-8", errors="replace"
    )[:limit]


def _line_text(source: bytes, line: int) -> str:
    lines = source.decode("utf-8", errors="replace").splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1][:500]
    return ""


class RepositoryIndex:
    """Bounded, lazy Tree-sitter index for definitions, references and calls."""

    def __init__(self, workspace: "RepositoryWorkspace", max_bytes: int):
        self.workspace = workspace
        self.max_bytes = max(1, max_bytes)
        self._lock = threading.Lock()
        self._built = False
        self._units = []
        self._symbols = []
        self._languages = set()
        self._truncated = False
        self.parser_name = "text-fallback"

    def _build(self) -> None:
        if self._built:
            return
        with self._lock:
            if self._built:
                return
            try:
                from tree_sitter_language_pack import get_parser
            except ImportError:
                get_parser = None
            consumed = 0
            for path in self.workspace.iter_files(indexable_only=True):
                language = LANGUAGES.get(Path(path).suffix.lower())
                if not language:
                    continue
                try:
                    source = self.workspace.read_bytes(path)
                except (OSError, UnicodeError, WorkspaceSecurityError):
                    continue
                if consumed + len(source) > self.max_bytes:
                    self._truncated = True
                    break
                consumed += len(source)
                tree = None
                if get_parser is not None:
                    try:
                        tree = get_parser(language).parse(source)
                        self.parser_name = "tree-sitter-language-pack"
                    except Exception:
                        tree = None
                unit = {"path": path, "language": language, "source": source, "tree": tree}
                self._units.append(unit)
                self._languages.add(language)
                if tree is not None:
                    self._index_symbols(unit)
                else:
                    self._index_symbols_fallback(unit)
            self._built = True

    def _symbol_name(self, node, source: bytes) -> str:
        name_node = node.child_by_field_name("name")
        if name_node is None and node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            if declarator is not None:
                name_node = next(
                    (item for item in _walk_tree(declarator)
                     if item.type in IDENTIFIER_NODE_TYPES),
                    None,
                )
        if name_node is None:
            name_node = next(
                (item for item in node.children
                 if item.type in IDENTIFIER_NODE_TYPES),
                None,
            )
        return _node_text(source, name_node, 200) if name_node is not None else ""

    def _index_symbols(self, unit: dict) -> None:
        source = unit["source"]
        for node in _walk_tree(unit["tree"].root_node):
            kind = SYMBOL_KINDS.get(node.type)
            if not kind:
                if node.type == "variable_declarator":
                    value = node.child_by_field_name("value")
                    if value is None or value.type not in {
                        "arrow_function", "function_expression", "function"
                    }:
                        continue
                    kind = "function"
                else:
                    continue
            name = self._symbol_name(node, source)
            if not name:
                continue
            self._symbols.append({
                "name": name,
                "kind": kind,
                "path": unit["path"],
                "start_line": node.start_point.row + 1,
                "end_line": node.end_point.row + 1,
                "language": unit["language"],
                "signature": _line_text(source, node.start_point.row + 1).strip(),
            })

    def _index_symbols_fallback(self, unit: dict) -> None:
        pattern = re.compile(
            r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        )
        text = unit["source"].decode("utf-8", errors="replace")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            self._symbols.append({
                "name": match.group(1), "kind": "symbol", "path": unit["path"],
                "start_line": line, "end_line": line,
                "language": unit["language"],
                "signature": text.splitlines()[line - 1][:500].strip(),
            })

    def status(self) -> dict:
        self._build()
        return self.summary_status()

    def summary_status(self) -> dict:
        return {
            "parser": self.parser_name if self._built else "not-built",
            "files_indexed": len(self._units),
            "symbols_indexed": len(self._symbols),
            "languages": sorted(self._languages),
            "truncated": self._truncated,
        }

    def find_symbols(self, query: str, limit: int = 50) -> List[dict]:
        self._build()
        value = query.strip().casefold()
        if not value:
            raise ValueError("symbol query is required")
        matches = [
            item for item in self._symbols if value in item["name"].casefold()
        ]
        matches.sort(key=lambda item: (
            item["name"].casefold() != value, item["path"], item["start_line"]
        ))
        return matches[:max(1, min(int(limit), 100))]

    def find_references(
        self, symbol: str, path: str = "", limit: int = 100,
    ) -> List[dict]:
        self._build()
        if not IDENTIFIER_PATTERN.fullmatch(symbol):
            raise ValueError("reference symbol must be an identifier")
        results = []
        for unit in self._units:
            if path and unit["path"] != path:
                continue
            tree = unit["tree"]
            if tree is None:
                results.extend(self._fallback_references(unit, symbol))
            else:
                for node in _walk_tree(tree.root_node):
                    if node.type not in IDENTIFIER_NODE_TYPES:
                        continue
                    if _node_text(unit["source"], node, 200) != symbol:
                        continue
                    results.append({
                        "symbol": symbol,
                        "path": unit["path"],
                        "line": node.start_point.row + 1,
                        "column": node.start_point.column + 1,
                        "context": _line_text(
                            unit["source"], node.start_point.row + 1
                        ).strip(),
                    })
                    if len(results) >= max(1, min(int(limit), 200)):
                        return results
        return results[:max(1, min(int(limit), 200))]

    def _fallback_references(self, unit: dict, symbol: str) -> List[dict]:
        results = []
        pattern = re.compile(r"\b%s\b" % re.escape(symbol))
        text = unit["source"].decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                results.append({
                    "symbol": symbol, "path": unit["path"], "line": line_number,
                    "column": match.start() + 1, "context": line[:500].strip(),
                })
        return results

    def find_callers(self, symbol: str, limit: int = 100) -> List[dict]:
        self._build()
        if not IDENTIFIER_PATTERN.fullmatch(symbol):
            raise ValueError("caller symbol must be an identifier")
        results = []
        maximum = max(1, min(int(limit), 200))
        for unit in self._units:
            tree = unit["tree"]
            if tree is None:
                continue
            for node in _walk_tree(tree.root_node):
                if node.type not in CALL_NODE_TYPES:
                    continue
                target = (
                    node.child_by_field_name("function")
                    or node.child_by_field_name("name")
                )
                target_text = _node_text(unit["source"], target, 300) if target else ""
                identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", target_text)
                if not identifiers or identifiers[-1] != symbol:
                    continue
                parent = node.parent
                caller = "<module>"
                while parent is not None:
                    if parent.type in SYMBOL_KINDS:
                        caller = self._symbol_name(parent, unit["source"]) or caller
                        break
                    parent = parent.parent
                results.append({
                    "callee": symbol,
                    "caller": caller,
                    "path": unit["path"],
                    "line": node.start_point.row + 1,
                    "context": _line_text(
                        unit["source"], node.start_point.row + 1
                    ).strip(),
                })
                if len(results) >= maximum:
                    return results
        return results


class RepositoryWorkspace:
    """A bounded, read-only view over one checked-out repository."""

    def __init__(
        self,
        root: Path,
        max_file_bytes: int = 256 * 1024,
        max_files: int = 2000,
        max_index_bytes: int = 20 * 1024 * 1024,
    ):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceSecurityError("repository workspace must be a directory")
        self.max_file_bytes = max(1024, int(max_file_bytes))
        self.max_files = max(1, int(max_files))
        self.index = RepositoryIndex(self, max_index_bytes)

    @staticmethod
    def _validate_relative_path(path: str) -> PurePosixPath:
        if not path or "\x00" in path or "\\" in path:
            raise WorkspaceSecurityError("repository path is invalid")
        value = PurePosixPath(path)
        if value.is_absolute() or any(part in {"", ".", ".."} for part in value.parts):
            raise WorkspaceSecurityError("repository path must be relative and normalized")
        if any(part in IGNORED_DIRECTORIES for part in value.parts):
            raise WorkspaceSecurityError("repository path is excluded")
        if value.name.lower() in SENSITIVE_NAMES or value.suffix.lower() in SENSITIVE_SUFFIXES:
            raise WorkspaceSecurityError("sensitive repository file is excluded")
        return value

    def _resolve_file(self, path: str) -> Path:
        relative = self._validate_relative_path(path)
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceSecurityError("repository symlinks are not readable")
        candidate = current.resolve(strict=True)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceSecurityError("repository path escapes the workspace") from exc
        if not candidate.is_file():
            raise WorkspaceSecurityError("repository path is not a regular file")
        return candidate

    def read_bytes(self, path: str) -> bytes:
        candidate = self._resolve_file(path)
        size = candidate.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceSecurityError("repository file exceeds the read limit")
        value = candidate.read_bytes()
        if b"\x00" in value:
            raise WorkspaceSecurityError("binary repository files are not readable")
        return value

    def iter_files(self, indexable_only: bool = False) -> Iterable[str]:
        count = 0
        for current, directories, files in os.walk(self.root, followlinks=False):
            directories[:] = sorted(
                item for item in directories
                if item not in IGNORED_DIRECTORIES
                and not (Path(current) / item).is_symlink()
            )
            for name in sorted(files):
                candidate = Path(current) / name
                if candidate.is_symlink():
                    continue
                relative = candidate.relative_to(self.root).as_posix()
                try:
                    self._validate_relative_path(relative)
                except WorkspaceSecurityError:
                    continue
                if indexable_only and candidate.suffix.lower() not in INDEXED_SUFFIXES:
                    continue
                if candidate.stat().st_size > self.max_file_bytes:
                    continue
                yield relative
                count += 1
                if count >= self.max_files:
                    return

    def list_files(self, limit: int = 200) -> List[str]:
        return list(self.iter_files())[:max(1, min(int(limit), self.max_files))]

    def read_file(
        self, path: str, start_line: int = 1, end_line: Optional[int] = None,
    ) -> dict:
        start = max(1, int(start_line))
        end = start + 199 if end_line is None else int(end_line)
        if end < start or end - start + 1 > 200:
            raise ValueError("repository reads are limited to 200 lines")
        raw = self.read_bytes(path)
        text = raw.decode("utf-8")
        lines = text.splitlines()
        selected = lines[start - 1:end]
        actual_end = start + len(selected) - 1 if selected else start - 1
        digest = hashlib.sha256(raw).hexdigest()
        evidence_id = hashlib.sha256(
            ("%s:%s:%d:%d" % (path, digest, start, actual_end)).encode("utf-8")
        ).hexdigest()[:20]
        return {
            "source": "repository",
            "path": path,
            "start_line": start,
            "end_line": actual_end,
            "content": "\n".join(
                "%d: %s" % (number, line)
                for number, line in enumerate(selected, start)
            ),
            "sha256": digest,
            "evidence_id": evidence_id,
            "truncated": end < len(lines),
        }

    def read_context(self, path: str, line: int, radius: int = 4) -> dict:
        target = max(1, int(line))
        result = self.read_file(
            path,
            max(1, target - max(0, int(radius))),
            target + max(0, int(radius)),
        )
        prefix = "%d: " % target
        result["target_line"] = target
        result["target_content"] = next(
            (item[len(prefix):] for item in result["content"].splitlines()
             if item.startswith(prefix)),
            "",
        )
        return result

    def search_text(
        self, query: str, path: str = "", limit: int = 50,
    ) -> List[dict]:
        value = query.strip()
        if not value or len(value) > 200:
            raise ValueError("repository search query must contain 1-200 characters")
        paths = [path] if path else self.iter_files(indexable_only=True)
        results = []
        maximum = max(1, min(int(limit), 200))
        for item in paths:
            try:
                text = self.read_bytes(item).decode("utf-8")
            except (OSError, UnicodeError, WorkspaceSecurityError):
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if value.casefold() in line.casefold():
                    results.append({
                        "path": item, "line": line_number, "content": line[:500]
                    })
                    if len(results) >= maximum:
                        return results
        return results


class WorkspaceSession:
    """Assignment-scoped read ledger used to bind findings to tool evidence."""

    def __init__(self, workspace: RepositoryWorkspace):
        self.workspace = workspace
        self.reads: List[dict] = []

    def read_file(
        self, path: str, start_line: int = 1, end_line: Optional[int] = None,
    ) -> dict:
        result = self.workspace.read_file(path, start_line, end_line)
        self.reads.append({
            key: result[key]
            for key in (
                "source", "path", "start_line", "end_line", "sha256", "evidence_id"
            )
        } | {"content": result["content"]})
        return result

    def evidence_for(self, path: str, line: int) -> List[dict]:
        values = []
        prefix = "%d: " % line
        for item in self.reads:
            if item["path"] != path or not item["start_line"] <= line <= item["end_line"]:
                continue
            value = {key: detail for key, detail in item.items() if key != "content"}
            value["excerpt"] = next(
                (row[len(prefix):][:240] for row in item["content"].splitlines()
                 if row.startswith(prefix)),
                "",
            )
            values.append(value)
        return values


class RepositoryWorkspaceResolver:
    """Map a repository slug to a checkout below one administrator-owned root."""

    def __init__(
        self,
        root: str = "",
        max_file_bytes: int = 256 * 1024,
        max_files: int = 2000,
        max_index_bytes: int = 20 * 1024 * 1024,
    ):
        self.enabled = bool(root.strip())
        self.root = Path(root).resolve(strict=True) if self.enabled else None
        if self.root is not None and not self.root.is_dir():
            raise WorkspaceSecurityError("CODEEVO_REPOSITORY_ROOT must be a directory")
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.max_index_bytes = max_index_bytes

    def resolve(self, repository: str) -> Optional[RepositoryWorkspace]:
        if not self.enabled or not REPOSITORY_PATTERN.fullmatch(repository):
            return None
        candidate = (self.root / PurePosixPath(repository)).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        if not candidate.is_dir() or candidate.is_symlink():
            return None
        return RepositoryWorkspace(
            candidate,
            self.max_file_bytes,
            self.max_files,
            self.max_index_bytes,
        )
