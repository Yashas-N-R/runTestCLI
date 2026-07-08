"""Dispatches matched TestCases to the right framework-specific runner."""

from __future__ import annotations

from collections import defaultdict

from nltest.models import Framework, MatchResult, TestResult

from .java_runner import run_java_tests
from .js_runner import DISPATCH as JS_DISPATCH
from .pytest_runner import run_pytest_tests

FRAMEWORK_RUNNERS = {
    Framework.PYTEST: run_pytest_tests,
    Framework.PLAYWRIGHT_PY: run_pytest_tests,
    Framework.JUNIT: run_java_tests,
    Framework.TESTNG: run_java_tests,
    **JS_DISPATCH,
}


def run_matches(
    matches: list[MatchResult], repo_root: str, dry_run: bool = False, extra_args: str = "", exact: bool = False
) -> list[TestResult]:
    """Group matches by framework and execute each group with the appropriate runner.

    By default (`exact=False`, "safe mode"), runners execute at file/class
    granularity rather than cherry-picking individual test IDs, so that
    setup another (unselected) test in the same file/class performs -- shared
    fixtures, `beforeEach` hooks, TestNG `dependsOnMethods`, ordering -- still
    happens. Pass `exact=True` to only run the exact matched tests (faster,
    but riskier for suites with inter-test dependencies).
    """
    grouped = defaultdict(list)
    for m in matches:
        grouped[m.test.framework].append(m.test)

    all_results: list[TestResult] = []
    for framework, tests in grouped.items():
        runner = FRAMEWORK_RUNNERS.get(framework)
        if runner is None:
            for t in tests:
                from nltest.models import Status, TestResult as TR

                all_results.append(TR(test=t, status=Status.ERROR, message=f"No runner implemented for framework {framework}"))
            continue
        all_results.extend(runner(tests, repo_root, dry_run=dry_run, extra_args=extra_args, exact=exact))
    return all_results
