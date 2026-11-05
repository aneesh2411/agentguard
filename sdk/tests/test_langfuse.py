"""Langfuse trace import tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentguard.integrations.langfuse import runs_from_traces  # noqa: E402

TRACE = {
    "id": "trace-1",
    "name": "support_ticket",
    "tags": ["taskStatus:completed"],
    "metadata": {},
    "observations": [
        {"id": "o2", "type": "GENERATION", "model": "gpt-4o-mini",
         "startTime": "2026-11-01T10:00:10Z",
         "usage": {"input": 1000, "output": 200}},
        {"id": "o1", "type": "GENERATION", "model": "gpt-4o",
         "startTime": "2026-11-01T10:00:00Z",
         "usage": {"input": 2000, "output": 500},
         "calculatedTotalCost": 0.01},
        {"id": "o3", "type": "SPAN", "startTime": "2026-11-01T10:00:05Z"},
    ],
}


def test_trace_maps_to_one_run():
    runs = runs_from_traces([TRACE])
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == "langfuse-trace-1"
    assert run["task_type"] == "support_ticket"
    assert run["status"] == "completed"
    calls = run["attempts"][0]["llm_calls"]
    assert len(calls) == 2  # SPAN excluded
    assert calls[0]["model"] == "gpt-4o"  # sorted by startTime
    # o1 provider-reported 0.01 + o2 estimated (1000*.15+200*.60)/1M = 0.00027
    assert abs(run["cost_usd"] - 0.01027) < 1e-9
    assert run["metadata"]["cost_basis"] == "mixed"


def test_outcome_unknown_without_signal():
    t = {**TRACE, "tags": [], "metadata": {}}
    assert runs_from_traces([t])[0]["status"] == "unknown"


def test_unknown_model_flagged_not_free():
    t = {**TRACE, "observations": [
        {"type": "GENERATION", "model": "some-new-model",
         "usage": {"input": 100, "output": 50}}]}
    run = runs_from_traces([t])[0]
    assert run["cost_usd"] == 0.0
    assert run["metadata"]["unknown_cost"] is True
