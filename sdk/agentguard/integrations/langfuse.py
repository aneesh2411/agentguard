"""Import Langfuse traces into AgentGuard runs.

Langfuse (langfuse.com) groups LLM work into traces: one trace per task
execution, with observations (GENERATION for model calls, SPAN/EVENT for
other steps) underneath. A trace maps naturally to one AgentGuard run.

Cost: Langfuse computes calculatedTotalCost per generation when it knows
the model's pricing; those provider-reported dollars are used as-is
(cost_basis="provider-reported"). Generations without a Langfuse cost
are estimated from the shipped pricing table (cost_basis notes "mixed"
when both sources appear in one run); unknown models contribute zero and
the run is flagged unknown_cost=True in metadata so the gap is visible
rather than silently free.

Completion contract: like LiteLLM imports, a successful model call is
NOT proof the business task completed. Imported runs are "unknown"
unless the trace carries an explicit outcome: metadata
agentguard_outcome="completed"/"failed", or a "taskStatus:<state>" tag.

Attempt structure: Langfuse SPANs don't map to AgentGuard attempts;
each imported run holds a single attempt with calls in time order.
"""
from __future__ import annotations

from ..pricing import PricingTable


def _ts(obs: dict) -> float | None:
    raw = obs.get("startTime") or obs.get("start_time")
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


def _outcome(trace: dict) -> str:
    """Explicit business-outcome signal, else 'unknown'."""
    meta = trace.get("metadata") or {}
    explicit = meta.get("agentguard_outcome")
    for tag in trace.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("taskStatus:"):
            explicit = tag.split(":", 1)[1]
    return explicit if explicit in ("completed", "failed") else "unknown"


def runs_from_traces(traces: list[dict],
                     pricing: PricingTable | None = None) -> list[dict]:
    """Group Langfuse trace dicts into AgentGuard run payloads."""
    table = pricing or PricingTable()
    runs = []
    for trace in traces:
        trace_id = str(trace.get("id") or trace.get("trace_id"))
        observations = sorted(
            (o for o in (trace.get("observations") or [])
             if o.get("type") == "GENERATION"),
            key=lambda o: o.get("startTime") or o.get("start_time") or "")
        llm_calls, reported, estimated, unknown_cost = [], 0.0, 0.0, False
        for o in observations:
            usage = o.get("usage") or {}
            model = o.get("model") or "unknown"
            in_tok = usage.get("input") or usage.get("promptTokens") or 0
            out_tok = usage.get("output") or usage.get("completionTokens") or 0
            cost = o.get("calculatedTotalCost")
            if isinstance(cost, (int, float)):
                reported += cost
            else:
                try:
                    cost = table.cost(model, in_tok, out_tok)
                    estimated += cost
                except KeyError:
                    cost, unknown_cost = 0.0, True
            call = {"model": model, "input_tokens": in_tok,
                    "output_tokens": out_tok, "cost_usd": cost,
                    "ts": _ts(o)}
            llm_calls.append({k: v for k, v in call.items()
                              if v is not None})
        basis = ("provider-reported" if not estimated and not unknown_cost
                 else "mixed" if reported else
                 "estimated-local" if not unknown_cost else "partial")
        outcome = _outcome(trace)
        runs.append({
            "run_id": f"langfuse-{trace_id}",
            "task_type": trace.get("name") or "langfuse",
            "status": outcome,
            "cost_usd": round(reported + estimated, 6),
            "retry_count": 0,
            "attempts": [{
                "status": {"completed": "succeeded"}.get(outcome, outcome),
                "llm_calls": llm_calls,
                "tool_calls": [],
            }],
            "metadata": {
                "source": "langfuse",
                "cost_basis": basis,
                "unknown_cost": unknown_cost,
                "call_count": len(llm_calls),
            },
        })
    return runs
