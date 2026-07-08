"""Widens the NL-matching signal beyond a single test's own title/tags/body:

1. Every comment in the file the test lives in (a comment at the top of the
   file describing the feature, or on a helper used by several tests).
2. The content of any *locally defined* page-object/helper file the test file
   imports (e.g. a Selenium `RecordingPage` class, a Cypress command file) --
   the feature might only be named in the helper, not in the test itself.

Both are captured once per source *file* (not per test) and shared by every
test found in that file, since scanning is already per-file.
"""

from __future__ import annotations

import os
import re

MAX_IMPORT_FOLLOWS = 3
MAX_IMPORT_CONTENT = 2000

_PY_COMMENT_RE = re.compile(r"#.*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//.*")

_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+[\w.]+\s+import\s+([\w, *]+)|import\s+([\w.]+(?:\s*,\s*[\w.]+)*))", re.MULTILINE
)
_JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?from\s+|require\()\s*['"]([^'"]+)['"]""")
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)


def extract_python_comments(source: str) -> str:
    """All `#` comments in a file, including ones outside any single test
    (e.g. a module-level comment describing what the whole file covers)."""
    return "\n".join(_PY_COMMENT_RE.findall(source))


def extract_c_style_comments(source: str) -> str:
    """All `//` and `/* */` comments in a file (JS/TS/Java)."""
    blocks = _BLOCK_COMMENT_RE.findall(source)
    lines = _LINE_COMMENT_RE.findall(source)
    return "\n".join(blocks + lines)


def _local_import_names_python(source: str) -> list[str]:
    names = []
    for from_part, import_part in _PY_IMPORT_RE.findall(source):
        blob = from_part or import_part
        for token in re.split(r"[,\s]+", blob):
            token = token.strip().split(".")[-1]
            if token and token not in ("*", "import"):
                names.append(token)
    return names


def _local_import_names_js(source: str) -> list[str]:
    names = []
    for path in _JS_IMPORT_RE.findall(source):
        if path.startswith("."):
            names.append(os.path.splitext(os.path.basename(path))[0])
    return names


def _local_import_names_java(source: str) -> list[str]:
    return [imp.split(".")[-1] for imp in _JAVA_IMPORT_RE.findall(source)]


_IMPORT_EXTRACTORS = {
    "python": _local_import_names_python,
    "javascript": _local_import_names_js,
    "typescript": _local_import_names_js,
    "java": _local_import_names_java,
}


def build_filename_index(paths: list[str]) -> dict[str, str]:
    """Map lowercased basename-without-extension -> absolute path, for a set
    of already-discovered source files. Used to resolve local imports to an
    actual file in the repo without re-walking the filesystem per import."""
    index: dict[str, str] = {}
    for path in paths:
        key = os.path.splitext(os.path.basename(path))[0].lower()
        index.setdefault(key, path)
    return index


def resolve_local_imports(source: str, language: str, filename_index: dict[str, str]) -> str:
    """Best-effort: find names locally imported by this file, look them up in
    `filename_index`, and return a snippet of each match's content. Only
    names that resolve to an actual file already discovered in this repo are
    followed -- third-party/stdlib imports simply won't be in the index."""
    extractor = _IMPORT_EXTRACTORS.get(language)
    if not extractor:
        return ""

    snippets = []
    followed = 0
    seen: set[str] = set()
    for name in extractor(source):
        key = name.lower()
        if followed >= MAX_IMPORT_FOLLOWS or key in seen:
            continue
        seen.add(key)
        match_path = filename_index.get(key)
        if not match_path:
            continue
        try:
            with open(match_path, "r", encoding="utf-8", errors="ignore") as fh:
                snippets.append(fh.read(MAX_IMPORT_CONTENT))
        except OSError:
            continue
        followed += 1

    return "\n".join(snippets)


def build_file_context(source: str, language: str, filename_index: dict[str, str]) -> str:
    """Convenience: file-level comments + locally-imported helper content."""
    if language == "python":
        comments = extract_python_comments(source)
    elif language in ("javascript", "typescript", "java"):
        comments = extract_c_style_comments(source)
    else:
        comments = ""
    imported = resolve_local_imports(source, language, filename_index)
    return "\n".join(part for part in (comments, imported) if part)
