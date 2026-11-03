"""Store-level aggregation test (no server needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store  # noqa: E402


def test_cost_per_completed_task(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.30, "retry_count": 1})
    s.put_run({"run_id": "2", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.10, "retry_count": 0})
    s.put_run({"run_id": "3", "task_type": "ticket", "status": "failed",
               "cost_usd": 0.25, "retry_count": 2})
    row = s.summary()["task_types"][0]
    assert row["cost_per_completed_task"] == 0.2
    assert row["wasted_on_failed_runs"] == 0.25


def test_list_runs_filters(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.30, "retry_count": 1})
    s.put_run({"run_id": "2", "task_type": "invoice", "status": "failed",
               "cost_usd": 0.10, "retry_count": 0})
    assert len(s.list_runs()) == 2
    assert len(s.list_runs(task_type="ticket")) == 1
    assert len(s.list_runs(status="failed")) == 1
