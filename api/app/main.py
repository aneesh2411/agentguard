"""AgentGuard ingestion + read-only aggregate API."""
from __future__ import annotations

from fastapi import Depends, FastAPI

from .auth import require_write_key

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
