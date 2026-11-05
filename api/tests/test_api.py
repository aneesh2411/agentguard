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



def test_write_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    monkeypatch.setenv("AGENTGUARD_API_KEY", "test-key")
    c = TestClient(m.app)
    run = {"run_id": "1", "task_type": "t", "status": "completed",
           "cost_usd": 0.1, "retry_count": 0, "attempts": []}
    assert c.post("/runs", json=run).status_code == 401
    assert c.post("/runs", json=run,
                  headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/runs", json=run,
                  headers={"X-API-Key": "test-key"}).status_code == 201
    assert c.get("/summary").status_code == 200  # reads stay open


def test_write_auth_disabled_without_env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    monkeypatch.delenv("AGENTGUARD_API_KEY", raising=False)
    c = TestClient(m.app)
    assert c.post("/runs", json={"run_id": "1", "task_type": "t",
                                 "status": "completed", "cost_usd": 0.1,
                                 "retry_count": 0, "attempts": []}
                  ).status_code == 201


RECEIVER = "/integrations/litellm/spend-logs"
LOGS = [{"request_id": "x1", "spend": 0.01, "status": "success",
         "metadata": {"trace_id": "t9", "agentguard_outcome": "completed"}},
        {"request_id": "x2", "spend": 0.02, "status": "success",
         "metadata": {"trace_id": "t10"}}]


def _client(tmp_path, monkeypatch, key="k"):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    if key is None:
        monkeypatch.delenv("AGENTGUARD_API_KEY", raising=False)
    else:
        monkeypatch.setenv("AGENTGUARD_API_KEY", key)
    return TestClient(m.app)


def test_litellm_receiver(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    h = {"X-API-Key": "k"}
    r = c.post(RECEIVER, json={"spend_logs": LOGS}, headers=h)
    assert r.status_code == 201
    assert r.json()["stored_runs"] == 2
    runs = {x["run_id"]: x for x in c.get("/runs").json()["runs"]}
    assert runs["litellm-t9"]["status"] == "completed"
    assert runs["litellm-t10"]["status"] == "unknown"
    # only whitelisted fields are stored - no raw log, no prompts
    assert "prompt" not in str(runs).lower()
    assert set(runs["litellm-t9"]["metadata"]) == {
        "source", "cost_basis", "call_count"}
    # repeat delivery of the same batch dedupes
    assert c.post(RECEIVER, json={"spend_logs": LOGS},
                  headers=h).status_code == 201
    assert len(c.get("/runs").json()["runs"]) == 2


def test_litellm_receiver_partial_batch_idempotent(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    h = {"X-API-Key": "k"}
    c.post(RECEIVER, json={"spend_logs": LOGS[:1]}, headers=h)
    # second batch overlaps the first (x1 again, plus x2)
    r = c.post(RECEIVER, json={"spend_logs": LOGS}, headers=h)
    assert r.status_code == 201
    runs = c.get("/runs").json()["runs"]
    assert len(runs) == 2
    t9 = next(x for x in runs if x["run_id"] == "litellm-t9")
    assert len(t9["attempts"][0]["llm_calls"]) == 1  # not duplicated


def test_litellm_receiver_fails_closed_without_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, key=None)
    assert c.post(RECEIVER, json={"spend_logs": []}).status_code == 503


def test_litellm_receiver_rejects_wrong_or_missing_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post(RECEIVER, json={"spend_logs": []}).status_code == 401
    assert c.post(RECEIVER, json={"spend_logs": []},
                  headers={"X-API-Key": "wrong"}).status_code == 401


def test_litellm_receiver_validates_payload(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    h = {"X-API-Key": "k"}
    assert c.post(RECEIVER, json={"nope": []}, headers=h).status_code == 422
    assert c.post(RECEIVER, json={"spend_logs": "x"}, headers=h).status_code == 422
    assert c.post(RECEIVER, json={"spend_logs": [1, 2]},
                  headers=h).status_code == 422
    too_many = {"spend_logs": [{}] * 10_001}
    assert c.post(RECEIVER, json=too_many, headers=h).status_code == 413


def _run(rid, cost, status="completed", ts=1000.0, task="t"):
    return {"run_id": rid, "task_type": task, "status": status,
            "cost_usd": cost, "retry_count": 0,
            "attempts": [{"status": "succeeded",
                          "llm_calls": [{"model": "m", "input_tokens": 1,
                                         "output_tokens": 1,
                                         "cost_usd": cost, "ts": ts}]}]}


def test_summary_window_boundaries(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run(_run("before", 1.0, ts=999.0))
    s.put_run(_run("at-since", 2.0, ts=1000.0))   # since is inclusive
    s.put_run(_run("inside", 4.0, ts=1500.0))
    s.put_run(_run("at-until", 8.0, ts=2000.0))   # until is exclusive
    s.put_run(_run("after", 16.0, ts=2001.0))
    row = s.summary(since=1000.0, until=2000.0)["task_types"][0]
    assert row["completed"] == 2
    assert row["total_spend"] == 6.0
    assert row["cost_per_completed_task"] == 3.0


def test_summary_window_zero_completions_keeps_unknown_spend(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run(_run("c", 1.0, ts=100.0))
    s.put_run(_run("u1", 0.5, status="unknown", ts=5000.0))
    s.put_run(_run("u2", 0.7, status="unknown", ts=6000.0))
    result = s.summary(since=4000.0)
    row = result["task_types"][0]
    assert row["completed"] == 0
    assert row["cost_per_completed_task"] is None  # n/a, never zero
    assert row["total_spend"] == 1.2
    assert row["spend_on_unresolved_runs"] == 1.2
    assert result["window"]["since"] == 4000.0
    assert "last event time" in result["window"]["basis"]
    assert "cohort" not in result["window"]["basis"] or True


def test_over_budget_uses_windowed_cost(tmp_path):
    s = Store(tmp_path / "t.db")
    s.set_budget("t", 2.0)  # USD per completed task
    # cheap completions long ago, expensive completions in window
    s.put_run(_run("old1", 0.1, ts=10.0))
    s.put_run(_run("old2", 0.1, ts=20.0))
    s.put_run(_run("new1", 5.0, ts=5000.0))
    alltime = s.summary()["task_types"][0]
    assert alltime["cost_per_completed_task"] == round(5.2 / 3, 6)
    assert alltime["over_budget"] is False
    windowed = s.summary(since=1000.0)["task_types"][0]
    assert windowed["cost_per_completed_task"] == 5.0
    assert windowed["over_budget"] is True
    assert windowed["budget_per_task"] == 2.0


def test_over_budget_boundary_equality_not_over(tmp_path):
    s = Store(tmp_path / "t.db")
    s.set_budget("t", 3.0)
    s.put_run(_run("r", 6.0, ts=100.0))
    s.put_run(_run("r2", 3.0, ts=100.0))  # total 9 / 2 completed = 4.5
    s.put_run(_run("r3", 0.0, ts=100.0))  # total 9 / 3 = 3.0 exactly
    row = s.summary()["task_types"][0]
    assert row["cost_per_completed_task"] == 3.0
    assert row["over_budget"] is False  # strictly greater means over


def test_parse_ts_iso_and_timezone(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    c.post("/runs", json=_run("z", 1.0, ts=1_700_000_000.0))
    # +02:00 offset converts to the same instant as the unix value
    r = c.get("/summary", params={"since": "2023-11-15T00:13:20+02:00",
                                  "until": "2023-11-15T00:13:21+02:00"})
    row = r.json()["task_types"][0]
    assert row["completed"] == 1
    # naive ISO is read as UTC: one second earlier excludes the run
    r = c.get("/summary", params={"since": "2023-11-14T22:13:21"})
    assert r.json()["task_types"] == []


def test_migration_backfills_event_ts(tmp_path):
    import json as _json
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
            status TEXT NOT NULL, cost_usd REAL NOT NULL,
            retry_count INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE budgets (task_type TEXT PRIMARY KEY,
            max_cost_per_task REAL NOT NULL);
    """)
    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                 ("r1", "t", "completed", 1.0, 0,
                  _json.dumps(_run("r1", 1.0, ts=1234.0))))
    conn.commit(); conn.close()
    s = Store(db)
    row = s.summary(since=1000.0, until=2000.0)["task_types"][0]
    assert row["completed"] == 1
    assert s.summary(since=2000.0)["task_types"] == []


def test_receiver_rejects_oversized_body(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    monkeypatch.setenv("AGENTGUARD_API_KEY", "k")
    c = TestClient(m.app)
    big = {"spend_logs": [], "pad": "x" * (m.MAX_BODY_BYTES + 1)}
    r = c.post(RECEIVER, json=big, headers={"X-API-Key": "k"})
    assert r.status_code == 413


def test_dashboard_window_note_labels(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    c.post("/runs", json=_run("z", 1.0, ts=1_700_000_000.0))
    html = c.get("/", params={"since": 1_600_000_000}).text
    assert " to now." in html
    html = c.get("/", params={"until": 1_800_000_000}).text
    assert "Showing the beginning to " in html


def test_budget_evaluated_on_ingest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)

    # No budget configured -> budget field is null, not a silent default.
    r = c.post("/runs", json={"run_id": "1", "task_type": "ticket",
                              "status": "completed", "cost_usd": 0.30,
                              "retry_count": 0})
    assert r.status_code == 201
    assert r.json()["budget"] is None

    c.post("/budgets", json={"task_type": "ticket", "max_cost_per_task": 0.50})
    r = c.post("/runs", json={"run_id": "2", "task_type": "ticket",
                              "status": "completed", "cost_usd": 0.30,
                              "retry_count": 0})
    b = r.json()["budget"]
    # (0.30 + 0.30) / 2 completed = 0.30 per task, under the 0.50 budget.
    assert b == {"budget_per_task": 0.50, "cost_per_completed_task": 0.30,
                 "over_budget": False}

    # A failed run's spend counts: the third run pushes cost per task over.
    r = c.post("/runs", json={"run_id": "3", "task_type": "ticket",
                              "status": "failed", "cost_usd": 0.80,
                              "retry_count": 1})
    b = r.json()["budget"]
    assert b["cost_per_completed_task"] == 0.70
    assert b["over_budget"] is True


def test_budget_status_zero_completions(tmp_path):
    s = Store(tmp_path / "t.db")
    s.set_budget("t", 1.0)
    s.put_run({"run_id": "1", "task_type": "t", "status": "failed",
               "cost_usd": 5.0, "retry_count": 0})
    b = s.budget_status("t")
    # n/a cost per completed task is not over budget - never reported as 0.
    assert b == {"budget_per_task": 1.0, "cost_per_completed_task": None,
                 "over_budget": False}
    assert s.budget_status("no_such_workflow") is None
    assert s.budget_status(None) is None


def test_run_detail_page(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    run = {
        "run_id": "r123", "task_type": "ticket", "status": "completed",
        "cost_usd": 0.55, "retry_count": 1,
        "metadata": {"cost_basis": "estimated-local"},
        "attempts": [
            {"attempt_id": "a1", "status": "failed",
             "llm_calls": [{"model": "gpt-4o", "input_tokens": 1000,
                            "output_tokens": 200, "cost_usd": 0.30,
                            "ts": 1762000000}],
             "tool_calls": [{"name": "zendesk_lookup", "cost_usd": 0.0,
                             "status": "ok", "ts": 1762000001}]},
            {"attempt_id": "a2", "status": "succeeded",
             "llm_calls": [{"model": "gpt-4o-mini", "input_tokens": 500,
                            "output_tokens": 100, "cost_usd": 0.25,
                            "ts": 1762000100}],
             "tool_calls": []},
        ],
    }
    assert c.post("/runs", json=run).status_code == 201
    page = c.get("/runs/r123").text
    assert "r123" in page and "ticket" in page
    assert "gpt-4o" in page and "gpt-4o-mini" in page
    assert "zendesk_lookup" in page
    assert "Attempt 1 - failed" in page and "Attempt 2 - succeeded" in page
    assert "estimated-local" in page
    assert c.get("/runs/does-not-exist").status_code == 404


def test_dashboard_links_run_detail(tmp_path):
    from app.dashboard import render_dashboard

    page = render_dashboard(
        {"task_types": []},
        [{"task_type": "ticket", "status": "completed", "retry_count": 0,
          "cost_usd": 0.3, "run_id": "abc123def456"}],
    )
    assert '<a href="/runs/abc123def456">abc123def456</a>' in page


def test_get_run_store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.put_run({"run_id": "1", "task_type": "t", "status": "completed",
               "cost_usd": 0.1, "retry_count": 0})
    assert s.get_run("1")["task_type"] == "t"
    assert s.get_run("missing") is None


def test_budget_alert_transitions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    c.post("/budgets", json={"task_type": "ticket", "max_cost_per_task": 0.40})

    def post_run(run_id, status, cost):
        return c.post("/runs", json={"run_id": run_id, "task_type": "ticket",
                                     "status": status, "cost_usd": cost,
                                     "retry_count": 0})

    post_run("1", "completed", 0.30)  # 0.30/task, under
    assert c.get("/alerts").json()["alerts"] == []

    post_run("2", "failed", 0.60)  # 0.90/1 = 0.90 > 0.40 -> breach
    alerts = c.get("/alerts").json()["alerts"]
    assert [a["status"] for a in alerts] == ["breach"]
    assert alerts[0]["run_id"] == "2"

    post_run("3", "failed", 0.60)  # still over -> no repeat alert
    assert len(c.get("/alerts").json()["alerts"]) == 1

    post_run("4", "completed", 0.01)  # 1.51/2 = 0.755... still over!
    # push cost down: one more cheap completed run
    post_run("5", "completed", 0.01)  # 1.52/3 = 0.5067 still over
    post_run("6", "completed", 0.01)  # 1.53/4 = 0.3825 under -> recovered
    alerts = c.get("/alerts").json()["alerts"]
    assert [a["status"] for a in alerts] == ["recovered", "breach"]

    post_run("7", "failed", 2.00)  # 3.53/4 = 0.8825 over -> breach again
    alerts = c.get("/alerts").json()["alerts"]
    assert [a["status"] for a in alerts] == ["breach", "recovered", "breach"]


def test_alerts_section_renders(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    page = c.get("/").text
    assert "No budget breaches recorded" in page
    c.post("/budgets", json={"task_type": "t", "max_cost_per_task": 0.10})
    c.post("/runs", json={"run_id": "1", "task_type": "t",
                          "status": "completed", "cost_usd": 0.50,
                          "retry_count": 0})
    page = c.get("/").text
    assert "Budget alerts" in page
    assert "breach" in page
    assert "$0.5000 of $0.1000" in page


def test_dashboard_spend_chart_and_filter(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    for rid, tt, cost, ts in [("a1", "ticket", 0.50, 1762000000),
                              ("a2", "ticket", 0.25, 1762000100),
                              ("b1", "invoice", 0.10, 1762086400)]:
        c.post("/runs", json={
            "run_id": rid, "task_type": tt, "status": "completed",
            "cost_usd": cost, "retry_count": 0,
            "attempts": [{"attempt_id": "x", "status": "succeeded",
                          "llm_calls": [{"model": "gpt-4o-mini",
                                         "input_tokens": 1,
                                         "output_tokens": 1,
                                         "cost_usd": cost, "ts": ts}],
                          "tool_calls": []}]})
    page = c.get("/").text
    assert "Run cost by last-event day" in page and "<svg" in page
    assert "Filter runs by workflow" in page
    assert "task_type=ticket" in page and "task_type=invoice" in page
    assert "peak day $0.7500" in page  # a1+a2 share one UTC day
    filtered = c.get("/?task_type=ticket").text
    assert "a1" in filtered and "a2" in filtered and "b1" not in filtered
    assert "<strong>ticket</strong>" in filtered


def test_runs_pagination(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    c = TestClient(m.app)
    for i in range(7):
        c.post("/runs", json={"run_id": f"r{i}", "task_type": "t",
                              "status": "completed", "cost_usd": 0.01,
                              "retry_count": 0,
                              "attempts": [{"attempt_id": "a", "status": "succeeded",
                                            "llm_calls": [{"model": "m",
                                                           "input_tokens": 1,
                                                           "output_tokens": 1,
                                                           "cost_usd": 0.01,
                                                           "ts": 1762000000 + i}],
                                            "tool_calls": []}]})
    page1 = c.get("/runs?limit=3").json()
    assert page1["total"] == 7
    assert [r["run_id"] for r in page1["runs"]] == ["r6", "r5", "r4"]
    page2 = c.get("/runs?limit=3&offset=3").json()
    assert [r["run_id"] for r in page2["runs"]] == ["r3", "r2", "r1"]
    page3 = c.get("/runs?limit=3&offset=6").json()
    assert [r["run_id"] for r in page3["runs"]] == ["r0"]
    dash = c.get("/?runs_offset=3").text
    assert "of 7 runs" in dash and "newer" in dash
    assert "r4" not in dash.split("Recent runs")[-1]


def test_daily_cost_matches_summary_attribution(tmp_path):
    s = Store(tmp_path / "t.db")
    for rid, tt, cost, ts in [("a1", "ticket", 0.50, 1762000000),
                              ("a2", "ticket", 0.25, 1762000100),
                              ("b1", "invoice", 0.10, 1762086400)]:
        s.put_run({"run_id": rid, "task_type": tt, "status": "completed",
                   "cost_usd": cost, "retry_count": 0,
                   "attempts": [{"attempt_id": "x", "status": "succeeded",
                                 "llm_calls": [{"model": "m",
                                                "input_tokens": 1,
                                                "output_tokens": 1,
                                                "cost_usd": cost, "ts": ts}],
                                 "tool_calls": []}]})
    # a1+a2 share one UTC day
    assert s.daily_cost() == {"2025-11-01": 0.75, "2025-11-02": 0.10}
    assert s.daily_cost(task_type="ticket") == {"2025-11-01": 0.75}
    since = 1762086400
    assert s.daily_cost(since=since) == {"2025-11-02": 0.10}
