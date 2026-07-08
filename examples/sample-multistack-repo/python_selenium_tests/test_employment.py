"""Selenium (Python/pytest) tests for the employment records feature.

Demonstrates nltest's compound-scenario understanding:

    nltest run "test save employment after importing"

is parsed as two scenarios -- "importing" (prerequisite) and "save
employment" (main) -- resolved and run independently and in that order,
rather than fuzzy-matched as one bag of words.
"""

import os

import pytest


@pytest.mark.import_data
def test_import_employment_csv():
    """Bulk-importing an employment CSV file should create records for every row."""
    assert True


@pytest.mark.save
def test_save_new_employment_record():
    """Saving a new employment record via the form should persist it and show a success toast."""
    assert True


# This composite test performs BOTH steps in one go. It's what nltest falls
# back to for a query like "test save employment after importing" in a repo
# that *doesn't* have the standalone tests above -- and it demonstrates the
# `# step: <name>` + skip-env-var convention nltest recognizes so it can
# bypass the import step specifically when a user says they already did it
# manually, rather than re-running the whole composite test from scratch.
@pytest.mark.import_data
@pytest.mark.save
def test_import_and_save_employment_full_flow():
    """Full flow: import employment data via CSV, then save a new employment record."""
    # step: import (skippable via NLTEST_SKIP_IMPORT)
    if not os.environ.get("NLTEST_SKIP_IMPORT"):
        pass  # would call import_employment_csv() here
    # step: save
    assert True  # would call save_new_employment_record() here
