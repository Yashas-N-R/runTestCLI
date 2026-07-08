"""Report generation: console summary, JSON, and HTML."""

from __future__ import annotations

import json
import os
import time
from html import escape

from rich.console import Console
from rich.table import Table
from rich.text import Text

from nltest.models import RunReport, Status

STATUS_STYLE = {
    Status.PASSED: "bold green",
    Status.FAILED: "bold red",
    Status.SKIPPED: "yellow",
    Status.ERROR: "bold red",
}

STATUS_SYMBOL = {
    Status.PASSED: "PASS",
    Status.FAILED: "FAIL",
    Status.SKIPPED: "SKIP",
    Status.ERROR: "ERR ",
}


def print_matches_preview(report: RunReport, console: Console | None = None, stage_labels: dict[str, str] | None = None) -> None:
    console = console or Console()
    if not report.matches:
        console.print(f"[yellow]No tests matched query:[/yellow] \"{report.query}\"")
        return
    table = Table(title=f'Matched tests for: "{report.query}"')
    if stage_labels:
        table.add_column("Stage")
    table.add_column("Score")
    table.add_column("Test")
    table.add_column("Framework")
    table.add_column("File")
    table.add_column("Tags")
    table.add_column("Why")
    for m in report.matches:
        row = []
        if stage_labels:
            row.append(stage_labels.get(m.test.id, "-"))
        row.extend(
            [
                f"{m.score:.2f}",
                m.test.name,
                m.test.framework.value,
                f"{m.test.file_path}:{m.test.line or ''}",
                ", ".join(m.test.tags),
                ", ".join(m.matched_on[:3]),
            ]
        )
        table.add_row(*row)
    console.print(table)


def print_console_report(report: RunReport, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(title=f'nltest run: "{report.query}"')
    table.add_column("Status")
    table.add_column("Test")
    table.add_column("Framework")
    table.add_column("File")
    table.add_column("Duration (s)")

    for r in report.results:
        style = STATUS_STYLE.get(r.status, "")
        table.add_row(
            Text(STATUS_SYMBOL.get(r.status, r.status.value), style=style),
            r.test.name,
            r.test.framework.value,
            f"{r.test.file_path}:{r.test.line or ''}",
            f"{r.duration_seconds:.2f}",
        )
    console.print(table)

    summary = (
        f"[bold]{report.total}[/bold] total   "
        f"[green]{report.passed} passed[/green]   "
        f"[red]{report.failed} failed[/red]   "
        f"[yellow]{report.skipped} skipped[/yellow]   "
        f"[red]{report.errors} errors[/red]   "
        f"in {report.duration_seconds:.2f}s"
    )
    console.print(summary)

    for r in report.results:
        if r.status in (Status.FAILED, Status.ERROR) and r.message:
            console.print(f"\n[bold red]{r.test.name}[/bold red] ({r.test.file_path})")
            console.print(r.message.strip()[:2000])


def to_dict(report: RunReport) -> dict:
    return {
        "query": report.query,
        "dry_run": report.dry_run,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": report.duration_seconds,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "errors": report.errors,
        },
        "results": [
            {
                "id": r.test.id,
                "name": r.test.name,
                "framework": r.test.framework.value,
                "stack": r.test.stack.value,
                "file_path": r.test.file_path,
                "line": r.test.line,
                "tags": r.test.tags,
                "status": r.status.value,
                "duration_seconds": r.duration_seconds,
                "message": r.message,
            }
            for r in report.results
        ],
    }


def write_json_report(report: RunReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_dict(report), fh, indent=2)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>nltest report: {query}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; background: #0f1115; color: #e6e6e6; }}
  h1 {{ font-size: 1.4rem; }}
  .summary {{ display: flex; gap: 1rem; margin: 1rem 0 2rem; }}
  .pill {{ padding: 0.4rem 0.8rem; border-radius: 999px; font-weight: 600; }}
  .pill.total {{ background: #2a2e37; }}
  .pill.passed {{ background: #1f4d2c; color: #7CFC9A; }}
  .pill.failed {{ background: #4d1f1f; color: #FF8A8A; }}
  .pill.skipped {{ background: #4d451f; color: #FFE07C; }}
  .pill.errors {{ background: #4d1f1f; color: #FF8A8A; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2e37; vertical-align: top; }}
  tr.passed td.status {{ color: #7CFC9A; }}
  tr.failed td.status, tr.error td.status {{ color: #FF8A8A; }}
  tr.skipped td.status {{ color: #FFE07C; }}
  code, pre {{ background: #1a1c22; padding: 0.2rem 0.4rem; border-radius: 4px; }}
  pre {{ white-space: pre-wrap; max-width: 700px; }}
  .tag {{ display:inline-block; background:#2a2e37; border-radius:4px; padding:0.1rem 0.4rem; margin-right:0.2rem; font-size:0.8rem; }}
</style>
</head>
<body>
<h1>nltest run: "{query}"</h1>
<div class="summary">
  <span class="pill total">{total} total</span>
  <span class="pill passed">{passed} passed</span>
  <span class="pill failed">{failed} failed</span>
  <span class="pill skipped">{skipped} skipped</span>
  <span class="pill errors">{errors} errors</span>
  <span class="pill total">{duration:.2f}s</span>
</div>
<table>
<thead>
<tr><th>Status</th><th>Test</th><th>Framework</th><th>File</th><th>Tags</th><th>Duration</th><th>Details</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<p style="color:#888;margin-top:2rem;">Generated by nltest at {generated_at}</p>
</body>
</html>
"""

_ROW_TEMPLATE = """<tr class="{status_class}">
  <td class="status">{status}</td>
  <td>{name}</td>
  <td>{framework}</td>
  <td><code>{file_path}{line}</code></td>
  <td>{tags}</td>
  <td>{duration:.2f}s</td>
  <td>{details}</td>
</tr>"""


def write_html_report(report: RunReport, path: str) -> None:
    rows = []
    for r in report.results:
        details = f"<pre>{escape(r.message.strip()[:1500])}</pre>" if r.message else ""
        tags = "".join(f'<span class="tag">{escape(tag)}</span>' for tag in r.test.tags)
        rows.append(
            _ROW_TEMPLATE.format(
                status_class=r.status.value,
                status=r.status.value.upper(),
                name=escape(r.test.name),
                framework=escape(r.test.framework.value),
                file_path=escape(r.test.file_path),
                line=f":{r.test.line}" if r.test.line else "",
                tags=tags,
                duration=r.duration_seconds,
                details=details,
            )
        )

    html = _HTML_TEMPLATE.format(
        query=escape(report.query),
        total=report.total,
        passed=report.passed,
        failed=report.failed,
        skipped=report.skipped,
        errors=report.errors,
        duration=report.duration_seconds,
        rows="\n".join(rows),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(report.finished_at or time.time())),
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
