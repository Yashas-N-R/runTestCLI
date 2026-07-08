import json
import os

from nltest.cli import main

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample-multistack-repo")


def test_cli_index_runs_and_exits_zero(capsys):
    rc = main(["--repo", FIXTURE_REPO, "index"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Discovered tests" in out


def test_cli_match_runs_and_exits_zero(capsys):
    rc = main(["--repo", FIXTURE_REPO, "match", "test recording"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Matched tests" in out


def test_cli_list_tags_runs_and_exits_zero(capsys):
    rc = main(["--repo", FIXTURE_REPO, "list-tags"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "recording" in out


def test_cli_run_dry_run_writes_json_report(tmp_path, capsys):
    json_path = str(tmp_path / "report.json")
    rc = main(["--repo", FIXTURE_REPO, "run", "test recording", "--dry-run", "--json", json_path])
    assert rc == 0
    assert os.path.exists(json_path)
    with open(json_path) as fh:
        data = json.load(fh)
    assert data["query"] == "test recording"
    assert data["summary"]["total"] >= 12
    assert data["dry_run"] is True


def test_cli_run_no_matches_exits_nonzero(capsys):
    rc = main(["--repo", FIXTURE_REPO, "run", "the flux capacitor", "--dry-run"])
    assert rc == 1


def test_cli_run_compound_query_dry_run(tmp_path, capsys):
    """Compound query with dedicated cases for both parts should resolve
    without needing any interactive prompt (no stdin should be touched)."""
    json_path = str(tmp_path / "report.json")
    rc = main(
        [
            "--repo",
            FIXTURE_REPO,
            "run",
            "test save employment after importing",
            "--dry-run",
            "--json",
            json_path,
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 scenario(s)" in out
    assert "stage: prerequisite: importing" in out
    assert "stage: main: test save employment" in out
    with open(json_path) as fh:
        data = json.load(fh)
    names = {r["name"] for r in data["results"]}
    assert "test_import_employment_csv" in names
    assert "test_save_new_employment_record" in names
