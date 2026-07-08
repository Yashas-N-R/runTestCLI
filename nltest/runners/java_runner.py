"""Runner for Java suites (JUnit/TestNG), via Maven or Gradle, covering
Selenium and REST Assured tests."""

from __future__ import annotations

import os
import subprocess
import time

from nltest.models import Status, TestCase, TestResult
from nltest.security import build_subprocess_env, parse_extra_args

from .junit_xml import find_reports, parse_junit_xml_files


def _build_tool_at(project_dir: str) -> str | None:
    if os.path.exists(os.path.join(project_dir, "pom.xml")):
        return "maven"
    if os.path.exists(os.path.join(project_dir, "build.gradle")) or os.path.exists(
        os.path.join(project_dir, "build.gradle.kts")
    ):
        return "gradle"
    return None


def _find_project_root(repo_root: str, file_path: str) -> tuple[str, str | None]:
    """Walk upward from a test file's directory to find the nearest Maven/Gradle
    project root (handles multi-module monorepos where each module has its own
    pom.xml/build.gradle rather than one at the overall repo root)."""
    current = os.path.dirname(os.path.join(repo_root, file_path))
    repo_root_abs = os.path.abspath(repo_root)
    while True:
        tool = _build_tool_at(current)
        if tool:
            return current, tool
        if os.path.abspath(current) == repo_root_abs:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return repo_root, _build_tool_at(repo_root)


def _short_class(class_name: str | None) -> str:
    if not class_name:
        return ""
    return class_name.rsplit(".", 1)[-1]


def build_command(tool: str, repo_root: str, tests: list[TestCase], exact: bool = False) -> list[str]:
    if exact:
        # Fast but riskier: only the matched methods run. If one depends on
        # shared class-level state/ordering that another (unselected) method
        # in the class sets up, isolating it can behave differently.
        selectors = sorted({f"{_short_class(t.class_name)}#{t.name}" for t in tests})
    else:
        # Safe mode (default): run the whole class(es) the matched methods
        # belong to, so TestNG dependsOnMethods/dependsOnGroups, @Before*
        # hooks, and any shared instance state still execute as normal.
        selectors = sorted({_short_class(t.class_name) for t in tests})

    if tool == "maven":
        mvn = "./mvnw" if os.path.exists(os.path.join(repo_root, "mvnw")) else "mvn"
        return [mvn, "test", f"-Dtest={','.join(selectors)}", "-DfailIfNoTests=false"]

    if exact:
        gradle_selectors = sorted({f"{_short_class(t.class_name)}.{t.name}" for t in tests})
    else:
        gradle_selectors = selectors
    gradlew = "./gradlew" if os.path.exists(os.path.join(repo_root, "gradlew")) else "gradle"
    cmd = [gradlew, "test"]
    for sel in gradle_selectors:
        cmd.extend(["--tests", sel])
    return cmd


def _run_group(
    tests: list[TestCase],
    project_root: str,
    tool: str,
    dry_run: bool,
    extra_args: str,
    exact: bool,
    env: dict[str, str] | None = None,
) -> list[TestResult]:
    cmd = build_command(tool, project_root, tests, exact=exact)
    if extra_args:
        cmd.extend(parse_extra_args(extra_args))

    if dry_run:
        env_prefix = " ".join(f"{k}={v}" for k, v in (env or {}).items())
        shown_cmd = f"{env_prefix} {' '.join(cmd)}".strip()
        return [
            TestResult(test=t, status=Status.SKIPPED, message=f"[dry-run, cwd={project_root}] {shown_cmd}")
            for t in tests
        ]

    run_env = build_subprocess_env(env)
    start = time.time()
    try:
        proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=3600, env=run_env)
    except FileNotFoundError:
        return [
            TestResult(test=t, status=Status.ERROR, message=f"{tool} executable not found on PATH")
            for t in tests
        ]
    except subprocess.TimeoutExpired:
        return [TestResult(test=t, status=Status.ERROR, message="build timed out after 3600s") for t in tests]
    duration = time.time() - start

    if tool == "maven":
        report_files = find_reports(os.path.join(project_root, "**", "target", "surefire-reports", "*.xml"))
    else:
        report_files = find_reports(os.path.join(project_root, "**", "build", "test-results", "test", "*.xml"))
    parsed = parse_junit_xml_files(report_files) if report_files else {}

    results: list[TestResult] = []
    for t in tests:
        short_class = _short_class(t.class_name)
        candidates = [f"{short_class}.{t.name}", t.name]
        match = None
        for key in candidates:
            if key in parsed:
                match = parsed[key]
                break
        if match:
            status, dur, message = match
            results.append(TestResult(test=t, status=status, duration_seconds=dur, message=message))
        else:
            fallback_status = Status.PASSED if proc.returncode == 0 else Status.ERROR
            tail = (proc.stdout or "")[-1500:] + (proc.stderr or "")[-500:]
            results.append(
                TestResult(
                    test=t,
                    status=fallback_status,
                    duration_seconds=duration / max(len(tests), 1),
                    message="(no surefire/gradle test report entry found; inferred from exit code)\n" + tail,
                )
            )
    return results


def run_java_tests(
    tests: list[TestCase],
    repo_root: str,
    dry_run: bool = False,
    extra_args: str = "",
    exact: bool = False,
    env: dict[str, str] | None = None,
) -> list[TestResult]:
    if not tests:
        return []

    groups: dict[tuple[str, str | None], list[TestCase]] = {}
    for t in tests:
        project_root, tool = _find_project_root(repo_root, t.file_path)
        groups.setdefault((project_root, tool), []).append(t)

    results: list[TestResult] = []
    for (project_root, tool), group_tests in groups.items():
        if tool is None:
            results.extend(
                TestResult(
                    test=t,
                    status=Status.ERROR,
                    message="Could not detect a Maven (pom.xml) or Gradle (build.gradle) project "
                    f"for {t.file_path} (searched upward from the file to the repo root).",
                )
                for t in group_tests
            )
            continue
        results.extend(_run_group(group_tests, project_root, tool, dry_run, extra_args, exact, env))
    return results
