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
    # outcome level: (0.30 + 0.10 + 0.25) / 2 completed tasks
    assert row["cost_per_completed_task"] == 0.325
    assert row["total_spend"] == 0.65
    assert row["spend_on_failed_runs"] == 0.25


def test_list_runs_filters(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.30, "retry_count": 1})
    s.put_run({"run_id": "2", "task_type": "invoice", "status": "failed",
               "cost_usd": 0.10, "retry_count": 0})
    assert len(s.list_runs()) == 2
    assert len(s.list_runs(task_type="ticket")) == 1
    assert len(s.list_runs(status="failed")) == 1


def test_dashboard_renders_values():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.dashboard import render_dashboard

    page = render_dashboard(
        {"task_types": [{"task_type": "ticket", "completed": 2,
                         "total_spend": 0.65,
                         "cost_per_completed_task": 0.325,
                         "spend_on_failed_runs": 0.25,
                         "retry_waste_in_completed_runs": 0.1}]},
        [{"task_type": "ticket", "status": "completed", "retry_count": 1,
          "cost_usd": 0.3, "run_id": "abc123def456"}],
    )
    assert "Cost per completed task" in page
    assert "$0.3250" in page
    assert "$0.6500" in page
    assert "ticket" in page
    assert "abc123def456" in page


def test_dashboard_empty_state():
    from app.dashboard import render_dashboard

    assert "No runs yet" in render_dashboard({"task_types": []}, [])


def test_retry_waste_attribution(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({
        "run_id": "1", "task_type": "ticket", "status": "completed",
        "cost_usd": 0.30, "retry_count": 1,
        "attempts": [
            {"status": "failed",
             "llm_calls": [{"cost_usd": 0.20}],
             "tool_calls": [{"cost_usd": 0.05}]},
            {"status": "succeeded",
             "llm_calls": [{"cost_usd": 0.05}],
             "tool_calls": []},
        ],
    })
    row = s.summary()["task_types"][0]
    assert row["retry_waste_in_completed_runs"] == 0.25
    assert row["cost_per_completed_task"] == 0.3


def test_http_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    r = c.post("/runs", json={"run_id": "1", "task_type": "ticket",
                              "status": "completed", "cost_usd": 0.1,
                              "retry_count": 0, "attempts": []})
    assert r.status_code == 201
    assert c.get("/summary").json()["task_types"][0]["completed"] == 1
    assert len(c.get("/runs").json()["runs"]) == 1
    page = c.get("/")
    assert page.status_code == 200 and "AgentGuard" in page.text


def test_budget_flag(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.30, "retry_count": 0})
    s.set_budget("ticket", 0.10)
    row = s.summary()["task_types"][0]
    assert row["budget_per_task"] == 0.10
    assert row["over_budget"] is True
    assert s.list_budgets() == [{"task_type": "ticket",
                                 "max_cost_per_task": 0.10}]


def test_budget_http(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    assert c.post("/budgets", json={"task_type": "ticket",
                                    "max_cost_per_task": 0.5}).status_code == 201
    assert c.get("/budgets").json()["budgets"][0]["max_cost_per_task"] == 0.5


def test_zero_completions_undefined_cost_not_zero(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "invoice", "status": "failed",
               "cost_usd": 0.40, "retry_count": 2})
    row = s.summary()["task_types"][0]
    assert row["cost_per_completed_task"] is None
    assert row["total_spend"] == 0.40
    assert row["spend_on_failed_runs"] == 0.40


def test_unresolved_runs_keep_spend_but_not_denominator(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "ticket", "status": "completed",
               "cost_usd": 0.10, "retry_count": 0})
    s.put_run({"run_id": "2", "task_type": "ticket", "status": "unknown",
               "cost_usd": 0.40, "retry_count": 0})
    row = s.summary()["task_types"][0]
    assert row["completed"] == 1
    assert row["unresolved_runs"] == 1
    assert row["spend_on_unresolved_runs"] == 0.40
    # unresolved spend stays in the numerator; denominator is completions
    assert row["cost_per_completed_task"] == 0.5
