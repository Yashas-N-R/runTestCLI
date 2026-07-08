"""Scanners discover TestCase objects for a given source stack/language."""

from __future__ import annotations

import os

from nltest.config import NLTestConfig
from nltest.models import TestCase

from .java_scanner import scan_java
from .js_scanner import scan_js
from .python_scanner import scan_python

ALL_SCANNERS = (scan_python, scan_js, scan_java)


def iter_source_files(config: NLTestConfig, extensions: tuple[str, ...]) -> list[str]:
    """Walk the repo root, returning absolute paths of files matching extensions,
    while skipping excluded directories."""
    roots = [os.path.join(config.repo_root, d) for d in config.include_dirs] or [config.repo_root]
    found: list[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in config.exclude_dirs and not d.startswith(".")]
            for fname in filenames:
                if fname.endswith(extensions):
                    found.append(os.path.join(dirpath, fname))
    return sorted(found)


def scan_repo(config: NLTestConfig) -> list[TestCase]:
    """Run every scanner over the repo and return the combined list of test cases."""
    all_tests: list[TestCase] = []
    for scanner in ALL_SCANNERS:
        all_tests.extend(scanner(config))
    return all_tests
