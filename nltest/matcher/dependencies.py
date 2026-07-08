"""Resolves explicit test-to-test dependencies so that running a matched
subset of tests doesn't silently skip setup another test relies on.

Handles:
  - TestNG `dependsOnMethods = {...}` (resolved within the same class)
  - TestNG `dependsOnGroups = {...}` (resolved via shared tags/groups)
  - pytest-dependency `@pytest.mark.dependency(name=..., depends=[...])`
    (resolved by registered dependency name, repo-wide)
  - A universal `# depends-on: <name>` / `// depends-on: <name>` comment
    convention (resolved by test name, first within the same file, then
    repo-wide) for frameworks without a native dependency mechanism.
"""

from __future__ import annotations

from nltest.models import MatchResult, TestCase

GROUP_PREFIX = "group:"


def _index_tests(all_tests: list[TestCase]) -> tuple[
    dict[tuple[str | None, str], TestCase],
    dict[str, TestCase],
    dict[str, list[TestCase]],
]:
    """Build lookup indexes: (class_name, method_name) -> test, dependency_name -> test,
    and tag -> [tests] (for dependsOnGroups)."""
    by_class_method: dict[tuple[str | None, str], TestCase] = {}
    by_dependency_name: dict[str, TestCase] = {}
    by_tag: dict[str, list[TestCase]] = {}
    for t in all_tests:
        by_class_method[(t.class_name, t.name)] = t
        if t.dependency_name:
            by_dependency_name[t.dependency_name] = t
        for tag in t.tags:
            by_tag.setdefault(tag, []).append(t)
    return by_class_method, by_dependency_name, by_tag


def _by_name_in_file(all_tests: list[TestCase], file_path: str, name: str) -> TestCase | None:
    for t in all_tests:
        if t.file_path == file_path and t.name == name:
            return t
    return None


def _by_name_anywhere(all_tests: list[TestCase], name: str) -> TestCase | None:
    for t in all_tests:
        if t.name == name:
            return t
    return None


def resolve_dependencies(dep_ref: str, source_test: TestCase, all_tests: list[TestCase], indexes) -> list[TestCase]:
    by_class_method, by_dependency_name, by_tag = indexes

    if dep_ref.startswith(GROUP_PREFIX):
        group = dep_ref[len(GROUP_PREFIX) :]
        return by_tag.get(group, [])

    # 1. Same-class method (TestNG dependsOnMethods, Java-style).
    candidate = by_class_method.get((source_test.class_name, dep_ref))
    if candidate:
        return [candidate]

    # 2. Registered dependency name (pytest-dependency).
    candidate = by_dependency_name.get(dep_ref)
    if candidate:
        return [candidate]

    # 3. Same-file match by name (generic `# depends-on:` comment convention).
    candidate = _by_name_in_file(all_tests, source_test.file_path, dep_ref)
    if candidate:
        return [candidate]

    # 4. Fallback: anywhere in the repo by name.
    candidate = _by_name_anywhere(all_tests, dep_ref)
    if candidate:
        return [candidate]

    return []


def expand_with_dependencies(matches: list[MatchResult], all_tests: list[TestCase]) -> list[MatchResult]:
    """Given the tests matched by an NL query, transitively pull in any tests
    they explicitly depend on that weren't already matched."""
    indexes = _index_tests(all_tests)
    selected_ids = {m.test.id for m in matches}
    result = list(matches)
    queue = [m.test for m in matches]
    seen_ids = set(selected_ids)

    while queue:
        current = queue.pop(0)
        for dep_ref in current.depends_on:
            for dep_test in resolve_dependencies(dep_ref, current, all_tests, indexes):
                if dep_test.id in seen_ids:
                    continue
                seen_ids.add(dep_test.id)
                result.append(
                    MatchResult(
                        test=dep_test,
                        score=1.0,
                        matched_on=[f"dependency-of:{current.name}"],
                    )
                )
                queue.append(dep_test)

    return result
