import os

import pytest

from nltest.ci_order import group_by_stage, load_order_rules, order_matches
from nltest.config import NLTestConfig
from nltest.matcher import match_query
from nltest.scanners import scan_repo

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


@pytest.fixture(scope="module")
def all_tests():
    config = NLTestConfig.load(FIXTURE_REPO)
    return config, scan_repo(config)


def test_load_order_rules_finds_github_actions_steps(all_tests):
    config, _ = all_tests
    rules = load_order_rules(config.repo_root)
    assert len(rules) >= 8
    # Declared job order in .github/workflows/e2e-tests.yml: smoke, login,
    # recording, checkout -- verify stage labels appear in that relative order.
    stages_in_order = []
    for r in rules:
        if not stages_in_order or stages_in_order[-1] != r.stage:
            stages_in_order.append(r.stage)
    assert stages_in_order == ["smoke", "login", "recording", "checkout"]


def test_order_matches_places_smoke_tagged_recording_test_before_general_recording_stage(all_tests):
    config, tests = all_tests
    rules = load_order_rules(config.repo_root)
    matches = match_query("test recording", tests, config)
    ordered, stage_labels = order_matches(matches, rules)

    # test_stop_recording_saves_file is tagged both "recording" and "smoke" --
    # it should be staged under "smoke" (which runs first), not "recording".
    smoke_tagged = next(m for m in ordered if m.test.name == "test_stop_recording_saves_file")
    assert stage_labels[smoke_tagged.test.id] == "smoke"

    # A plain recording test (no smoke tag) should land in the "recording" stage.
    plain_recording = next(m for m in ordered if m.test.name == "startRecordingReturns201")
    assert stage_labels[plain_recording.test.id] == "recording"

    # Stage order in the resulting list should be non-decreasing (smoke tests
    # never appear after recording/checkout tests).
    stage_rank = {"smoke": 0, "login": 1, "recording": 2, "checkout": 3}
    seen_ranks = [stage_rank[stage_labels[m.test.id]] for m in ordered if m.test.id in stage_labels]
    assert seen_ranks == sorted(seen_ranks)


def test_order_matches_assigns_checkout_test_to_checkout_stage(all_tests):
    config, tests = all_tests
    rules = load_order_rules(config.repo_root)
    matches = match_query("checkout", tests, config)
    ordered, stage_labels = order_matches(matches, rules)
    checkout_test = next(m for m in ordered if m.test.name == "createOrderReturns200")
    assert stage_labels[checkout_test.test.id] == "checkout"


def test_group_by_stage_produces_consecutive_ordered_groups(all_tests):
    config, tests = all_tests
    rules = load_order_rules(config.repo_root)
    matches = match_query("test recording", tests, config)
    ordered, stage_labels = order_matches(matches, rules)
    groups = group_by_stage(ordered, stage_labels)

    labels = [label for label, _ in groups]
    # No duplicate/non-consecutive stage labels (each stage should appear as
    # a single contiguous group, not interleaved).
    assert len(labels) == len(set(labels))
    assert sum(len(g) for _, g in groups) == len(ordered)
