"""Scanner for Python test suites (pytest / unittest), including Selenium and
Playwright-Python based tests."""

from __future__ import annotations

import ast
import os
import re

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack, TestCase

TAG_COMMENT_RE = re.compile(r"#\s*tags?:\s*(.+)$", re.IGNORECASE)


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
    if len(parts) >= 3 and parts[0] == "pytest" and parts[1] == "mark":
        names.append(parts[2])
    return names


def _leading_tag_comment(lines: list[str], lineno: int) -> list[str]:
    """Look at comment lines directly above a def/class for `# tags: a, b, c`."""
    tags: list[str] = []
    idx = lineno - 2  # lineno is 1-indexed; look at the line(s) above
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = TAG_COMMENT_RE.search(line)
        if m:
            tags.extend(t.strip() for t in m.group(1).split(",") if t.strip())
            idx -= 1
            continue
        if line.startswith("@") or line.startswith("#"):
            idx -= 1
            continue
        break
    return tags


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
            for dec in node.decorator_list:
                tags.extend(_marker_names(dec))
            tags.extend(_leading_tag_comment(lines, node.lineno))
            description = ast.get_docstring(node) or ""
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
