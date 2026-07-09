"""Scanner for Java test suites: JUnit (4/5) and TestNG, including Selenium and
REST Assured based tests."""

from __future__ import annotations

import os
import re

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack, TestCase

from .context import build_file_context, build_filename_index

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"\bclass\s+(\w+)")
METHOD_RE = re.compile(
    r"(?P<annotations>(?:@\w[\w()\"'.,\s{}=]*\s*)*)"
    r"(?:public|protected|private)?\s*(?:void|\w[\w<>\[\], ]*)\s+"
    r"(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{",
)
TESTNG_GROUPS_RE = re.compile(r"groups\s*=\s*\{([^}]*)\}")
TESTNG_DEPENDS_METHODS_RE = re.compile(r"dependsOnMethods\s*=\s*\{([^}]*)\}")
TESTNG_DEPENDS_GROUPS_RE = re.compile(r"dependsOnGroups\s*=\s*\{([^}]*)\}")
JUNIT_TAG_RE = re.compile(r"@Tag\(\s*\"([^\"]+)\"\s*\)")
DISPLAY_NAME_RE = re.compile(r"@DisplayName\(\s*\"([^\"]+)\"\s*\)")
TAG_COMMENT_RE = re.compile(r"//\s*tags?:\s*(.+)$", re.IGNORECASE)
DEPENDS_COMMENT_RE = re.compile(r"//\s*depends-on:\s*(.+)$", re.IGNORECASE)


def _extract_braced_body(source: str, from_idx: int, max_len: int = 6000) -> str:
    """Return the text from the method's opening `{` (at/after from_idx) through
    its matching closing `}`, used as a fallback for content-based NL matching."""
    start = source.find("{", from_idx)
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


def _detect_stack(source: str) -> Stack:
    if "org.openqa.selenium" in source:
        return Stack.SELENIUM
    if "io.restassured" in source or "RestAssured" in source:
        return Stack.REST_ASSURED
    if "io.appium" in source:
        return Stack.APPIUM
    return Stack.UNKNOWN


def _detect_framework(source: str) -> Framework:
    if "org.testng" in source:
        return Framework.TESTNG
    return Framework.JUNIT


def _string_list(raw: str) -> list[str]:
    return [s.strip().strip("\"'") for s in raw.split(",") if s.strip()]


def _leading_comments(lines: list[str], lineno: int, pattern: re.Pattern) -> list[str]:
    found: list[str] = []
    idx = lineno - 2
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = pattern.search(line)
        if m:
            found.extend(_string_list(m.group(1)))
            idx -= 1
            continue
        if line.startswith("//") or line.startswith("@"):
            idx -= 1
            continue
        break
    return found


def scan_java(config: NLTestConfig) -> list[TestCase]:
    from . import iter_source_files

    all_java_paths = iter_source_files(config, (".java",))
    filename_index = build_filename_index(all_java_paths)

    tests: list[TestCase] = []
    for path in all_java_paths:
        base = os.path.basename(path)
        if not (base.endswith("Test.java") or base.endswith("Tests.java") or base.startswith("Test")):
            continue
        try:
            from nltest.security import safe_read_text

            source = safe_read_text(path, config.repo_root)
            if source is None:
                continue
        except (UnicodeDecodeError, OSError):
            continue

        pkg_match = PACKAGE_RE.search(source)
        package = pkg_match.group(1) if pkg_match else ""
        class_match = CLASS_RE.search(source)
        class_name = class_match.group(1) if class_match else base.replace(".java", "")

        stack = _detect_stack(source)
        framework = _detect_framework(source)
        rel_path = os.path.relpath(path, config.repo_root)
        lines = source.splitlines()
        file_context = (
            build_file_context(source, "java", filename_index, config.repo_root) if config.search_body else ""
        )

        for m in METHOD_RE.finditer(source):
            annotations = m.group("annotations")
            if "@Test" not in annotations:
                continue
            name = m.group("name")
            lineno = source.count("\n", 0, m.start()) + 1

            tags: list[str] = []
            for grp in TESTNG_GROUPS_RE.finditer(annotations):
                tags.extend(_string_list(grp.group(1)))
            for tg in JUNIT_TAG_RE.finditer(annotations):
                tags.append(tg.group(1))
            tags.extend(_leading_comments(lines, lineno, TAG_COMMENT_RE))

            depends_on: list[str] = []
            for dep in TESTNG_DEPENDS_METHODS_RE.finditer(annotations):
                depends_on.extend(_string_list(dep.group(1)))
            for dep_grp in TESTNG_DEPENDS_GROUPS_RE.finditer(annotations):
                # dependsOnGroups references a group name, not a specific method;
                # record it so dependency resolution can pull in any test tagged
                # with that group.
                depends_on.extend(f"group:{g}" for g in _string_list(dep_grp.group(1)))
            depends_on.extend(_leading_comments(lines, lineno, DEPENDS_COMMENT_RE))

            display_name_match = DISPLAY_NAME_RE.search(annotations)
            description = display_name_match.group(1) if display_name_match else ""
            body = _extract_braced_body(source, m.end() - 1)

            fq_class = f"{package}.{class_name}" if package else class_name
            test_id = f"{rel_path}::{class_name}::{name}"
            tests.append(
                TestCase(
                    id=test_id,
                    name=name,
                    file_path=rel_path,
                    framework=framework,
                    stack=stack,
                    class_name=fq_class,
                    line=lineno,
                    tags=sorted(set(tags)),
                    description=description,
                    body=body,
                    depends_on=sorted(set(depends_on)),
                    file_context=file_context,
                    language="java",
                )
            )

    return tests
