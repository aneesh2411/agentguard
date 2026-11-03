"""Import LiteLLM proxy SpendLogs into AgentGuard runs.

LiteLLM logs one record per LLM call, with LiteLLM's own computed `spend`
(actual billed cost), token usage, status, and the request metadata the
caller sent. Callers can tag requests with metadata like
{"trace_id": "...", "tags": ["taskName:support_ticket"]}
(docs.litellm.ai/docs/proxy/logging), which is how calls group into runs.

Grouping (configurable):
- run:      metadata trace_id (fallback: request_id, one run per call)
- workflow: "taskName:<name>" tag (fallback: "litellm")

Attempt structure is not recoverable from spend logs, so each imported run
holds a single attempt with calls in time order.

Completion contract: a successful model call is NOT proof the business task
completed. Imported runs are "unknown" unless the caller sends an explicit
outcome signal in request metadata: agentguard_outcome="completed"/"failed",
or a "taskStatus:completed"/"taskStatus:failed" tag. Unknown runs keep their
spend but are excluded from the completed-task denominator.

Cost basis: run metadata carries cost_basis="provider-reported" - these
dollars come from LiteLLM's computed spend, not AgentGuard's shipped
pricing-table estimate. Duplicate request_ids are deduplicated on import.
"""
from __future__ import annotations


def _start_ts(log: dict) -> float | None:
    """Event time from LiteLLM's startTime (ISO), as unix seconds."""
    raw = log.get("startTime") or log.get("start_time")
    if not raw or not isinstance(raw, str):
        return None
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _meta(log: dict) -> dict:
    return (log.get("metadata") or log.get("request_metadata") or {})


def _outcome(logs: list[dict]) -> str:
    """Explicit business-outcome signal, else 'unknown'. Last signal wins."""
    outcome = "unknown"
    for log in logs:
        meta = _meta(log)
        explicit = meta.get("agentguard_outcome")
        for tag in meta.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("taskStatus:"):
                explicit = tag.split(":", 1)[1]
        if explicit in ("completed", "failed"):
            outcome = explicit
    return outcome


def _task_type(log: dict, tag_prefix: str) -> str:
    for tag in _meta(log).get("tags") or []:
        if isinstance(tag, str) and tag.startswith(tag_prefix + ":"):
            return tag.split(":", 1)[1]
    return "litellm"


def runs_from_spend_logs(
    logs: list[dict],
    run_id_field: str = "trace_id",
    task_type_tag: str = "taskName",
) -> list[dict]:
    """Group LiteLLM spend-log dicts into AgentGuard run payloads."""
    groups: dict[str, list[dict]] = {}
    seen_request_ids: set[str] = set()
    for log in logs:
        rid = log.get("request_id")
        if rid is not None and rid in seen_request_ids:
            continue  # idempotent re-import
        if rid is not None:
            seen_request_ids.add(rid)
        key = str(_meta(log).get(run_id_field) or rid)
        groups.setdefault(key, []).append(log)

    runs = []
    for run_id, calls in groups.items():
        calls.sort(key=lambda c: c.get("startTime") or c.get("start_time") or "")
        llm_calls = [
            {
                "model": c.get("model", "unknown"),
                "input_tokens": c.get("prompt_tokens", 0),
                "output_tokens": c.get("completion_tokens", 0),
                "cost_usd": c.get("spend", 0.0),  # LiteLLM's computed cost
                "ts": _start_ts(c),
            }
            for c in calls
        ]
        llm_calls = [{k: v for k, v in c.items() if v is not None}
                     for c in llm_calls]
        total = round(sum(c["cost_usd"] for c in llm_calls), 6)
        outcome = _outcome(calls)
        runs.append({
            "run_id": f"litellm-{run_id}",
            "task_type": _task_type(calls[0], task_type_tag),
            "status": outcome,
            "cost_usd": total,
            "retry_count": 0,
            "attempts": [{
                "status": {"completed": "succeeded"}.get(outcome, outcome),
                "llm_calls": llm_calls,
                "tool_calls": [],
            }],
            "metadata": {
                "source": "litellm",
                "cost_basis": "provider-reported",
                "call_count": len(calls),
            },
        })
    return runs
