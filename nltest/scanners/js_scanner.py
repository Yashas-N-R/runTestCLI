"""Scanner for JavaScript/TypeScript test suites: Playwright, Cypress, Jest, Mocha.

These frameworks share a very similar `describe`/`it`/`test` BDD-style syntax,
so we use a single regex-based scanner and disambiguate the framework from
file location, imports, and Cypress-specific globals (`cy.`).
"""

from __future__ import annotations

import os
import re

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack, TestCase

JS_TEST_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# Matches: it("name", ...), it('name', ...), test("name", ...), it.only(...), test.skip(...)
TEST_BLOCK_RE = re.compile(
    r"""(?P<kind>\bit|\btest)(?:\.(?:only|skip))?\s*\(\s*(?P<quote>['"`])(?P<name>(?:\\.|(?!\2).)*)\2""",
    re.VERBOSE,
)
DESCRIBE_RE = re.compile(
    r"""\bdescribe(?:\.(?:only|skip))?\s*\(\s*(?P<quote>['"`])(?P<name>(?:\\.|(?!\1).)*)\1""",
)
TAG_ANNOTATION_RE = re.compile(r"@(?P<tag>[a-zA-Z][\w-]*)")
TAG_COMMENT_RE = re.compile(r"//\s*tags?:\s*(.+)$", re.IGNORECASE)
DEPENDS_COMMENT_RE = re.compile(r"//\s*depends-on:\s*(.+)$", re.IGNORECASE)


def _extract_braced_body(source: str, from_offset: int, max_len: int = 4000) -> str:
    """Best-effort: find the first `{` at/after `from_offset` and return the
    text up to its matching `}` (used to grab a test's callback body for
    content-based NL matching)."""
    start = source.find("{", from_offset)
    if start == -1:
        return ""
    depth = 0
    for i in range(start, min(len(source), start + max_len)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    return source[start : start + max_len]


def _detect_stack_and_framework(path: str, source: str) -> tuple[Stack, Framework]:
    lower_path = path.lower()
    if "cypress" in lower_path or re.search(r"\bcy\.\w+\(", source):
        return Stack.CYPRESS, Framework.CYPRESS
    if "@playwright/test" in source or "playwright" in lower_path:
        return Stack.PLAYWRIGHT, Framework.PLAYWRIGHT_JS
    if re.search(r"\bfrom ['\"]selenium-webdriver['\"]", source):
        return Stack.SELENIUM, Framework.MOCHA
    if "jest" in lower_path or re.search(r"\bexpect\(.+\)\.to(?:Be|Equal|Contain)", source):
        return Stack.UNKNOWN, Framework.JEST
    return Stack.UNKNOWN, Framework.MOCHA


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _tags_near(lines: list[str], lineno: int, title: str) -> list[str]:
    tags: list[str] = []
    for m in TAG_ANNOTATION_RE.finditer(title):
        tags.append(m.group("tag"))
    idx = lineno - 2
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = TAG_COMMENT_RE.search(line)
        if m:
            tags.extend(t.strip() for t in m.group(1).split(",") if t.strip())
            idx -= 1
            continue
        if line.startswith("//"):
            idx -= 1
            continue
        break
    return tags


def _depends_near(lines: list[str], lineno: int) -> list[str]:
    depends: list[str] = []
    idx = lineno - 2
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = DEPENDS_COMMENT_RE.search(line)
        if m:
            depends.extend(t.strip() for t in m.group(1).split(",") if t.strip())
            idx -= 1
            continue
        if line.startswith("//"):
            idx -= 1
            continue
        break
    return depends


def scan_js(config: NLTestConfig) -> list[TestCase]:
    from . import iter_source_files

    tests: list[TestCase] = []
    for path in iter_source_files(config, JS_TEST_EXTENSIONS):
        base = os.path.basename(path).lower()
        is_test_file = (
            ".spec." in base
            or ".test." in base
            or "/cypress/" in path.replace("\\", "/").lower()
            or "cypress" in path.replace("\\", "/").lower().split(os.sep)[-2:-1]
        )
        if not is_test_file:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                source = fh.read()
        except (UnicodeDecodeError, OSError):
            continue

        stack, framework = _detect_stack_and_framework(path, source)
        rel_path = os.path.relpath(path, config.repo_root)
        lines = source.splitlines()

        # Track the nearest enclosing describe() block title (best-effort, by
        # scanning describes/its in source order and using indentation-free
        # "nearest preceding describe" heuristic).
        describes = [(m.start(), m.group("name")) for m in DESCRIBE_RE.finditer(source)]

        def nearest_describe(offset: int) -> str | None:
            candidate = None
            for start, name in describes:
                if start < offset:
                    candidate = name
                else:
                    break
            return candidate

        for m in TEST_BLOCK_RE.finditer(source):
            title = m.group("name")
            lineno = _line_number(source, m.start())
            class_name = nearest_describe(m.start())
            tags = _tags_near(lines, lineno, title)
            depends_on = _depends_near(lines, lineno)
            body = _extract_braced_body(source, m.end())
            test_id = f"{rel_path}::{class_name + ' > ' if class_name else ''}{title}"
            tests.append(
                TestCase(
                    id=test_id,
                    name=title,
                    file_path=rel_path,
                    framework=framework,
                    stack=stack,
                    class_name=class_name,
                    line=lineno,
                    tags=sorted(set(tags)),
                    description=title,
                    body=body,
                    depends_on=depends_on,
                    language="javascript" if path.endswith((".js", ".jsx", ".mjs", ".cjs")) else "typescript",
                )
            )

    return tests
