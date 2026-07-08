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
