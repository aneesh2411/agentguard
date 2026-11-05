"""AgentGuard ingestion + read-only aggregate API."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import require_receiver_key, require_write_key

from .store import Store

app = FastAPI(title="AgentGuard", version="0.1.0")
store = Store()

MAX_BODY_BYTES = 2_000_000


@app.middleware("http")
async def cap_request_body(request: Request, call_next):
    # Reject oversized requests before the body is parsed. Based on the
    # declared Content-Length; chunked bodies without one still parse.
    declared = request.headers.get("content-length")
    if declared is not None and int(declared) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413,
                            content={"detail": "request body too large"})
    return await call_next(request)


def _parse_ts(value: str | None) -> float | None:
    """ISO 8601 (offset-aware; naive read as UTC) or unix seconds."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@app.post("/runs", status_code=201, dependencies=[Depends(require_write_key)])
def ingest_run(run: dict) -> dict:
    store.put_run(run)
    # Evaluate the workflow's budget at write time, not just on read, so a
    # caller learns about a breach in the ingest response. `budget` is null
    # when the workflow has no budget configured. State transitions into or
    # out of breach are logged as alert events (local-only; no external
    # delivery).
    budget = store.budget_status(run.get("task_type"))
    if budget is not None:
        store.record_alert_transition(
            run["task_type"], budget["over_budget"],
            run_id=run.get("run_id"),
            cost_per_completed_task=budget["cost_per_completed_task"],
            budget_per_task=budget["budget_per_task"])
    return {"run_id": run.get("run_id"), "stored": True, "budget": budget}


@app.get("/summary")
def get_summary(since: str | None = None, until: str | None = None) -> dict:
    return store.summary(since=_parse_ts(since), until=_parse_ts(until))


@app.get("/runs")
def list_runs(task_type: str | None = None, status: str | None = None,
              limit: int = 100, offset: int = 0) -> dict:
    return {"runs": store.list_runs(task_type=task_type, status=status,
                                    limit=limit, offset=offset),
            "total": store.count_runs(task_type=task_type, status=status)}


@app.get("/runs/{run_id}",
         response_class=__import__("fastapi.responses",
                                   fromlist=["HTMLResponse"]).HTMLResponse)
def run_detail(run_id: str):
    from fastapi import HTTPException

    from .dashboard import render_run_detail

    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return render_run_detail(run)


@app.get("/", response_class=__import__("fastapi.responses", fromlist=["HTMLResponse"]).HTMLResponse)
def dashboard(since: str | None = None, until: str | None = None,
              task_type: str | None = None,
              runs_offset: int = 0) -> str:
    from .dashboard import render_dashboard

    s, u = _parse_ts(since), _parse_ts(until)
    return render_dashboard(store.summary(since=s, until=u),
                            store.list_runs(since=s, until=u,
                                            task_type=task_type,
                                            limit=50,
                                            offset=runs_offset),
                            store.list_alerts(limit=10),
                            task_type=task_type,
                            runs_total=store.count_runs(
                                task_type=task_type, since=s, until=u),
                            runs_offset=runs_offset,
                            chart_per_day=store.daily_cost(
                                task_type=task_type, since=s, until=u))


@app.post("/budgets", status_code=201, dependencies=[Depends(require_write_key)])
def set_budget(budget: dict) -> dict:
    store.set_budget(budget["task_type"], float(budget["max_cost_per_task"]))
    return {"stored": True}


@app.get("/alerts")
def get_alerts(limit: int = 50) -> dict:
    """Recent budget alert events (breach / recovered), newest first."""
    return {"alerts": store.list_alerts(limit=limit)}


@app.get("/budgets")
def get_budgets() -> dict:
    return {"budgets": store.list_budgets()}


MAX_SPEND_LOGS_PER_BATCH = 10_000


@app.post("/integrations/litellm/spend-logs", status_code=201,
          dependencies=[Depends(require_receiver_key)])
def receive_litellm_spend_logs(payload: dict) -> dict:
    """Accept an exported LiteLLM spend-log list and store it as runs.

    Always requires X-API-Key (fails closed when AGENTGUARD_API_KEY is
    unset). Local-only: bind the server to loopback. The importer stores a
    fixed whitelist of fields (model, token counts, spend, outcome/task
    tags) - prompts and arbitrary request metadata are never stored. Runs
    without an explicit completion signal import as unknown.
    """
    from agentguard.integrations.litellm import runs_from_spend_logs
    from fastapi import HTTPException

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="object payload required")
    logs = payload.get("spend_logs")
    if not isinstance(logs, list):
        raise HTTPException(status_code=422,
                            detail="spend_logs must be a list")
    if len(logs) > MAX_SPEND_LOGS_PER_BATCH:
        raise HTTPException(status_code=413,
                            detail="batch too large "
                                   f"(max {MAX_SPEND_LOGS_PER_BATCH})")
    if any(not isinstance(log, dict) for log in logs):
        raise HTTPException(status_code=422,
                            detail="each spend log must be an object")
    runs = runs_from_spend_logs(logs)
    for run in runs:
        store.put_run(run)
    return {"received_logs": len(logs), "stored_runs": len(runs),
            "run_ids": [r["run_id"] for r in runs]}
