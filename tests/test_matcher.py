import os

import pytest

from nltest.config import NLTestConfig
from nltest.matcher import match_query
from nltest.scanners import scan_repo

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


@pytest.fixture(scope="module")
def all_tests():
    config = NLTestConfig.load(FIXTURE_REPO)
    return config, scan_repo(config)


def test_query_test_recording_matches_only_recording_tests(all_tests):
    config, tests = all_tests
    matches = match_query("test recording", tests, config)
    names = {m.test.name for m in matches}

    assert len(matches) >= 12
    for m in matches:
        if any(r.startswith("feature_map:") for r in m.matched_on):
            continue  # deliberately has no "recording" anywhere -- that's the point of feature_map
        assert any("recording" in field for field in (m.test.searchable_text().lower(), m.test.body.lower()))

    # Weak, file-level signals (a shared comment/javadoc/page-object mentioning
    # "recording" elsewhere in the same file) can pull in an unrelated
    # co-located test (e.g. a login test living in RecordingUiTest.java) --
    # that's the intentional "search everything in the file" trade-off. Only
    # assert that STRONG signals (the test's own tag/name/description/body)
    # never falsely claim an unrelated login/checkout test is about recording.
    strong_matches = [
        m for m in matches if any(r.split(":", 1)[0] in ("tag", "name", "description", "body") for r in m.matched_on)
    ]
    strong_names = {m.test.name.lower() for m in strong_matches}
    assert not any("login" in n for n in strong_names)
    assert not any("checkout" in n for n in strong_names)


def test_body_content_match_finds_untitled_recording_test(all_tests):
    """A test whose title/tags/docstring never say 'recording' but whose code
    does (e.g. `cy.get('[data-testid=recording-toggle-button]')`) should still
    be found via body-content matching."""
    config, tests = all_tests
    matches = match_query("test recording", tests, config)
    names = {m.test.name for m in matches}
    assert "renders the correct button icon" in names


def test_feature_map_finds_internally_codenamed_test(all_tests):
    """A test that only ever refers to an internal codename ("beacon") should
    still be found via the .nltestrc.yml feature_map override."""
    config, tests = all_tests
    matches = match_query("test recording", tests, config)
    names = {m.test.name for m in matches}
    assert "test_beacon_pipeline_emits_heartbeat" in names
    beacon_match = next(m for m in matches if m.test.name == "test_beacon_pipeline_emits_heartbeat")
    assert any(r.startswith("feature_map:") for r in beacon_match.matched_on)


def test_dependency_auto_included_for_testng(all_tests):
    """A TestNG test with dependsOnMethods should pull in its dependency even
    though the dependency ("startRecordingReturns201") isn't independently
    matched by this query -- the query only matches the downstream test
    ("cleanupTempStorageAfterEachRun"), which never mentions "recording"."""
    config, tests = all_tests
    matches = match_query("cleanup temp storage", tests, config)
    names = {m.test.name for m in matches}
    assert names == {"cleanupTempStorageAfterEachRun", "startRecordingReturns201"}
    dep_match = next(m for m in matches if m.test.name == "startRecordingReturns201")
    assert any(r.startswith("dependency-of:") for r in dep_match.matched_on)


def test_dependency_auto_included_for_pytest_dependency_marker(all_tests):
    """pytest-dependency's `depends=[...]` should pull in the named setup test."""
    config, tests = all_tests
    matches = match_query("share button dialog", tests, config)
    names = {m.test.name for m in matches}
    assert "test_share_button_opens_dialog" in names
    assert "test_recording_can_be_started_for_share_test" in names


def test_query_matches_across_every_stack(all_tests):
    config, tests = all_tests
    matches = match_query("test recording", tests, config)
    frameworks = {m.test.framework.value for m in matches}
    assert "pytest" in frameworks
    assert "playwright-python" in frameworks
    assert "playwright-js" in frameworks
    assert "cypress" in frameworks
    assert "junit" in frameworks
    assert "testng" in frameworks


def test_query_login_matches_login_tests_only(all_tests):
    config, tests = all_tests
    matches = match_query("run login tests", tests, config)
    names = {m.test.name.lower() for m in matches}
    assert any("login" in n for n in names)
    assert not any("recording" in n for n in names)


def test_unrelated_query_returns_no_matches(all_tests):
    config, tests = all_tests
    matches = match_query("test the flux capacitor", tests, config)
    assert matches == []


def test_synonym_expansion_matches_record_variants(all_tests):
    config, tests = all_tests
    matches = match_query("capture screen recorder", tests, config)
    assert len(matches) > 0
