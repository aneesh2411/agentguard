"""SQLite store for run events."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    retry_count INTEGER NOT NULL,
    event_ts REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    task_type TEXT PRIMARY KEY,
    max_cost_per_task REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    cost_per_completed_task REAL,
    budget_per_task REAL
);
"""


def _event_ts(run: dict) -> float | None:
    """Latest event time in a run payload (unix seconds), if any call has one."""
    latest = None
    for attempt in run.get("attempts", []):
        for call in (attempt.get("llm_calls", [])
                     + attempt.get("tool_calls", [])):
            ts = call.get("ts")
            if isinstance(ts, (int, float)):
                latest = ts if latest is None else max(latest, ts)
    return latest


class Store:
    def __init__(self, path: str | Path = "agentguard.db"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(runs)")}
        if "event_ts" not in cols:
            import time

            now = time.time()
            self.conn.execute(
                "ALTER TABLE runs ADD COLUMN event_ts REAL NOT NULL DEFAULT 0")
            # Backfill from payload call timestamps; runs without any get the
            # migration time - their true event time was never recorded.
            for run_id, payload in list(self.conn.execute(
                    "SELECT run_id, payload FROM runs")):
                ts = _event_ts(json.loads(payload)) or now
                self.conn.execute(
                    "UPDATE runs SET event_ts = ? WHERE run_id = ?",
                    (ts, run_id))
            self.conn.commit()

    def put_run(self, run: dict) -> None:
        import time

        self.conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run["run_id"],
                run["task_type"],
                run["status"],
                run["cost_usd"],
                run["retry_count"],
                _event_ts(run) or time.time(),
                json.dumps(run),
            ),
        )
        self.conn.commit()

    def summary(self, since: float | None = None,
                until: float | None = None) -> dict:
        clauses, args = [], []
        if since is not None:
            clauses.append("event_ts >= ?")
            args.append(since)
        if until is not None:
            clauses.append("event_ts < ?")
            args.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur = self.conn.execute(
            """
            SELECT task_type,
                   COUNT(*) AS runs,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status='completed' THEN cost_usd ELSE 0 END) AS completed_cost,
                   SUM(CASE WHEN status='failed' THEN cost_usd ELSE 0 END) AS failed_cost,
                   SUM(CASE WHEN status NOT IN ('completed','failed')
                            THEN 1 ELSE 0 END) AS unresolved,
                   SUM(CASE WHEN status NOT IN ('completed','failed')
                            THEN cost_usd ELSE 0 END) AS unresolved_cost
            FROM runs""" + where + """
            GROUP BY task_type
            """,
            args,
        )
        retry_waste = self._retry_waste_by_task_type(where, args)
        rows = []
        for (task_type, runs, completed, completed_cost, failed_cost,
             unresolved, unresolved_cost) in cur:
            # Outcome-level metric: ALL spend on this workflow (completed,
            # failed, and unresolved/outcome-unknown runs, incl. retries)
            # divided by tasks with an explicit completed signal.
            # Undefined (None) when nothing completed - never reported as zero.
            total_spend = completed_cost + failed_cost + unresolved_cost
            rows.append(
                {
                    "task_type": task_type,
                    "runs": runs,
                    "completed": completed,
                    "total_spend": round(total_spend, 6),
                    "cost_per_completed_task": (
                        round(total_spend / completed, 6) if completed else None
                    ),
                    "spend_on_completed_runs": round(completed_cost, 6),
                    "spend_on_failed_runs": round(failed_cost, 6),
                    "unresolved_runs": unresolved,
                    "spend_on_unresolved_runs": round(unresolved_cost, 6),
                    "retry_waste_in_completed_runs": round(
                        retry_waste.get(task_type, 0.0), 6
                    ),
                }
            )
        budgets = {
            t: m for t, m in
            self.conn.execute("SELECT task_type, max_cost_per_task FROM budgets")
        }
        for row in rows:
            budget = budgets.get(row["task_type"])
            row["budget_per_task"] = budget
            row["over_budget"] = (
                budget is not None
                and row["cost_per_completed_task"] is not None
                and row["cost_per_completed_task"] > budget
            )
        result = {"task_types": rows}
        if since is not None or until is not None:
            # Honest basis: an event-time window, not a cohort of tasks
            # completed in the window.
            result["window"] = {
                "since": since,
                "until": until,
                "basis": ("runs counted by their last event time; each "
                          "run's full spend is attributed to the window "
                          "containing its last event"),
            }
        return result

    def set_budget(self, task_type: str, max_cost_per_task: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO budgets VALUES (?, ?)",
            (task_type, max_cost_per_task),
        )
        self.conn.commit()

    def list_budgets(self) -> list[dict]:
        return [
            {"task_type": t, "max_cost_per_task": m}
            for t, m in self.conn.execute(
                "SELECT task_type, max_cost_per_task FROM budgets"
            )
        ]

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM runs WHERE run_id = ?",
                                (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def budget_status(self, task_type: str | None) -> dict | None:
        """Budget evaluation for one workflow, e.g. right after a write.

        None when the workflow has no budget (or no runs). Mirrors the
        summary's over_budget semantics: windowed/all-time cost per
        completed task strictly greater than the budget.
        """
        if task_type is None:
            return None
        budget = self.conn.execute(
            "SELECT max_cost_per_task FROM budgets WHERE task_type = ?",
            (task_type,)).fetchone()
        if budget is None:
            return None
        row = next((r for r in self.summary()["task_types"]
                    if r["task_type"] == task_type), None)
        if row is None:
            return None
        return {"budget_per_task": budget[0],
                "cost_per_completed_task": row["cost_per_completed_task"],
                "over_budget": row["over_budget"]}

    def record_alert_transition(self, task_type: str, over_budget: bool,
                                run_id: str | None = None,
                                cost_per_completed_task: float | None = None,
                                budget_per_task: float | None = None) -> dict | None:
        """Log a budget alert when a workflow's over_budget state changes.

        Returns the recorded event, or None when the state is unchanged.
        A workflow already over budget does not re-alert on every ingest;
        it alerts again only after recovering (a read under budget) and
        breaching once more. Recovery itself is logged as 'recovered'.
        """
        import time

        last = self.conn.execute(
            "SELECT status FROM alerts WHERE task_type = ? "
            "ORDER BY id DESC LIMIT 1", (task_type,)).fetchone()
        state = "breach" if over_budget else "recovered"
        if last is not None and last[0] == state:
            return None
        if last is None and not over_budget:
            return None  # never breached: nothing to recover from
        ts = time.time()
        cur = self.conn.execute(
            "INSERT INTO alerts (ts, task_type, status, run_id, "
            "cost_per_completed_task, budget_per_task) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, task_type, state, run_id, cost_per_completed_task,
             budget_per_task))
        self.conn.commit()
        return {"id": cur.lastrowid, "ts": ts, "task_type": task_type,
                "status": state, "run_id": run_id,
                "cost_per_completed_task": cost_per_completed_task,
                "budget_per_task": budget_per_task}

    def list_alerts(self, limit: int = 50) -> list[dict]:
        return [
            {"id": i, "ts": t, "task_type": tt, "status": st,
             "run_id": r, "cost_per_completed_task": c,
             "budget_per_task": b}
            for i, t, tt, st, r, c, b in self.conn.execute(
                "SELECT id, ts, task_type, status, run_id, "
                "cost_per_completed_task, budget_per_task FROM alerts "
                "ORDER BY id DESC LIMIT ?", (limit,))
        ]

    def _retry_waste_by_task_type(self, where: str = "",
                                  args: list | None = None) -> dict:
        """Cost of failed attempts inside runs that eventually completed."""
        waste: dict[str, float] = {}
        q = "SELECT task_type, payload FROM runs WHERE status = 'completed'"
        if where:
            q += " AND " + where.removeprefix(" WHERE ")
        cur = self.conn.execute(q, args or [])
        for task_type, payload in cur:
            run = json.loads(payload)
            attempts = run.get("attempts", [])
            run_waste = 0.0
            for a in attempts:
                if a.get("status") == "failed":
                    run_waste += sum(c.get("cost_usd", 0.0)
                                     for c in a.get("llm_calls", []))
                    run_waste += sum(t.get("cost_usd", 0.0)
                                     for t in a.get("tool_calls", []))
            waste[task_type] = waste.get(task_type, 0.0) + run_waste
        return waste

    def list_runs(self, task_type: str | None = None,
                  status: str | None = None, limit: int = 100,
                  since: float | None = None,
                  until: float | None = None) -> list[dict]:
        q = "SELECT payload FROM runs"
        clauses, args = [], []
        if task_type:
            clauses.append("task_type = ?"); args.append(task_type)
        if status:
            clauses.append("status = ?"); args.append(status)
        if since is not None:
            clauses.append("event_ts >= ?"); args.append(since)
        if until is not None:
            clauses.append("event_ts < ?"); args.append(until)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " LIMIT ?"; args.append(limit)
        return [json.loads(r[0]) for r in self.conn.execute(q, args)]
