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
                }
            )
        return {"task_types": rows}

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
