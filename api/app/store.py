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
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    task_type TEXT PRIMARY KEY,
    max_cost_per_task REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = "agentguard.db"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def put_run(self, run: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            (
                run["run_id"],
                run["task_type"],
                run["status"],
                run["cost_usd"],
                run["retry_count"],
                json.dumps(run),
            ),
        )
        self.conn.commit()

    def summary(self) -> dict:
        cur = self.conn.execute(
            """
            SELECT task_type,
                   COUNT(*) AS runs,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status='completed' THEN cost_usd ELSE 0 END) AS completed_cost,
                   SUM(CASE WHEN status='failed' THEN cost_usd ELSE 0 END) AS failed_cost
            FROM runs GROUP BY task_type
            """
        )
        retry_waste = self._retry_waste_by_task_type()
        rows = []
        for task_type, runs, completed, completed_cost, failed_cost in cur:
            rows.append(
                {
                    "task_type": task_type,
                    "runs": runs,
                    "completed": completed,
                    "cost_per_completed_task": (
                        round(completed_cost / completed, 6) if completed else None
                    ),
                    "wasted_on_failed_runs": round(failed_cost, 6),
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
        return {"task_types": rows}

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

    def _retry_waste_by_task_type(self) -> dict:
        """Cost of failed attempts inside runs that eventually completed."""
        waste: dict[str, float] = {}
        cur = self.conn.execute(
            "SELECT task_type, payload FROM runs WHERE status = 'completed'"
        )
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
                  status: str | None = None, limit: int = 100) -> list[dict]:
        q = "SELECT payload FROM runs"
        clauses, args = [], []
        if task_type:
            clauses.append("task_type = ?"); args.append(task_type)
        if status:
            clauses.append("status = ?"); args.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " LIMIT ?"; args.append(limit)
        return [json.loads(r[0]) for r in self.conn.execute(q, args)]
