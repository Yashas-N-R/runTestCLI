"""Scanner for Python test suites (pytest / unittest), including Selenium and
Playwright-Python based tests."""

from __future__ import annotations

import ast
import os
import re

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack, TestCase

TAG_COMMENT_RE = re.compile(r"#\s*tags?:\s*(.+)$", re.IGNORECASE)
DEPENDS_COMMENT_RE = re.compile(r"#\s*depends-on:\s*(.+)$", re.IGNORECASE)


def _detect_stack(source: str) -> Stack:
    if re.search(r"\bfrom\s+selenium\b|\bimport\s+selenium\b", source):
        return Stack.SELENIUM
    if re.search(r"\bplaywright\b", source):
        return Stack.PLAYWRIGHT
    if re.search(r"\bappium\b", source):
        return Stack.APPIUM
    if re.search(r"\brequests\b|\brest_assured\b|\bhttpx\b", source):
        return Stack.REST_ASSURED
    return Stack.UNKNOWN


def _detect_framework(source: str, stack: Stack) -> Framework:
    if stack == Stack.PLAYWRIGHT:
        return Framework.PLAYWRIGHT_PY
    return Framework.PYTEST


def _marker_names(decorator: ast.expr) -> list[str]:
    """Extract pytest.mark.<name> (and args) from a decorator node."""
    names: list[str] = []
    node = decorator
    # e.g. @pytest.mark.recording or @pytest.mark.recording("slow")
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    parts.reverse()
    if len(parts) >= 3 and parts[0] == "pytest" and parts[1] == "mark" and parts[2] != "dependency":
        names.append(parts[2])
    return names


def _leading_comments(lines: list[str], lineno: int, pattern: re.Pattern) -> list[str]:
    """Look at comment lines directly above a def/class matching `pattern`."""
    found: list[str] = []
    idx = lineno - 2  # lineno is 1-indexed; look at the line(s) above
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = pattern.search(line)
        if m:
            found.extend(t.strip() for t in m.group(1).split(",") if t.strip())
            idx -= 1
            continue
        if line.startswith("@") or line.startswith("#"):
            idx -= 1
            continue
        break
    return found


def _dependency_marker(decorator: ast.expr) -> tuple[str | None, list[str]]:
    """Extract pytest-dependency's `@pytest.mark.dependency(name=..., depends=[...])`.

    Returns (own_name, depends_on_names).
    """
    if not isinstance(decorator, ast.Call):
        return None, []
    func = decorator.func
    parts = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    parts.reverse()
    if not (len(parts) >= 3 and parts[0] == "pytest" and parts[1] == "mark" and parts[2] == "dependency"):
        return None, []

    own_name = None
    depends: list[str] = []
    for kw in decorator.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            own_name = kw.value.value
        elif kw.arg == "depends" and isinstance(kw.value, (ast.List, ast.Tuple)):
            depends = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
    return own_name, depends


def scan_python(config: NLTestConfig) -> list[TestCase]:
    from . import iter_source_files

    tests: list[TestCase] = []
    for path in iter_source_files(config, (".py",)):
        base = os.path.basename(path)
        if not (base.startswith("test_") or base.endswith("_test.py") or "test" in base.lower()):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue

        lines = source.splitlines()
        stack = _detect_stack(source)
        framework = _detect_framework(source, stack)
        rel_path = os.path.relpath(path, config.repo_root)

        def collect_from_func(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None):
            if not node.name.startswith("test"):
                return
            tags: list[str] = []
            own_dep_name = None
            depends_on: list[str] = []
            for dec in node.decorator_list:
                tags.extend(_marker_names(dec))
                name, deps = _dependency_marker(dec)
                own_dep_name = own_dep_name or name
                depends_on.extend(deps)
            tags.extend(_leading_comments(lines, node.lineno, TAG_COMMENT_RE))
            depends_on.extend(_leading_comments(lines, node.lineno, DEPENDS_COMMENT_RE))
            description = ast.get_docstring(node) or ""
            body = ast.get_source_segment(source, node) or ""
            test_id = f"{rel_path}::{class_name + '::' if class_name else ''}{node.name}"
            tests.append(
                TestCase(
                    id=test_id,
                    name=node.name,
                    file_path=rel_path,
                    framework=framework,
                    stack=stack,
                    class_name=class_name,
                    line=node.lineno,
                    tags=sorted(set(tags)),
                    description=description,
                    body=body,
                    depends_on=sorted(set(depends_on)),
                    dependency_name=own_dep_name,
                    language="python",
                )
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_tags = []
                for dec in node.decorator_list:
                    class_tags.extend(_marker_names(dec))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        collect_from_func(item, node.name)
                        if class_tags:
                            tests[-1].tags = sorted(set(tests[-1].tags) | set(class_tags))

        # Top-level test_ functions (not inside a class), scanned separately from
        # the module body only, so they aren't confused with methods above.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                collect_from_func(node, None)

    return tests
