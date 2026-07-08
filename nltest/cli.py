"""nltest CLI: run automation test suites using plain English commands."""

from __future__ import annotations

import argparse
import sys
import time

from rich.console import Console

from nltest.ci_order import group_by_stage, load_order_rules, order_matches
from nltest.config import NLTestConfig
from nltest.matcher import augment_matches, match_query, score_matches
from nltest.models import RunReport
from nltest.report import print_console_report, print_matches_preview, write_html_report, write_json_report
from nltest.runners import run_matches
from nltest.scanners import scan_repo
from nltest.scenario import resolve_scenario

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nltest",
        description="Run automation test suites (Selenium, Playwright, Cypress, REST Assured, JUnit, TestNG, "
        "pytest, Jest, Mocha, ...) using plain English commands.",
    )
    parser.add_argument("--repo", default=".", help="Path to the test automation repo (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Match and execute tests for a natural-language query")
    run_p.add_argument("query", help='e.g. "test recording" or "run login and checkout tests"')
    run_p.add_argument("--dry-run", action="store_true", help="Show which tests/commands would run, without executing them")
    run_p.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt before running")
    run_p.add_argument("--json", dest="json_out", help="Write a JSON report to this path")
    run_p.add_argument("--html", dest="html_out", help="Write an HTML report to this path")
    run_p.add_argument("--extra-args", default="", help="Extra args forwarded verbatim to the underlying test runner")
    run_p.add_argument("--threshold", type=float, default=None, help="Override the match score threshold (0-1)")
    run_p.add_argument("--limit", type=int, default=None, help="Max number of matched tests to run")
    run_p.add_argument(
        "--exact",
        action="store_true",
        help="Run only the exact matched tests (by node ID/method) instead of the default safe mode, "
        "which runs whole files/classes so shared setup, fixtures, and test dependencies still execute",
    )
    run_p.add_argument(
        "--no-deps",
        action="store_true",
        help="Don't auto-include tests that a matched test explicitly depends on "
        "(TestNG dependsOnMethods, pytest-dependency, # depends-on: comments)",
    )
    run_p.add_argument(
        "--no-ci-order",
        action="store_true",
        help="Don't reorder/stage execution based on the repo's CI pipeline YAML "
        "(.github/workflows, .gitlab-ci.yml, etc.) -- run in match-score order instead",
    )

    index_p = sub.add_parser("index", help="Scan the repo and list all discovered test cases")
    index_p.add_argument("--tag", default=None, help="Only show tests with this tag")
    index_p.add_argument("--framework", default=None, help="Only show tests for this framework")

    tags_p = sub.add_parser("list-tags", help="List all tags/markers/groups discovered across the repo")

    match_p = sub.add_parser("match", help="Preview which tests a query would match, without running anything")
    match_p.add_argument("query", help='e.g. "test recording"')
    match_p.add_argument("--threshold", type=float, default=None)

    return parser


def cmd_index(args: argparse.Namespace) -> int:
    config = NLTestConfig.load(args.repo)
    tests = scan_repo(config)
    if args.tag:
        tests = [t for t in tests if args.tag in t.tags]
    if args.framework:
        tests = [t for t in tests if t.framework.value == args.framework]

    from rich.table import Table

    table = Table(title=f"Discovered tests in {config.repo_root} ({len(tests)})")
    table.add_column("Name")
    table.add_column("Framework")
    table.add_column("Stack")
    table.add_column("File")
    table.add_column("Tags")
    for t in sorted(tests, key=lambda t: (t.framework.value, t.file_path, t.name)):
        table.add_row(t.name, t.framework.value, t.stack.value, f"{t.file_path}:{t.line or ''}", ", ".join(t.tags))
    console.print(table)
    if not tests:
        console.print(
            "[yellow]No tests found.[/yellow] Supported: pytest/Selenium/Playwright(py), "
            "Playwright(JS/TS)/Cypress/Jest/Mocha, JUnit/TestNG (Selenium/REST Assured)."
        )
    return 0


def cmd_list_tags(args: argparse.Namespace) -> int:
    config = NLTestConfig.load(args.repo)
    tests = scan_repo(config)
    tag_counts: dict[str, int] = {}
    for t in tests:
        for tag in t.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    from rich.table import Table

    table = Table(title="Tags discovered in repo")
    table.add_column("Tag")
    table.add_column("Count")
    for tag, count in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
        table.add_row(tag, str(count))
    console.print(table)
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    config = NLTestConfig.load(args.repo)
    if args.threshold is not None:
        config.match_threshold = args.threshold
    tests = scan_repo(config)
    matches = match_query(args.query, tests, config)
    report = RunReport(query=args.query, matches=matches, dry_run=True)
    print_matches_preview(report, console)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = NLTestConfig.load(args.repo)
    if args.threshold is not None:
        config.match_threshold = args.threshold
    if args.no_deps:
        config.include_dependencies = False
    if args.no_ci_order:
        config.respect_ci_order = False

    console.print(f'[bold]Scanning repo:[/bold] {config.repo_root}')
    tests = scan_repo(config)
    console.print(f"[bold]Discovered {len(tests)} test case(s) across all supported frameworks.[/bold]")

    # Understand the query's actual intent first: is this one scenario, or a
    # compound request like "test save employment after importing" that
    # names two distinct scenarios with an explicit run-order between them?
    # Compound requests are resolved clause-by-clause (each independently
    # matched against the repo), with any clause that has no corresponding
    # test case flagged and interactively resolved -- rather than blending
    # every word into one keyword-soup query.
    plan = resolve_scenario(args.query, tests, config, prompt=console.input, announce=console.print)

    if plan.aborted:
        console.print("[red]Aborted.[/red]")
        return 1

    # Execution batches: (label, matches, env_overrides), run strictly in
    # this order. For a compound query, the order comes directly from the
    # user's own wording (prerequisite before main) and takes precedence
    # over CI-pipeline staging. For a simple query, fall back to the
    # existing single-scenario flow: dependency/feature_map augmentation,
    # optional --limit, and (if configured) CI-pipeline-order staging.
    stage_labels: dict[str, str] = {}
    ci_rules: list = []

    if plan.is_compound:
        for cr in plan.runnable_clauses():
            cr.matches = augment_matches(cr.clause.text, cr.matches, tests, config)
        batches = [
            (f"{cr.clause.role}: {cr.clause.text}", cr.matches, cr.env_overrides) for cr in plan.runnable_clauses()
        ]
        matches = plan.all_matches()
        console.print(
            f'[dim]Understood "{args.query}" as {len(plan.clauses)} scenario(s), run in the order you specified.[/dim]'
        )
    else:
        matches = plan.clauses[0].matches if plan.clauses else []
        if args.limit:
            matches = matches[: args.limit]
        matches = augment_matches(args.query, matches, tests, config)

        ci_rules = load_order_rules(config.repo_root) if config.respect_ci_order else []
        if ci_rules:
            matches, stage_labels = order_matches(matches, ci_rules)
        batches = [(label, group, {}) for label, group in group_by_stage(matches, stage_labels)]

    dependency_count = sum(1 for m in matches if any(r.startswith("dependency-of:") for r in m.matched_on))

    report = RunReport(query=args.query, matches=matches, dry_run=args.dry_run)
    print_matches_preview(report, console, stage_labels=stage_labels)
    if dependency_count:
        console.print(
            f"[dim]({dependency_count} of the above were auto-included because a matched test depends on them; "
            "pass --no-deps to disable)[/dim]"
        )
    if not args.exact:
        console.print(
            "[dim]Running in safe mode: whole files/classes will execute (not just the matched tests), "
            "so shared setup/state isn't skipped. Pass --exact to run only the matched tests.[/dim]"
        )
    if stage_labels:
        ci_sources = sorted({r.source for r in ci_rules})
        console.print(
            f"[dim]Ordering execution to match the CI pipeline stages found in {', '.join(ci_sources)} "
            "(e.g. smoke before regression). Pass --no-ci-order to run in match-score order instead.[/dim]"
        )

    if not matches:
        console.print("[yellow]Nothing to run.[/yellow] Try `nltest index` to see available tests, "
                       "or `nltest list-tags` to see recognized tags. If the feature isn't referenced anywhere "
                       "in test titles, tags, docstrings, or code, add a `feature_map` entry to .nltestrc.yml.")
        return 1

    if not args.dry_run and not args.yes:
        answer = console.input(f"\nRun these {len(matches)} test(s)? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            console.print("Aborted.")
            return 1

    results = []
    for stage_label, stage_matches, stage_env in batches:
        if not stage_matches:
            continue
        if stage_label:
            console.print(f"\n[bold cyan]-- stage: {stage_label} --[/bold cyan]")
        results.extend(
            run_matches(
                stage_matches,
                config.repo_root,
                dry_run=args.dry_run,
                extra_args=args.extra_args,
                exact=args.exact,
                env=stage_env or None,
            )
        )
    report.results = results
    report.finished_at = time.time()

    print_console_report(report, console)

    if args.json_out:
        write_json_report(report, args.json_out)
        console.print(f"[dim]JSON report written to {args.json_out}[/dim]")
    if args.html_out:
        write_html_report(report, args.html_out)
        console.print(f"[dim]HTML report written to {args.html_out}[/dim]")

    if args.dry_run:
        return 0
    return 1 if (report.failed or report.errors) else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "run": cmd_run,
        "index": cmd_index,
        "list-tags": cmd_list_tags,
        "match": cmd_match,
    }
    handler = handlers[args.command]
    try:
        return handler(args)
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted.[/red]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
