"""Read-only HTML dashboard, server-rendered, no JS dependencies."""
from __future__ import annotations

import html

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>AgentGuard</title><style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 720px; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border-bottom: 1px solid #ddd; padding: .4rem .6rem; text-align: left; }}
.muted {{ color: #777; }}
</style></head><body>
<h1>AgentGuard</h1>
<p class="muted">Cost per completed task. Auto-refreshes every 30s.</p>
{summary}
<h2>Recent runs</h2>
{runs}
</body></html>"""


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:.4f}"


def render_dashboard(summary: dict, runs: list[dict]) -> str:
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(r["task_type"]),
            r["completed"],
            _money(r["cost_per_completed_task"]),
            _money(r["wasted_on_failed_runs"]),
        )
        for r in summary.get("task_types", [])
    )
    summary_html = (
        "<table><tr><th>Workflow</th><th>Completed</th>"
        "<th>Cost / completed task</th><th>Wasted on failed runs</th></tr>"
        f"{rows}</table>"
        if rows
        else '<p class="muted">No runs yet. Post one with the SDK.</p>'
    )
    run_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(r.get("task_type", "")),
            html.escape(r.get("status", "")),
            r.get("retry_count", 0),
            _money(r.get("cost_usd")),
            html.escape(r.get("run_id", "")[:8]),
        )
        for r in runs[:50]
    )
    runs_html = (
        "<table><tr><th>Workflow</th><th>Status</th><th>Retries</th>"
        f"<th>Cost</th><th>Run</th></tr>{run_rows}</table>"
        if run_rows
        else ""
    )
    return PAGE.format(summary=summary_html, runs=runs_html)
