"""Read-only HTML dashboard, server-rendered, no JS dependencies."""
from __future__ import annotations

import html

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>AgentGuard</title><style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 720px; }}
tr.over td {{ background: #fdecea; }}
.badge {{ color: #b3261e; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border-bottom: 1px solid #ddd; padding: .4rem .6rem; text-align: left; }}
.muted {{ color: #777; }}
</style></head><body>
<h1>AgentGuard</h1>
<p class="muted">Cost per completed task = all spend on the workflow (failed, unresolved, and retry attempts included) divided by tasks with an explicit completion signal. Auto-refreshes every 30s.</p>
{summary}
<h2>Spend per day (UTC)</h2>
{chart}
<h2>Budget alerts</h2>
{alerts}
<h2>Recent runs</h2>
{runs}
<p class="muted">Costs are estimates from the shipped pricing table
(standard-tier uncached rates) unless the run was imported with
provider-reported spend.</p>
</body></html>"""


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:.4f}"


def _window_links(summary: dict) -> str:
    import time

    now = time.time()
    day = int(now - 86400)
    week = int(now - 7 * 86400)
    return (
        '<p class="muted">Window: '
        f'<a href="/?since={day}">last 24h</a> · '
        f'<a href="/?since={week}">last 7 days</a> · '
        '<a href="/">all time</a></p>'
    )


def _window_note(summary: dict) -> str:
    w = summary.get("window")
    if not w:
        return ""
    import datetime

    def fmt(ts):
        return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                .strftime("%Y-%m-%d %H:%M UTC")) if ts else "the beginning"

    def label(ts, fallback):
        return fmt(ts) if ts else fallback

    return ('<p class="muted">Showing {} to {}. Runs are counted by their '
            "last event time; each run's full spend is attributed to the "
            'window containing its last event, so this is not a cohort of '
            'tasks completed in the window.</p>'
            .format(label(w.get("since"), "the beginning"),
                    label(w.get("until"), "now")))



def _filter_links(summary: dict, task_type: str | None) -> str:
    """Workflow filter links for the runs table, preserving the window."""
    from urllib.parse import urlencode

    w = summary.get("window") or {}
    types = {t.get("task_type") for t in summary.get("task_types", [])}
    types.discard(None)
    if task_type:
        types.add(task_type)
    if not types:
        return ""

    def href(t):
        q = {}
        if w.get("since"):
            q["since"] = str(int(w["since"]))
        if w.get("until"):
            q["until"] = str(int(w["until"]))
        if t:
            q["task_type"] = t
        return "/?" + urlencode(q) if q else "/"

    parts = []
    if task_type:
        parts.append('<a href="{}">all</a>'.format(
            html.escape(href(None), quote=True)))
    else:
        parts.append("<strong>all</strong>")
    for t in sorted(types):
        label = html.escape(str(t))
        if t == task_type:
            parts.append(f"<strong>{label}</strong>")
        else:
            parts.append('<a href="{}">{}</a>'.format(
                html.escape(href(t), quote=True), label))
    return ('<p class="muted">Filter runs by workflow: ' + " · ".join(parts)
            + "</p>")


def _spend_chart(runs: list[dict]) -> str:
    """Inline SVG bar chart of estimated spend per UTC day (no JS)."""
    import datetime

    per_day: dict[str, float] = {}
    for r in runs:
        cost = r.get("cost_usd")
        if not isinstance(cost, (int, float)) or cost <= 0:
            continue
        latest = None
        for a in r.get("attempts", []):
            for c in (a.get("llm_calls", []) + a.get("tool_calls", [])):
                ts = c.get("ts")
                if isinstance(ts, (int, float)):
                    latest = ts if latest is None else max(latest, ts)
        if latest is None:
            continue
        day = (datetime.datetime.fromtimestamp(latest, datetime.timezone.utc)
               .strftime("%Y-%m-%d"))
        per_day[day] = per_day.get(day, 0.0) + cost
    if not per_day:
        return '<p class="muted">No timestamped spend in this view.</p>'
    days = sorted(per_day)
    peak = max(per_day.values())
    width, height, pad = 640, 120, 24
    bw = max(4, (width - pad * 2) // len(days) - 4)
    bars = []
    for i, d in enumerate(days):
        h = max(1, round((per_day[d] / peak) * (height - pad * 2)))
        x = pad + i * (bw + 4)
        y = height - pad - h
        bars.append(
            '<rect x="{}" y="{}" width="{}" height="{}" fill="#4c7cbf">'
            "<title>{}: {}</title></rect>".format(x, y, bw, h, d,
                                                  _money(per_day[d])))
    peak_label = ('<text x="{}" y="12" font-size="10" fill="#777">'
                  "peak day {}</text>".format(pad, _money(peak)))
    first = ('<text x="{}" y="{}" font-size="10" fill="#777">{}</text>'
             .format(pad, height - 6, days[0]))
    last = ('<text x="{}" y="{}" font-size="10" fill="#777" '
            'text-anchor="end">{}</text>'.format(width - pad, height - 6,
                                                 days[-1]))
    return ('<svg role="img" aria-label="Estimated spend per day" '
            'width="{}" height="{}" viewBox="0 0 {} {}">{}{}{}{}</svg>'
            .format(width, height, width, height, peak_label,
                    "".join(bars), first, last))


def render_dashboard(summary: dict, runs: list[dict],
                     alerts: list[dict] | None = None,
                     task_type: str | None = None) -> str:
    rows = "".join(
        '<tr{}><td>{}</td><td>{}</td><td>{}</td><td>{}{}</td><td>{}</td>'
        "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
            ' class="over"' if r.get("over_budget") else "",
            html.escape(r["task_type"]),
            r["completed"],
            _money(r.get("total_spend")),
            _money(r["cost_per_completed_task"]),
            (' <span class="badge">OVER BUDGET</span>'
             if r.get("over_budget") else ""),
            _money(r.get("spend_on_failed_runs")),
            _money(r.get("retry_waste_in_completed_runs")),
            _money(r.get("spend_on_unresolved_runs")),
            _money(r.get("budget_per_task")),
        )
        for r in summary.get("task_types", [])
    )
    summary_html = (
        _window_links(summary)
        + _window_note(summary)
        + "<table><tr><th>Workflow</th><th>Completed</th>"
        "<th>Total spend</th>"
        "<th>Cost / completed task</th>"
        "<th>of which failed runs</th>"
        "<th>of which retries</th><th>unresolved</th>"
        "<th>budget / task</th></tr>"
        f"{rows}</table>"
        if rows
        else _window_links(summary)
        + '<p class="muted">No runs yet. Post one with the SDK.</p>'
    )
    run_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(r.get("task_type", "")),
            html.escape(r.get("status", "")),
            r.get("retry_count", 0),
            _money(r.get("cost_usd")),
            '<a href="/runs/{}">{}</a>'.format(
                html.escape(str(r.get("run_id", "")), quote=True),
                html.escape(str(r.get("run_id", "")))),
        )
        for r in runs[:50]
    )
    runs_html = _filter_links(summary, task_type) + (
        "<table><tr><th>Workflow</th><th>Status</th><th>Retries</th>"
        f"<th>Cost</th><th>Run</th></tr>{run_rows}</table>"
        if run_rows
        else ""
    )
    alert_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{} of {}</td></tr>".format(
            _fmt_ts(a.get("ts")),
            html.escape(str(a.get("task_type", ""))),
            html.escape(str(a.get("status", ""))),
            _money(a.get("cost_per_completed_task")),
            _money(a.get("budget_per_task")),
        )
        for a in (alerts or [])
    )
    alerts_html = (
        "<table><tr><th>Time</th><th>Workflow</th><th>Event</th>"
        f"<th>Cost / task vs budget</th></tr>{alert_rows}</table>"
        if alert_rows
        else '<p class="muted">No budget breaches recorded. External alert '
        'delivery is not configured; this log is local-only.</p>'
    )
    chart_html = _spend_chart(runs)
    return PAGE.format(summary=summary_html, chart=chart_html,
                       runs=runs_html, alerts=alerts_html)


DETAIL_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1">
<title>AgentGuard - run {run_id}</title><style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 720px; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.2rem; }}
td, th {{ border-bottom: 1px solid #ddd; padding: .4rem .6rem; text-align: left; }}
.muted {{ color: #777; }}
</style></head><body>
<p><a href="/">&larr; dashboard</a></p>
<h1>Run {run_id}</h1>
{body}
</body></html>"""


def _fmt_ts(ts) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    import datetime

    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S UTC"))


def render_run_detail(run: dict) -> str:
    """Run detail page: attempts, their LLM/tool calls, and cost split."""
    run_id = html.escape(str(run.get("run_id", "")))
    parts = [
        "<p><strong>{}</strong> - status {} - {} retries - "
        "total {}</p>".format(
            html.escape(str(run.get("task_type", ""))),
            html.escape(str(run.get("status", ""))),
            run.get("retry_count", 0),
            _money(run.get("cost_usd")),
        )
    ]
    meta = run.get("metadata") or {}
    if meta:
        rows = "".join(
            "<tr><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(k)), html.escape(str(v)))
            for k, v in sorted(meta.items())
        )
        parts.append("<h2>Metadata</h2><table><tr><th>Key</th>"
                     f"<th>Value</th></tr>{rows}</table>")
    for i, a in enumerate(run.get("attempts", []), 1):
        parts.append("<h2>Attempt {} - {} - {}</h2>".format(
            i, html.escape(str(a.get("status", ""))),
            _money(sum(c.get("cost_usd", 0.0) for c in a.get("llm_calls", []))
                   + sum(t.get("cost_usd", 0.0)
                         for t in a.get("tool_calls", [])))))
        llm_rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
            "<td>{}</td></tr>".format(
                html.escape(str(c.get("model", ""))),
                c.get("input_tokens", 0), c.get("output_tokens", 0),
                _money(c.get("cost_usd")), _fmt_ts(c.get("ts")))
            for c in a.get("llm_calls", [])
        )
        if llm_rows:
            parts.append("<table><tr><th>Model</th><th>In tokens</th>"
                         "<th>Out tokens</th><th>Cost</th><th>Time</th></tr>"
                         f"{llm_rows}</table>")
        tool_rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(t.get("name", ""))),
                html.escape(str(t.get("status", ""))),
                _money(t.get("cost_usd")), _fmt_ts(t.get("ts")))
            for t in a.get("tool_calls", [])
        )
        if tool_rows:
            parts.append("<table><tr><th>Tool</th><th>Status</th>"
                         f"<th>Cost</th><th>Time</th></tr>{tool_rows}</table>")
    return DETAIL_PAGE.format(run_id=run_id, body="".join(parts))
