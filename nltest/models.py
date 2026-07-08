"""Core data models shared across scanners, matcher, runners and reporter."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Framework(str, Enum):
    """Test frameworks/stacks that nltest knows how to scan and run."""

    PYTEST = "pytest"
    PLAYWRIGHT_PY = "playwright-python"
    PLAYWRIGHT_JS = "playwright-js"
    CYPRESS = "cypress"
    JEST = "jest"
    MOCHA = "mocha"
    JUNIT = "junit"
    TESTNG = "testng"


class Stack(str, Enum):
    """Underlying tool/library a test is exercising (used for NL keyword hints)."""

    SELENIUM = "selenium"
    PLAYWRIGHT = "playwright"
    CYPRESS = "cypress"
    REST_ASSURED = "rest-assured"
    APPIUM = "appium"
    UNKNOWN = "unknown"


@dataclass
class TestCase:
    """A single discovered test case, normalized across languages/frameworks."""

    id: str
    """Stable, globally unique identifier, e.g. path::Class::method"""

    name: str
    """Human readable test name/method name (e.g. 'test_recording_starts')"""

    file_path: str
    """Path to the source file, relative to the repo root."""

    framework: Framework
    stack: Stack = Stack.UNKNOWN

    class_name: str | None = None
    line: int | None = None

    tags: list[str] = field(default_factory=list)
    """Explicit tags/markers (pytest markers, TestNG groups, JUnit @Tag, comments)."""

    description: str = ""
    """Docstring / display name / free text used for NL matching."""

    language: str = "unknown"

    def searchable_text(self) -> str:
        """All text associated with this test that NL matching should consider."""
        parts = [
            self.name,
            self.class_name or "",
            self.description,
            self.file_path,
            " ".join(self.tags),
            self.stack.value,
        ]
        return " ".join(p for p in parts if p)


@dataclass
class MatchResult:
    """A test case matched against an NL query, with a relevance score."""

    test: TestCase
    score: float
    matched_on: list[str] = field(default_factory=list)


class Status(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestResult:
    """Outcome of actually executing a (group of) test case(s)."""

    test: TestCase
    status: Status
    duration_seconds: float = 0.0
    message: str = ""


@dataclass
class RunReport:
    """Aggregate report for a full `nltest run` invocation."""

    query: str
    matches: list[MatchResult]
    results: list[TestResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    dry_run: bool = False

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.FAILED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == Status.SKIPPED)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == Status.ERROR)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None:
            return 0.0
        return self.finished_at - self.started_at
