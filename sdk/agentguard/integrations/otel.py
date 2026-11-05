"""Import OpenTelemetry spans into AgentGuard runs.

OpenTelemetry groups work into traces: one trace per task execution,
with spans underneath. A trace maps naturally to one AgentGuard run.
Model calls are detected via the GenAI semantic conventions
(`gen_ai.*` attributes); other spans are ignored for cost.

Cost: OTel spans carry no cost field, so every call is estimated from
the shipped pricing table (cost_basis="estimated-local"). Unknown
models contribute zero and the run is flagged unknown_cost=True in
metadata so the gap is visible rather than silently free.

Completion contract: like the other importers, a successful model call
is NOT proof the business task completed. Imported runs are "unknown"
unless any span in the trace carries an explicit outcome attribute:
agentguard_outcome="completed"/"failed" (agentguard.outcome also
accepted).

Attempt structure: spans don't map to AgentGuard attempts; each
imported run holds a single attempt with calls in time order.
"""
from __future__ import annotations

from ..pricing import PricingTable

_MODEL_KEYS = ("gen_ai.request.model", "gen_ai.response.model", "llm.model")
_IN_KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens")
_OUT_KEYS = ("gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens")


def _attrs(span: dict) -> dict:
    raw = span.get("attributes") or {}
    # OTLP JSON may encode attributes as a list of {key, value: {...}}
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            v = item.get("value")
            if isinstance(v, dict):  # {"intValue": n} / {"stringValue": s}
                v = next(iter(v.values()), None)
            out[item.get("key")] = v
        return out
    return raw if isinstance(raw, dict) else {}


def _ts(span: dict) -> float | None:
    nano = span.get("startTimeUnixNano")
    if nano is not None:
        try:
            return int(nano) / 1e9
        except (TypeError, ValueError):
            return None
    raw = span.get("start_time") or span.get("startTime")
    if raw and isinstance(raw, str):
        from datetime import datetime, timezone

        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    return None


def _first(attrs: dict, keys: tuple[str, ...]):
    for k in keys:
        v = attrs.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def _is_model_call(attrs: dict) -> bool:
    return any(attrs.get(k) for k in _MODEL_KEYS) or \
        bool(attrs.get("gen_ai.system"))


def _outcome(spans: list[dict]) -> str:
    """Explicit business-outcome signal, else 'unknown'."""
    for span in spans:
        attrs = _attrs(span)
        explicit = attrs.get("agentguard_outcome") or \
            attrs.get("agentguard.outcome")
        if explicit in ("completed", "failed"):
            return explicit
    return "unknown"


def runs_from_spans(spans: list[dict],
                    pricing: PricingTable | None = None) -> list[dict]:
    """Group OTel span dicts by trace into AgentGuard run payloads."""
    table = pricing or PricingTable()
    traces: dict[str, list[dict]] = {}
    for span in spans:
        trace_id = str(span.get("traceId") or span.get("trace_id") or "")
        if trace_id:
            traces.setdefault(trace_id, []).append(span)
    runs = []
    for trace_id, members in traces.items():
        ordered = sorted(members, key=lambda s: _ts(s) or 0.0)
        llm_calls, total, unknown_cost = [], 0.0, False
        for span in ordered:
            attrs = _attrs(span)
            if not _is_model_call(attrs):
                continue
            model = next((str(attrs[k]) for k in _MODEL_KEYS
                          if attrs.get(k)), "unknown")
            in_tok = _first(attrs, _IN_KEYS)
            out_tok = _first(attrs, _OUT_KEYS)
            try:
                cost = table.cost(model, in_tok, out_tok)
            except KeyError:
                cost, unknown_cost = 0.0, True
            total += cost
            call = {"model": model, "input_tokens": in_tok,
                    "output_tokens": out_tok, "cost_usd": cost,
                    "ts": _ts(span)}
            llm_calls.append({k: v for k, v in call.items()
                              if v is not None})
        roots = [s for s in ordered if not s.get("parentSpanId")]
        name = (roots or ordered)[0].get("name") or "otel"
        outcome = _outcome(members)
        runs.append({
            "run_id": f"otel-{trace_id}",
            "task_type": name,
            "status": outcome,
            "cost_usd": round(total, 6),
            "retry_count": 0,
            "attempts": [{
                "status": {"completed": "succeeded"}.get(outcome, outcome),
                "llm_calls": llm_calls,
                "tool_calls": [],
            }],
            "metadata": {
                "source": "opentelemetry",
                "cost_basis": "estimated-local" if not unknown_cost
                              else "partial",
                "unknown_cost": unknown_cost,
                "call_count": len(llm_calls),
            },
        })
    return runs
