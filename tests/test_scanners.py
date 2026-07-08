import os

import pytest

from nltest.config import NLTestConfig
from nltest.models import Framework, Stack
from nltest.scanners import scan_repo
from nltest.scanners.java_scanner import scan_java
from nltest.scanners.js_scanner import scan_js
from nltest.scanners.python_scanner import scan_python

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


@pytest.fixture(scope="module")
def config() -> NLTestConfig:
    return NLTestConfig.load(FIXTURE_REPO)


def test_scan_repo_finds_all_stacks(config):
    tests = scan_repo(config)
    frameworks = {t.framework for t in tests}
    assert Framework.PYTEST in frameworks
    assert Framework.PLAYWRIGHT_PY in frameworks
    assert Framework.PLAYWRIGHT_JS in frameworks
    assert Framework.CYPRESS in frameworks
    assert Framework.JUNIT in frameworks
    assert Framework.TESTNG in frameworks
    assert len(tests) >= 18


def test_python_scanner_extracts_pytest_markers_as_tags(config):
    tests = scan_python(config)
    by_name = {t.name: t for t in tests}
    assert "recording" in by_name["test_start_recording_shows_indicator"].tags
    assert by_name["test_start_recording_shows_indicator"].stack == Stack.SELENIUM
    assert "recording" in by_name["test_recorded_video_plays_back_correctly"].tags
    assert by_name["test_recorded_video_plays_back_correctly"].stack == Stack.PLAYWRIGHT


def test_python_scanner_extracts_comment_tags(config):
    tests = scan_python(config)
    by_name = {t.name: t for t in tests}
    assert "playback" in by_name["test_recorded_video_plays_back_correctly"].tags


def test_js_scanner_extracts_hashtag_and_comment_tags(config):
    tests = scan_js(config)
    by_name = {t.name: t for t in tests}
    countdown = by_name["shows a countdown before recording starts @recording"]
    assert "recording" in countdown.tags
    assert countdown.framework == Framework.CYPRESS

    pausing = by_name["allows pausing and resuming an active recording"]
    assert "recording" in pausing.tags

    pw = [t for t in tests if t.framework == Framework.PLAYWRIGHT_JS]
    assert any("recording" in t.tags for t in pw)


def test_java_scanner_extracts_junit_tags_and_testng_groups(config):
    tests = scan_java(config)
    by_name = {t.name: t for t in tests}

    junit_test = by_name["recordingButtonTogglesState"]
    assert junit_test.framework == Framework.JUNIT
    assert junit_test.stack == Stack.SELENIUM
    assert "recording" in junit_test.tags

    testng_test = by_name["startRecordingReturns201"]
    assert testng_test.framework == Framework.TESTNG
    assert testng_test.stack == Stack.REST_ASSURED
    assert "recording" in testng_test.tags
    assert "api" in testng_test.tags
