"""OpenTelemetry span import tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentguard.integrations.otel import runs_from_spans  # noqa: E402

SPANS = [
    {"traceId": "t1", "spanId": "root", "name": "support_ticket",
     "startTimeUnixNano": "1762087200000000000",
     "attributes": {"agentguard_outcome": "completed"}},
    {"traceId": "t1", "spanId": "s2", "parentSpanId": "root",
     "name": "chat",
     "startTimeUnixNano": "1762087210000000000",
     "attributes": {"gen_ai.system": "openai",
                    "gen_ai.request.model": "gpt-4o-mini",
                    "gen_ai.usage.input_tokens": 1000,
                    "gen_ai.usage.output_tokens": 200}},
    {"traceId": "t1", "spanId": "s3", "parentSpanId": "root",
     "name": "db lookup",
     "startTimeUnixNano": "1762087205000000000",
     "attributes": {"db.system": "sqlite"}},
    {"traceId": "t2", "spanId": "s4", "name": "invoice",
     "startTimeUnixNano": "1762087300000000000",
     "attributes": {"gen_ai.request.model": "gpt-4o",
                    "gen_ai.usage.input_tokens": 2000,
                    "gen_ai.usage.output_tokens": 500}},
]


def test_spans_group_by_trace():
    runs = runs_from_spans(SPANS)
    assert len(runs) == 2
    by_id = {r["run_id"]: r for r in runs}
    r1 = by_id["otel-t1"]
    assert r1["task_type"] == "support_ticket"  # root span name
    assert r1["status"] == "completed"
    calls = r1["attempts"][0]["llm_calls"]
    assert len(calls) == 1  # db span excluded
    # (1000*.15 + 200*.60)/1M = 0.00027
    assert abs(r1["cost_usd"] - 0.00027) < 1e-9
    assert r1["metadata"]["cost_basis"] == "estimated-local"


def test_second_trace_estimated():
    r2 = {r["run_id"]: r for r in runs_from_spans(SPANS)}["otel-t2"]
    # gpt-4o: (2000*2.50 + 500*10.0)/1M = 0.01
    assert abs(r2["cost_usd"] - 0.01) < 1e-9
    assert r2["status"] == "unknown"  # no outcome signal


def test_unknown_model_flagged_not_free():
    spans = [{"traceId": "t3", "spanId": "s", "name": "x",
              "attributes": {"gen_ai.request.model": "some-new-model",
                             "gen_ai.usage.input_tokens": 100,
                             "gen_ai.usage.output_tokens": 50}}]
    run = runs_from_spans(spans)[0]
    assert run["cost_usd"] == 0.0
    assert run["metadata"]["unknown_cost"] is True
    assert run["metadata"]["cost_basis"] == "partial"


def test_otlp_list_attributes_and_iso_time():
    spans = [{"trace_id": "t4", "name": "enc",
              "start_time": "2026-11-01T10:00:00Z",
              "attributes": [
                  {"key": "gen_ai.request.model",
                   "value": {"stringValue": "gpt-4o-mini"}},
                  {"key": "gen_ai.usage.input_tokens",
                   "value": {"intValue": 100}},
              ]}]
    run = runs_from_spans(spans)[0]
    call = run["attempts"][0]["llm_calls"][0]
    assert call["model"] == "gpt-4o-mini"
    assert call["input_tokens"] == 100
    assert abs(call["ts"] - 1793527200.0) < 1e-6
