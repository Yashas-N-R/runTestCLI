"""Runners for Node-based suites: Playwright (JS/TS), Jest, Mocha, and Cypress."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

from nltest.models import Framework, Status, TestCase, TestResult

_STATUS_MAP = {
    "passed": Status.PASSED,
    "pass": Status.PASSED,
    "ok": Status.PASSED,
    "failed": Status.FAILED,
    "fail": Status.FAILED,
    "timedOut": Status.FAILED,
    "skipped": Status.SKIPPED,
    "pending": Status.SKIPPED,
    "interrupted": Status.ERROR,
}


def _which(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


def _run(cmd: list[str], cwd: str, timeout: int = 1800) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def _dry_run_results(tests: list[TestCase], cmd: list[str]) -> list[TestResult]:
    return [TestResult(test=t, status=Status.SKIPPED, message=f"[dry-run] {' '.join(cmd)}") for t in tests]


def _fallback_results(tests: list[TestCase], returncode: int, stdout: str, stderr: str, duration: float) -> list[TestResult]:
    status = Status.PASSED if returncode == 0 else Status.ERROR
    tail = (stdout or "")[-1500:] + (stderr or "")[-500:]
    return [
        TestResult(
            test=t,
            status=status,
            duration_seconds=duration / max(len(tests), 1),
            message="(result inferred from process exit code)\n" + tail,
        )
        for t in tests
    ]


def run_playwright_js_tests(tests: list[TestCase], repo_root: str, dry_run: bool = False, extra_args: str = "") -> list[TestResult]:
    if not tests:
        return []
    files = sorted({t.file_path for t in tests})
    names = [re.escape(t.name) for t in tests]
    grep = "|".join(names)
    cmd = ["npx", "playwright", "test", *files, "-g", grep, "--reporter=json"]
    if extra_args:
        cmd.extend(extra_args.split())

    if dry_run:
        return _dry_run_results(tests, cmd)

    start = time.time()
    returncode, stdout, stderr = _run(cmd, repo_root)
    duration = time.time() - start

    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return _fallback_results(tests, returncode, stdout, stderr, duration)

    by_title: dict[str, tuple[Status, float, str]] = {}

    def walk_suites(suite):
        for spec in suite.get("specs", []):
            title = spec.get("title", "")
            for result_entry in spec.get("tests", []):
                for r in result_entry.get("results", []):
                    status = _STATUS_MAP.get(r.get("status", ""), Status.ERROR)
                    dur = (r.get("duration", 0) or 0) / 1000.0
                    msg = r.get("error", {}).get("message", "") if r.get("error") else ""
                    by_title[title] = (status, dur, msg)
        for child in suite.get("suites", []):
            walk_suites(child)

    for suite in data.get("suites", []):
        walk_suites(suite)

    results = []
    for t in tests:
        if t.name in by_title:
            status, dur, msg = by_title[t.name]
            results.append(TestResult(test=t, status=status, duration_seconds=dur, message=msg))
        else:
            results.append(
                TestResult(
                    test=t,
                    status=Status.PASSED if returncode == 0 else Status.ERROR,
                    message="(no matching entry in playwright JSON report)",
                )
            )
    return results


def run_jest_tests(tests: list[TestCase], repo_root: str, dry_run: bool = False, extra_args: str = "") -> list[TestResult]:
    if not tests:
        return []
    files = sorted({t.file_path for t in tests})
    names = [re.escape(t.name) for t in tests]
    pattern = "|".join(names)

    with tempfile.TemporaryDirectory() as tmp:
        out_file = os.path.join(tmp, "jest-report.json")
        cmd = ["npx", "jest", *files, "-t", pattern, "--json", f"--outputFile={out_file}"]
        if extra_args:
            cmd.extend(extra_args.split())

        if dry_run:
            return _dry_run_results(tests, cmd)

        start = time.time()
        returncode, stdout, stderr = _run(cmd, repo_root)
        duration = time.time() - start

        if not os.path.exists(out_file):
            return _fallback_results(tests, returncode, stdout, stderr, duration)

        with open(out_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        by_title: dict[str, tuple[Status, float, str]] = {}
        for suite in data.get("testResults", []):
            for assertion in suite.get("assertionResults", []):
                title = assertion.get("title", "")
                status = _STATUS_MAP.get(assertion.get("status", ""), Status.ERROR)
                msg = "\n".join(assertion.get("failureMessages", []))
                by_title[title] = (status, 0.0, msg)

        results = []
        for t in tests:
            if t.name in by_title:
                status, dur, msg = by_title[t.name]
                results.append(TestResult(test=t, status=status, duration_seconds=dur, message=msg))
            else:
                results.append(
                    TestResult(
                        test=t,
                        status=Status.PASSED if returncode == 0 else Status.ERROR,
                        message="(no matching entry in jest JSON report)",
                    )
                )
        return results


def run_mocha_tests(tests: list[TestCase], repo_root: str, dry_run: bool = False, extra_args: str = "") -> list[TestResult]:
    if not tests:
        return []
    files = sorted({t.file_path for t in tests})
    names = [re.escape(t.name) for t in tests]
    grep = "|".join(names)
    cmd = ["npx", "mocha", *files, "--grep", grep, "--reporter", "json"]
    if extra_args:
        cmd.extend(extra_args.split())

    if dry_run:
        return _dry_run_results(tests, cmd)

    start = time.time()
    returncode, stdout, stderr = _run(cmd, repo_root)
    duration = time.time() - start

    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return _fallback_results(tests, returncode, stdout, stderr, duration)

    by_title: dict[str, tuple[Status, float, str]] = {}
    for p in data.get("passes", []):
        by_title[p.get("title", "")] = (Status.PASSED, (p.get("duration", 0) or 0) / 1000.0, "")
    for f in data.get("failures", []):
        by_title[f.get("title", "")] = (Status.FAILED, (f.get("duration", 0) or 0) / 1000.0, f.get("err", {}).get("message", ""))
    for p in data.get("pending", []):
        by_title[p.get("title", "")] = (Status.SKIPPED, 0.0, "")

    results = []
    for t in tests:
        if t.name in by_title:
            status, dur, msg = by_title[t.name]
            results.append(TestResult(test=t, status=status, duration_seconds=dur, message=msg))
        else:
            results.append(
                TestResult(
                    test=t,
                    status=Status.PASSED if returncode == 0 else Status.ERROR,
                    message="(no matching entry in mocha JSON report)",
                )
            )
    return results


_CY_PASS_RE = re.compile(r"✓\s+(.+?)\s*(?:\(\d+[a-z]*\))?\s*$")
_CY_FAIL_RE = re.compile(r"^\s*\d+\)\s+(?:.*?\s+)?(.+)$")


def run_cypress_tests(tests: list[TestCase], repo_root: str, dry_run: bool = False, extra_args: str = "") -> list[TestResult]:
    if not tests:
        return []
    files = sorted({t.file_path for t in tests})
    cmd = ["npx", "cypress", "run", "--spec", ",".join(files)]
    if extra_args:
        cmd.extend(extra_args.split())

    if dry_run:
        return _dry_run_results(tests, cmd)

    start = time.time()
    returncode, stdout, stderr = _run(cmd, repo_root)
    duration = time.time() - start

    passed_titles = set(m.group(1).strip() for m in _CY_PASS_RE.finditer(stdout))
    failed_titles = set(m.group(1).strip() for m in _CY_FAIL_RE.finditer(stdout))

    results = []
    for t in tests:
        if t.name in passed_titles:
            results.append(TestResult(test=t, status=Status.PASSED))
        elif t.name in failed_titles or any(t.name in title for title in failed_titles):
            results.append(TestResult(test=t, status=Status.FAILED, message=stdout[-1500:]))
        else:
            results.append(
                TestResult(
                    test=t,
                    status=Status.PASSED if returncode == 0 else Status.ERROR,
                    message="(status inferred from Cypress console output/exit code; "
                    "install a JSON mocha reporter for precise per-test results)",
                )
            )
    return results


DISPATCH = {
    Framework.PLAYWRIGHT_JS: run_playwright_js_tests,
    Framework.JEST: run_jest_tests,
    Framework.MOCHA: run_mocha_tests,
    Framework.CYPRESS: run_cypress_tests,
}
