"""Scanner for Java test suites: JUnit (4/5) and TestNG, including Selenium and
REST Assured based tests."""

from __future__ import annotations

import os
import re

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack, TestCase

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"\bclass\s+(\w+)")
METHOD_RE = re.compile(
    r"(?P<annotations>(?:@\w[\w()\"'.,\s{}=]*\s*)*)"
    r"(?:public|protected|private)?\s*(?:void|\w[\w<>\[\], ]*)\s+"
    r"(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{",
)
TESTNG_GROUPS_RE = re.compile(r"groups\s*=\s*\{([^}]*)\}")
JUNIT_TAG_RE = re.compile(r"@Tag\(\s*\"([^\"]+)\"\s*\)")
DISPLAY_NAME_RE = re.compile(r"@DisplayName\(\s*\"([^\"]+)\"\s*\)")
TAG_COMMENT_RE = re.compile(r"//\s*tags?:\s*(.+)$", re.IGNORECASE)


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


def _tags_near(lines: list[str], lineno: int) -> list[str]:
    tags: list[str] = []
    idx = lineno - 2
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break
        m = TAG_COMMENT_RE.search(line)
        if m:
            tags.extend(_string_list(m.group(1)))
            idx -= 1
            continue
        if line.startswith("//") or line.startswith("@"):
            idx -= 1
            continue
        break
    return tags


def scan_java(config: NLTestConfig) -> list[TestCase]:
    from . import iter_source_files

    tests: list[TestCase] = []
    for path in iter_source_files(config, (".java",)):
        base = os.path.basename(path)
        if not (base.endswith("Test.java") or base.endswith("Tests.java") or base.startswith("Test")):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                source = fh.read()
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
            tags.extend(_tags_near(lines, lineno))

            display_name_match = DISPLAY_NAME_RE.search(annotations)
            description = display_name_match.group(1) if display_name_match else ""

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
                    language="java",
                )
            )

    return tests
