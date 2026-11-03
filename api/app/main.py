"""AgentGuard ingestion + read-only aggregate API."""
from __future__ import annotations

from fastapi import Depends, FastAPI

from .auth import require_receiver_key, require_write_key

from .store import Store

app = FastAPI(title="AgentGuard", version="0.1.0")
store = Store()


@app.post("/runs", status_code=201, dependencies=[Depends(require_write_key)])
def ingest_run(run: dict) -> dict:
    store.put_run(run)
    return {"run_id": run.get("run_id"), "stored": True}


@app.get("/summary")
def get_summary() -> dict:
    return store.summary()


@app.get("/runs")
def list_runs(task_type: str | None = None, status: str | None = None,
              limit: int = 100) -> dict:
    return {"runs": store.list_runs(task_type=task_type, status=status,
                                    limit=limit)}


@app.get("/", response_class=__import__("fastapi.responses", fromlist=["HTMLResponse"]).HTMLResponse)
def dashboard() -> str:
    from .dashboard import render_dashboard

    return render_dashboard(store.summary(), store.list_runs())


@app.post("/budgets", status_code=201, dependencies=[Depends(require_write_key)])
def set_budget(budget: dict) -> dict:
    store.set_budget(budget["task_type"], float(budget["max_cost_per_task"]))
    return {"stored": True}


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
