"""Reads CI pipeline YAML files (GitHub Actions, GitLab CI, CircleCI, Azure
Pipelines, Bitbucket Pipelines) to infer the order/grouping the team already
runs test suites in -- e.g. "smoke" before "regression", "login" before
"checkout" -- so `nltest run` executes matched tests in that same order
instead of an arbitrary one.

This is a best-effort heuristic, not a full CI-schema parser: it walks the
YAML document depth-first (which for GitHub Actions/Azure/Bitbucket already
corresponds to declared run order), collects string values under common
"run a command" keys (`run`, `script`, `cmd`, `command`) that look like a
test-runner invocation, and -- for GitLab CI's `stages:` list, which is the
one common case where top-level key order does NOT reflect run order --
reorders by declared stage index first.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

import yaml

from nltest.matcher.nlp import tokenize
from nltest.security import is_within_repo, safe_read_text
from nltest.models import MatchResult, TestCase

CI_YAML_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    ".gitlab-ci.yaml",
    ".circleci/config.yml",
    ".circleci/config.yaml",
    "azure-pipelines.yml",
    "azure-pipelines.yaml",
    "bitbucket-pipelines.yml",
    "bitbucket-pipelines.yaml",
)

RUNNER_HINTS = (
    "pytest",
    "playwright",
    "cypress",
    "jest",
    "mocha",
    "mvn",
    "gradle",
    "testng",
    "junit",
    "npx",
    "npm test",
    "npm run test",
    "robot",
    "behave",
)

COMMAND_KEYS = {"run", "script", "cmd", "command"}

# Structural container keys that should never be used as a stage's display
# label (we want the job/workflow *name*, e.g. "smoke", not the list key that
# happened to contain it, e.g. "steps").
_CONTAINER_KEYS = {"jobs", "steps", "stages", "workflows", "pipelines", "default", "script"}


@dataclass
class OrderedStep:
    index: int
    """Position in the overall pipeline (lower runs first)."""
    source: str
    """Which CI file this step came from, for reporting."""
    stage: str
    """Best-effort label for this step (job/stage name), for reporting."""
    command: str
    tokens: set[str] = field(default_factory=set)


def _looks_like_test_command(cmd: str) -> bool:
    lower = cmd.lower()
    return any(hint in lower for hint in RUNNER_HINTS)


# Extracts the *selector* portion of a test-runner invocation -- the marker
# expression / grep pattern / group list that actually says which tests to
# run -- rather than tokenizing the whole command line. Tokenizing the whole
# line would pick up noise like "pytest"/"python"/"test" that's shared by
# nearly every step and swamps the real signal (e.g. "recording"/"smoke").
_GENERIC_SELECTOR_RES = (
    re.compile(r"-m\s+\"?([^\"\n]+)\"?"),  # pytest -m "recording and not slow"
    re.compile(r"-k\s+\"?([^\"\n]+)\"?"),  # pytest -k login
    re.compile(r"--grep[= ]\"?([^\"\n]+)\"?"),  # mocha/cypress-grep --grep recording
    re.compile(r"-g\s+\"?([^\"\n]+)\"?"),  # playwright -g recording
    re.compile(r"-Dgroups=([^\s]+)"),  # TestNG groups via Maven/Surefire
)
# `-Dtest=`/`--tests` reference `Class#method` or `Class.method` selectors --
# handled separately so we can prefer the method name (a much more specific
# signal) over the class name (which, like a file path, is often shared by
# several unrelated tests and would otherwise cause false stage matches).
_CLASS_METHOD_SELECTOR_RES = (
    re.compile(r"-Dtest=([^\s]+)"),
    re.compile(r"--tests\s+\"?([^\"\n]+)\"?"),
)


def _selector_tokens(command: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in _GENERIC_SELECTOR_RES:
        for match in pattern.findall(command):
            tokens.update(tokenize(match))

    for pattern in _CLASS_METHOD_SELECTOR_RES:
        for match in pattern.findall(command):
            for selector in match.split(","):
                selector = selector.strip()
                # "Class#method" (Maven/Surefire) or "Class.method" (Gradle):
                # prefer the trailing method name if there is one.
                part = re.split(r"[#.]", selector)[-1] if ("#" in selector or "." in selector) else selector
                tokens.update(tokenize(part))
    return tokens


def _test_intent_tokens(test: TestCase) -> set[str]:
    """Deliberately restricted to tags only (not name/description/file_path):
    tags are a curated, categorical vocabulary (recording/smoke/login/...)
    that lines up well with CI selector flags like `-m recording`, whereas
    matching against free-text test names causes false positives from
    ordinary shared English words (e.g. two unrelated tests both containing
    "...Correctly" or "render")."""
    return set(tokenize(" ".join(test.tags)))


def _collect_command_value(value, path: list[str], stage_name: str | None, steps: list[OrderedStep], source: str, counter: list[int]) -> None:
    commands = value if isinstance(value, list) else [value]
    for cmd in commands:
        if not isinstance(cmd, str):
            continue
        for line in cmd.splitlines():
            line = line.strip()
            if line and _looks_like_test_command(line):
                label = stage_name or next((p for p in reversed(path) if p not in _CONTAINER_KEYS), "")
                steps.append(
                    OrderedStep(
                        index=counter[0],
                        source=source,
                        stage=label,
                        command=line,
                        tokens=_selector_tokens(line) | set(tokenize(label)),
                    )
                )
                counter[0] += 1


def _walk(node, path: list[str], steps: list[OrderedStep], source: str, counter: list[int]) -> None:
    if isinstance(node, dict):
        stage_name = node.get("stage") if isinstance(node.get("stage"), str) else None
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            if key in COMMAND_KEYS:
                _collect_command_value(value, path, stage_name, steps, source, counter)
            else:
                _walk(value, path + [key], steps, source, counter)
    elif isinstance(node, list):
        for item in node:
            _walk(item, path, steps, source, counter)


def _gitlab_stage_rank(doc) -> dict[str, int]:
    stages = doc.get("stages") if isinstance(doc, dict) else None
    if isinstance(stages, list):
        return {str(s): i for i, s in enumerate(stages)}
    return {}


def load_order_rules(repo_root: str) -> list[OrderedStep]:
    """Parse every recognized CI YAML file in the repo into an ordered list of
    test-invocation steps. Steps from GitLab CI are re-sorted by its
    `stages:` list (if declared) since GitLab job order in the file doesn't
    necessarily reflect run order the way GitHub Actions/Azure/Bitbucket's
    nested step lists do."""
    all_steps: list[OrderedStep] = []
    counter = [0]
    for pattern in CI_YAML_GLOBS:
        for path in glob.glob(os.path.join(repo_root, pattern)):
            if not is_within_repo(repo_root, path):
                continue
            doc_text = safe_read_text(path, repo_root)
            if doc_text is None:
                continue
            try:
                doc = yaml.safe_load(doc_text)
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue

            rel_source = os.path.relpath(path, repo_root)
            steps: list[OrderedStep] = []
            _walk(doc, [], steps, rel_source, counter)

            stage_rank = _gitlab_stage_rank(doc)
            if stage_rank:
                steps.sort(key=lambda s: stage_rank.get(s.stage, len(stage_rank)))

            all_steps.extend(steps)
    return all_steps


def _rank_for(test: TestCase, rules: list[OrderedStep]) -> tuple[int, str | None]:
    """The earliest CI step whose command/job-name plausibly corresponds to
    this test (by file path substring or shared tag/name token), or
    (len(rules), None) if no step seems to correspond to it at all."""
    test_tokens = _test_intent_tokens(test)
    norm_path = test.file_path.replace("\\", "/")
    for rule in rules:
        if norm_path and norm_path in rule.command.replace("\\", "/"):
            return rule.index, rule.stage
        if test_tokens & rule.tokens:
            return rule.index, rule.stage
    return len(rules), None


def order_matches(matches: list[MatchResult], rules: list[OrderedStep]) -> tuple[list[MatchResult], dict[str, str]]:
    """Sort matches by which CI-pipeline step they best correspond to (earlier
    step runs first). Ties (including "no corresponding step") fall back to
    descending match score, then file path, for a stable, sensible order.

    Returns (ordered_matches, {test_id: stage_label}) for reporting purposes.
    """
    if not rules:
        return matches, {}

    ranked = []
    stage_labels: dict[str, str] = {}
    for m in matches:
        rank, stage = _rank_for(m.test, rules)
        if stage:
            stage_labels[m.test.id] = stage
        ranked.append((rank, -m.score, m.test.file_path, m.test.name, m))

    ranked.sort(key=lambda t: t[:4])
    return [t[4] for t in ranked], stage_labels


def group_by_stage(
    matches: list[MatchResult], stage_labels: dict[str, str]
) -> list[tuple[str | None, list[MatchResult]]]:
    """Split an already CI-ordered match list into consecutive (stage_label,
    matches) groups, so each stage can be executed as its own sequential
    batch -- preserving true run order across stages, even across different
    test frameworks within the same stage."""
    groups: list[tuple[str | None, list[MatchResult]]] = []
    current_label: str | None = "__unset__"  # sentinel, never a real label
    current: list[MatchResult] = []
    for m in matches:
        label = stage_labels.get(m.test.id)
        if label != current_label:
            if current:
                groups.append((current_label if current_label != "__unset__" else None, current))
            current = []
            current_label = label
        current.append(m)
    if current:
        groups.append((current_label if current_label != "__unset__" else None, current))
    return groups
