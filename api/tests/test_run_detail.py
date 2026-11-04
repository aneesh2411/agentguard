"""Run detail page tests (server-rendered HTML at /runs/{run_id})."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store  # noqa: E402


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
