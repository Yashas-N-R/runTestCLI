"""Resolves a (possibly compound) natural-language query into a concrete,
ordered execution plan: which test(s) to run for each part of the request,
in what order, and -- critically -- what to do when part of the request has
no corresponding test case at all.

This is what makes `nltest run "test save employment after importing"`
understand the request rather than just fuzzy-matching keywords: it
decomposes the query into "importing" (a prerequisite) and "save employment"
(the actual thing being tested), resolves each independently, and flags any
part that doesn't correspond to a real test case -- instead of silently
guessing and running whatever scores highest on the combined bag of words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from nltest.config import NLTestConfig
from nltest.matcher import score_matches
from nltest.matcher.intent import Clause, parse_query_into_clauses
from nltest.models import MatchResult, TestCase
from nltest.steps import find_step

PromptFn = Callable[[str], str]
AnnounceFn = Callable[[str], None]


@dataclass
class ClauseResolution:
    clause: Clause
    matches: list[MatchResult] = field(default_factory=list)
    status: str = "matched"
    """"matched" | "skipped_manually" | "aborted" | "unresolved" (no match,
    and nothing more productive to ask -- e.g. a single-clause query)."""
    note: str = ""
    env_overrides: dict[str, str] = field(default_factory=dict)
    """Environment variables to set when running `matches`, used to skip a
    step inside a composite test that also covers an already-satisfied
    (skipped) clause -- see `steps.py`."""


@dataclass
class ScenarioPlan:
    query: str
    clauses: list[ClauseResolution] = field(default_factory=list)
    aborted: bool = False

    @property
    def is_compound(self) -> bool:
        return len(self.clauses) > 1

    def runnable_clauses(self) -> list[ClauseResolution]:
        return [cr for cr in self.clauses if cr.status == "matched" and cr.matches]

    def all_matches(self) -> list[MatchResult]:
        """Every match to run, in clause (dependency) order, de-duplicated."""
        seen: set[str] = set()
        ordered: list[MatchResult] = []
        for cr in self.runnable_clauses():
            for m in cr.matches:
                if m.test.id in seen:
                    continue
                seen.add(m.test.id)
                ordered.append(m)
        return ordered


def _default_prompt(message: str) -> str:
    return input(message)


def _default_announce(message: str) -> None:
    print(message)


def _prompt_for_clause(
    clause: Clause,
    tests: list[TestCase],
    prompt: PromptFn,
    announce: AnnounceFn,
    extra_option: str = "",
) -> tuple[str, list[MatchResult]]:
    """Ask the user how to handle a clause that has no *dedicated* test case,
    returning (status, matches)."""
    answer = (
        prompt(
            f'  How should nltest handle "{clause.text}"?\n'
            "    [s] I already did this manually -- skip it\n"
            "    [t] Use a specific tag or exact test name for this step\n"
            f"{extra_option}"
            "    [a] Abort\n"
            "  > "
        )
        .strip()
        .lower()
    )

    if answer.startswith("t"):
        selector = prompt("  Enter a tag or exact test name to use: ").strip()
        selected = [t for t in tests if selector in t.tags or selector in (t.name, t.id)]
        if selected:
            return "matched", [
                MatchResult(test=t, score=1.0, matched_on=[f"manual-selection:{selector}"]) for t in selected
            ]
        announce(f'  No test found matching "{selector}" -- treating "{clause.text}" as skipped.')
        return "skipped_manually", []
    if answer.startswith("s"):
        return "skipped_manually", []
    if extra_option and answer.startswith("u"):
        return "use_combined", []
    return "aborted", []


def resolve_scenario(
    query: str,
    tests: list[TestCase],
    config: NLTestConfig,
    prompt: PromptFn = _default_prompt,
    announce: AnnounceFn = _default_announce,
) -> ScenarioPlan:
    """Parse `query` into clauses and resolve each one against `tests`,
    interactively asking (via `prompt`) how to handle any clause with no
    matching test case -- including the case where a clause only shows up
    as part of a combined/composite test that also covers another clause,
    rather than having a dedicated test case of its own.
    `prompt`/`announce` are injectable so callers (the CLI, or tests) can
    control I/O without touching stdin/stdout directly.
    """
    clauses = parse_query_into_clauses(query)
    plan = ScenarioPlan(query=query)

    raw_matches: dict[int, list[MatchResult]] = {
        i: score_matches(clause.text, tests, config) for i, clause in enumerate(clauses)
    }
    # test_id -> {clause_idx: MatchResult}, for cross-clause lookups below.
    by_test: dict[str, dict[int, MatchResult]] = {}
    for idx, matches in raw_matches.items():
        for m in matches:
            by_test.setdefault(m.test.id, {})[idx] = m

    clause_status: list[str | None] = [None] * len(clauses)

    def shared_with_another_clause(clause_idx: int, test_id: str) -> bool:
        """A test only counts as "shared" (i.e. a composite covering more
        than one clause) if it has a strong (tag-level) match for some OTHER
        *still-pending* clause too -- not just any incidental overlap (e.g.
        two sibling tests in the same file both mentioning "employment" in
        their file_path/description). Clauses already resolved as
        "skipped_manually" don't count: once the user has said that part is
        already done, the composite effectively "belongs" to whichever
        clause is left, so a later clause shouldn't be re-flagged over it."""
        for other_idx, m in by_test.get(test_id, {}).items():
            if other_idx == clause_idx or clause_status[other_idx] == "skipped_manually":
                continue
            if any(reason.startswith("tag:") or reason.startswith("manual-selection:") for reason in m.matched_on):
                return True
        return False

    skipped_clauses: list[Clause] = []

    for idx, clause in enumerate(clauses):
        matches = raw_matches[idx]
        dedicated = [m for m in matches if not shared_with_another_clause(idx, m.test.id)]
        cr = ClauseResolution(clause=clause, matches=matches)

        if dedicated or len(clauses) == 1:
            # Either a genuinely dedicated case exists, or this is a simple
            # single-clause query -- use whatever score_matches found as-is
            # (including "nothing at all", which just falls through to the
            # caller's normal "nothing matched" handling for simple queries).
            if not matches and len(clauses) > 1:
                label = "prerequisite step" if clause.role == "prerequisite" else "scenario"
                announce(f'No test case found for the {label}: "{clause.text}".')
                status, resolved = _prompt_for_clause(clause, tests, prompt, announce)
                if status == "aborted":
                    cr.status = "aborted"
                    plan.aborted = True
                    plan.clauses.append(cr)
                    break
                cr.status = status
                cr.matches = resolved
                if status == "skipped_manually":
                    skipped_clauses.append(clause)
            elif not matches:
                cr.status = "unresolved"
            clause_status[idx] = cr.status
            plan.clauses.append(cr)
            continue

        # Every match for this clause is shared with another clause -- i.e.
        # there's no test dedicated to JUST this step, only a combined case
        # that also covers something else. Flag it explicitly rather than
        # silently treating the combined case as if it were a clean match.
        combined_names = ", ".join(sorted({m.test.name for m in matches}))
        announce(
            f'No DEDICATED test case found for the {"prerequisite step" if clause.role == "prerequisite" else "scenario"}: '
            f'"{clause.text}" -- it only appears as part of a combined case ({combined_names}) that also covers '
            "another part of this request."
        )
        status, resolved = _prompt_for_clause(
            clause, tests, prompt, announce, extra_option="    [u] Use the combined case as-is (run it in full)\n"
        )
        if status == "aborted":
            cr.status = "aborted"
            plan.aborted = True
            plan.clauses.append(cr)
            break
        if status == "use_combined":
            cr.status = "matched"  # keep `matches` (the combined case) unchanged
        else:
            cr.status = status
            cr.matches = resolved
            if status == "skipped_manually":
                skipped_clauses.append(clause)
        clause_status[idx] = cr.status
        plan.clauses.append(cr)

    if plan.aborted or not skipped_clauses:
        return plan

    # A clause was skipped manually. If the test(s) matched for a REMAINING
    # clause are actually composite tests that also perform the skipped
    # step, try to bypass just that part via a detected skip-env-var
    # convention -- otherwise, warn rather than silently running it in full.
    for cr in plan.clauses:
        if cr.status != "matched":
            continue
        for m in cr.matches:
            for skipped in skipped_clauses:
                step = find_step(m.test.body, skipped.text)
                if step is None:
                    continue
                if step.skip_env_var:
                    cr.env_overrides[step.skip_env_var] = "1"
                    announce(
                        f'  "{m.test.name}" also performs the "{skipped.text}" step you skipped -- '
                        f"running it with {step.skip_env_var}=1 to bypass that part."
                    )
                else:
                    announce(
                        f'  Warning: "{m.test.name}" is the case covering "{cr.clause.text}", but it also '
                        f'performs the "{skipped.text}" step you said was already done manually. nltest can\'t '
                        "isolate that step at runtime (no skip convention detected in this test), so it will "
                        "run in full."
                    )

    return plan
