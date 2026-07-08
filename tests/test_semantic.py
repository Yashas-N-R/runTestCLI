import os

import pytest

from nltest.config import NLTestConfig
from nltest.matcher import semantic
from nltest.matcher import score_matches
from nltest.scanners import scan_repo

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


@pytest.fixture(scope="module")
def all_tests():
    config = NLTestConfig.load(FIXTURE_REPO)
    return config, scan_repo(config)


def test_semantic_model_is_available_in_this_environment():
    # sentence-transformers is installed as a dev/test dependency; this
    # confirms the happy path actually activates rather than silently no-op.
    assert semantic.is_available()


PARAPHRASED_IMPORT_QUERY = "ingest a batch of new hires from an external file"
"""Deliberately shares almost no literal tokens with "import"/"csv"/
"employment" (unlike, say, "bulk upload a csv of employee data", which
would lexically match on "csv" alone) -- isolates the semantic contribution."""


def test_paraphrased_query_with_no_lexical_overlap_still_matches(all_tests):
    """The core promise: understanding a totally different phrasing of
    "import" means the same feature, WITHOUT a hardcoded synonym dictionary
    ever having been told "ingest" or "hires" relate to "import"/"employment"."""
    config, tests = all_tests
    assert "import" not in config.synonyms, "this test is only meaningful without a hardcoded import synonym"

    matches = score_matches(PARAPHRASED_IMPORT_QUERY, tests, config)
    names = {m.test.name for m in matches}
    assert "test_import_employment_csv" in names
    top = next(m for m in matches if m.test.name == "test_import_employment_csv")
    assert any(r.startswith("semantic:") for r in top.matched_on)


def test_semantic_matching_can_be_disabled_via_config(all_tests):
    config, tests = all_tests
    disabled = NLTestConfig(repo_root=config.repo_root, semantic_matching=False)
    matches = score_matches(PARAPHRASED_IMPORT_QUERY, tests, disabled)
    # Without semantic matching AND without a hardcoded synonym dictionary,
    # this differently-worded query should find nothing at all -- demonstrating
    # what semantic matching actually buys you over lexical matching alone.
    assert matches == []


def test_degrades_gracefully_when_dependency_unavailable(monkeypatch, all_tests):
    """Simulate `sentence-transformers` not being installed: matching should
    fall back to lexical/tag/fuzzy matching without raising."""
    config, tests = all_tests
    monkeypatch.setattr(semantic, "_load_model", lambda: None)
    semantic._load_model.cache_clear = lambda: None  # not an lru_cache anymore after monkeypatch; no-op is fine

    assert semantic.embed(["anything"]) is None
    assert semantic.similarities("anything", None) is None

    # score_matches should still work end-to-end (falls back to lexical only).
    matches = score_matches("test recording", tests, config)
    assert any(m.test.name == "test_start_recording_shows_indicator" for m in matches)


def test_semantic_text_excludes_file_path():
    from nltest.models import Framework, TestCase

    t = TestCase(
        id="x",
        name="test_thing",
        file_path="some/deeply/nested/path/test_thing.py",
        framework=Framework.PYTEST,
        tags=["recording"],
        description="does a thing",
    )
    assert "nested" not in t.semantic_text()
    assert "recording" in t.semantic_text()
