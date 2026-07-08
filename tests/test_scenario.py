import os

import pytest

from nltest.config import NLTestConfig
from nltest.scanners import scan_repo
from nltest.scenario import resolve_scenario
from nltest.steps import extract_steps, find_step

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


@pytest.fixture(scope="module")
def all_tests():
    config = NLTestConfig.load(FIXTURE_REPO)
    return config, scan_repo(config)


def _match_names(cr):
    return sorted(m.test.name for m in cr.matches)


def test_compound_query_with_both_dedicated_cases_needs_no_prompt(all_tests):
    """When both a dedicated import test and a dedicated save test exist,
    nltest should resolve the compound scenario without asking anything."""
    config, tests = all_tests
    prompts = []
    plan = resolve_scenario(
        "test save employment after importing", tests, config, prompt=lambda m: prompts.append(m) or "", announce=lambda m: None
    )
    assert not prompts, "should not need to ask the user anything when dedicated cases exist"
    assert not plan.aborted
    assert plan.is_compound
    assert plan.clauses[0].clause.role == "prerequisite"
    assert "test_import_employment_csv" in _match_names(plan.clauses[0])
    assert plan.clauses[1].clause.role == "main"
    assert "test_save_new_employment_record" in _match_names(plan.clauses[1])


def test_missing_prerequisite_case_is_flagged_and_prompts_user(all_tests):
    config, tests = all_tests
    tests_without_import = [t for t in tests if "import" not in t.name.lower()]

    announcements = []
    plan = resolve_scenario(
        "test save employment after importing",
        tests_without_import,
        config,
        prompt=lambda m: "s",
        announce=announcements.append,
    )
    assert any("No test case found" in a or "No DEDICATED test case found" in a for a in announcements)
    assert plan.clauses[0].status == "skipped_manually"
    assert plan.clauses[1].status == "matched"
    # The final run plan should only include the "save" test(s), never an
    # import test (there are none left) and never silently invent one.
    assert all("import" not in m.test.name.lower() for m in plan.all_matches())


def test_user_can_provide_explicit_tag_for_missing_prerequisite(all_tests):
    config, tests = all_tests
    tests_without_import = [t for t in tests if "import" not in t.name.lower()]

    answers = iter(["t", "save"])  # choose "use a tag", then provide "save"
    plan = resolve_scenario(
        "test save employment after importing",
        tests_without_import,
        config,
        prompt=lambda m: next(answers),
        announce=lambda m: None,
    )
    assert plan.clauses[0].status == "matched"
    assert all("save" in t.tags for m in plan.clauses[0].matches for t in [m.test])


def test_user_can_abort_when_prerequisite_missing(all_tests):
    config, tests = all_tests
    tests_without_import = [t for t in tests if "import" not in t.name.lower()]

    plan = resolve_scenario(
        "test save employment after importing", tests_without_import, config, prompt=lambda m: "a", announce=lambda m: None
    )
    assert plan.aborted


def test_composite_only_case_is_flagged_as_not_dedicated(all_tests):
    """If the only test covering "importing" ALSO covers "save employment",
    it's not a dedicated case for either -- nltest should say so rather than
    silently treating it as a normal match for both."""
    config, tests = all_tests
    composite_only = [
        t for t in tests if t.name not in ("test_import_employment_csv", "test_save_new_employment_record")
    ]

    announcements = []
    plan = resolve_scenario(
        "test save employment after importing",
        composite_only,
        config,
        prompt=lambda m: "s",
        announce=announcements.append,
    )
    assert any("combined case" in a for a in announcements)
    assert plan.clauses[0].status == "skipped_manually"
    # The composite test should still run for the "main" clause, with the
    # import step bypassed via its detected skip-env-var convention.
    main_cr = plan.clauses[1]
    assert "test_import_and_save_employment_full_flow" in _match_names(main_cr)
    assert main_cr.env_overrides.get("NLTEST_SKIP_IMPORT") == "1"


def test_composite_only_case_can_be_run_as_is(all_tests):
    config, tests = all_tests
    composite_only = [
        t for t in tests if t.name not in ("test_import_employment_csv", "test_save_new_employment_record")
    ]
    plan = resolve_scenario(
        "test save employment after importing", composite_only, config, prompt=lambda m: "u", announce=lambda m: None
    )
    assert not plan.aborted
    assert plan.clauses[0].env_overrides == {}
    assert "test_import_and_save_employment_full_flow" in _match_names(plan.clauses[0])


def test_extract_steps_finds_markers_and_skip_env_var():
    body = (
        "def test_x():\n"
        "    # step: import (skippable via NLTEST_SKIP_IMPORT)\n"
        '    if not os.environ.get("NLTEST_SKIP_IMPORT"):\n'
        "        do_import()\n"
        "    # step: save\n"
        "    do_save()\n"
    )
    steps = extract_steps(body)
    names = {s.name for s in steps}
    assert names == {"import", "save"}
    import_step = next(s for s in steps if s.name == "import")
    assert import_step.skip_env_var == "NLTEST_SKIP_IMPORT"
    save_step = next(s for s in steps if s.name == "save")
    assert save_step.skip_env_var is None


def test_find_step_loose_matches_by_substring():
    body = "# step: import\ndo_import()\n"
    assert find_step(body, "importing").name == "import"
    assert find_step(body, "checkout") is None
