"""Shared JUnit-XML parsing, since pytest, Java Surefire/Gradle, and several
JS reporters can all emit results in (roughly) this format."""

from __future__ import annotations

import glob
import xml.etree.ElementTree as ET

from nltest.models import Status


def parse_junit_xml_files(paths: list[str]) -> dict[str, tuple[Status, float, str]]:
    """Parse one or more JUnit XML report files.

    Returns a dict keyed by a "loose" test name (the `name` attribute of each
    `<testcase>`, as well as `classname.name`) mapping to (status, duration, message).
    Callers should try the most specific key first.
    """
    results: dict[str, tuple[Status, float, str]] = {}
    for path in paths:
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        root = tree.getroot()
        testcases = root.iter("testcase")
        for tc in testcases:
            name = tc.get("name", "")
            classname = tc.get("classname", "")
            duration = float(tc.get("time", 0) or 0)

            status = Status.PASSED
            message = ""
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")
            if failure is not None:
                status = Status.FAILED
                message = failure.get("message", "") or (failure.text or "")
            elif error is not None:
                status = Status.ERROR
                message = error.get("message", "") or (error.text or "")
            elif skipped is not None:
                status = Status.SKIPPED
                message = skipped.get("message", "") or ""

            results[name] = (status, duration, message)
            if classname:
                results[f"{classname}.{name}"] = (status, duration, message)
                short_class = classname.rsplit(".", 1)[-1]
                results[f"{short_class}.{name}"] = (status, duration, message)
    return results


def find_reports(pattern: str) -> list[str]:
    return glob.glob(pattern, recursive=True)
