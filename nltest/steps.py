"""Detects named steps within a single test's body (via a `# step: <name>` /
`// step: <name>` comment convention) and any environment-variable a test
reads to make that step conditionally skippable.

Most test frameworks execute a test method/function atomically -- there's no
generic way to "run only half" of one. But teams that write composite tests
(e.g. "import data, then save a new record") sometimes already guard a
section behind an environment variable so CI can skip slow/already-satisfied
setup. This lets nltest recognize that convention and, when a user says a
prerequisite step was already done manually, pass the matching env var when
invoking a composite test that still needs to run for the remaining step --
rather than just guessing or silently running the whole thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STEP_MARKER_RE = re.compile(r"(?:#|//|\*)\s*step:\s*([\w-]+)", re.IGNORECASE)

_ENV_READ_RES = (
    re.compile(r"os\.environ\.get\(\s*[\"']([A-Z0-9_]+)[\"']"),
    re.compile(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']"),
    re.compile(r"process\.env\.([A-Z0-9_]+)"),
    re.compile(r"process\.env\[[\"']([A-Z0-9_]+)[\"']\]"),
    re.compile(r"System\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']"),
)

_LOOKAHEAD_LINES = 4


@dataclass
class StepInfo:
    name: str
    """Lowercased step name from the `# step: <name>` marker, e.g. "import"."""

    skip_env_var: str | None = None
    """Environment variable this step's code appears to check to decide
    whether to run (best-effort: the first env var read within a few lines
    of the step marker), or None if no such convention was detected."""


def extract_steps(body: str) -> list[StepInfo]:
    """Find every `# step: <name>` marker in `body` and, best-effort, the
    environment variable used to make that step conditionally skippable."""
    if not body:
        return []
    lines = body.splitlines()
    steps: list[StepInfo] = []
    for i, line in enumerate(lines):
        m = STEP_MARKER_RE.search(line)
        if not m:
            continue
        name = m.group(1).lower()
        skip_env_var = None
        for nearby in lines[i : i + _LOOKAHEAD_LINES]:
            for env_re in _ENV_READ_RES:
                env_match = env_re.search(nearby)
                if env_match:
                    skip_env_var = env_match.group(1)
                    break
            if skip_env_var:
                break
        steps.append(StepInfo(name=name, skip_env_var=skip_env_var))
    return steps


def find_step(body: str, step_name_hint: str) -> StepInfo | None:
    """Find a step whose name is contained in (or contains) `step_name_hint`
    (case-insensitive, loose match since the user's wording won't exactly
    match the marker name)."""
    hint = step_name_hint.lower()
    for step in extract_steps(body):
        if step.name in hint or hint in step.name:
            return step
    return None
