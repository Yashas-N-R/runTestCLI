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
        assert "recording" in m.test.tags or "recording" in m.test.name.lower() or "recording" in m.test.description.lower()

    assert not any("login" in n.lower() for n in names)
    assert not any("checkout" in n.lower() for n in names)


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
