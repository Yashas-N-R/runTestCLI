"""Runner for pytest-based suites (plain pytest, Selenium-in-pytest,
Playwright-Python)."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time

from nltest.models import Status, TestCase, TestResult

from .junit_xml import parse_junit_xml_files


def _node_id(test: TestCase) -> str:
    if test.class_name:
        return f"{test.file_path}::{test.class_name}::{test.name}"
    return f"{test.file_path}::{test.name}"


def build_command(tests: list[TestCase], junit_xml_path: str, extra_args: str = "") -> list[str]:
    cmd = ["pytest", "-v", f"--junitxml={junit_xml_path}"]
    if extra_args:
        cmd.extend(shlex.split(extra_args))
    cmd.extend(_node_id(t) for t in tests)
    return cmd


def run_pytest_tests(tests: list[TestCase], repo_root: str, dry_run: bool = False, extra_args: str = "") -> list[TestResult]:
    if not tests:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        junit_path = os.path.join(tmp, "junit.xml")
        cmd = build_command(tests, junit_path, extra_args)

        if dry_run:
            return [
                TestResult(test=t, status=Status.SKIPPED, message=f"[dry-run] {' '.join(cmd)}")
                for t in tests
            ]

        start = time.time()
        try:
            proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            return [
                TestResult(test=t, status=Status.ERROR, message="pytest is not installed/available on PATH")
                for t in tests
            ]
        except subprocess.TimeoutExpired:
            return [
                TestResult(test=t, status=Status.ERROR, message="pytest run timed out after 1800s")
                for t in tests
            ]
        duration = time.time() - start

        parsed = parse_junit_xml_files([junit_path]) if os.path.exists(junit_path) else {}

        results: list[TestResult] = []
        for t in tests:
            key_candidates = [t.name, f"{t.class_name}.{t.name}" if t.class_name else t.name]
            match = None
            for key in key_candidates:
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
                        message="(no junit entry found; result inferred from process exit code)\n" + tail,
                    )
                )
        return results
