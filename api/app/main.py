"""AgentGuard ingestion + read-only aggregate API."""
from __future__ import annotations

from fastapi import FastAPI

from .store import Store

app = FastAPI(title="AgentGuard", version="0.1.0")
store = Store()


@app.post("/runs", status_code=201)
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
