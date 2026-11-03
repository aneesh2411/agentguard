from agentguard.integrations.litellm import runs_from_spend_logs

LOGS = [
    {"request_id": "a1", "model": "gpt-4o-mini", "prompt_tokens": 100,
     "completion_tokens": 50, "spend": 0.0001, "status": "success",
     "startTime": "2026-11-02T10:00:00",
     "metadata": {"trace_id": "t1", "tags": ["taskName:support_ticket"]}},
    {"request_id": "a2", "model": "gpt-4o", "prompt_tokens": 200,
     "completion_tokens": 80, "spend": 0.0013, "status": "failure",
     "startTime": "2026-11-02T10:00:05",
     "metadata": {"trace_id": "t1", "tags": ["taskName:support_ticket"]}},
    {"request_id": "a3", "model": "gpt-4o-mini", "prompt_tokens": 120,
     "completion_tokens": 60, "spend": 0.0001, "status": "success",
     "startTime": "2026-11-02T10:00:09",
     "metadata": {"trace_id": "t1", "tags": ["taskName:support_ticket",
                                              "taskStatus:completed"]}},
    {"request_id": "b1", "model": "gpt-4o", "prompt_tokens": 500,
     "completion_tokens": 0, "spend": 0.0013, "status": "failure",
     "startTime": "2026-11-02T10:01:00", "metadata": {}},
]


def test_groups_by_trace_and_uses_litellm_spend():
    runs = runs_from_spend_logs(LOGS)
    assert len(runs) == 2
    t1 = next(r for r in runs if r["run_id"] == "litellm-t1")
    assert t1["task_type"] == "support_ticket"
    assert t1["status"] == "completed"  # explicit taskStatus tag
    assert abs(t1["cost_usd"] - 0.0015) < 1e-9  # LiteLLM spend, not our table
    assert len(t1["attempts"][0]["llm_calls"]) == 3  # multi-call accumulation


def test_no_completion_signal_means_unknown_not_completed():
    orphan = next(r for r in runs_from_spend_logs(LOGS)
                  if r["run_id"] == "litellm-b1")
    assert orphan["task_type"] == "litellm"
    assert orphan["status"] == "unknown"  # last call failed, but no signal


def test_last_call_success_is_not_business_completion():
    logs = [{"request_id": "c1", "spend": 0.01, "status": "success",
             "metadata": {"trace_id": "t2"}}]
    assert runs_from_spend_logs(logs)[0]["status"] == "unknown"


def test_explicit_failed_overrides_successful_last_call():
    logs = [{"request_id": "d1", "spend": 0.01, "status": "success",
             "metadata": {"trace_id": "t3",
                          "agentguard_outcome": "failed"}}]
    assert runs_from_spend_logs(logs)[0]["status"] == "failed"


def test_partial_import_keeps_spend_and_stays_unknown():
    # Only the first call of a trace has arrived so far.
    partial = runs_from_spend_logs(LOGS[:1])
    t1 = next(r for r in partial if r["run_id"] == "litellm-t1")
    assert t1["status"] == "unknown"
    assert abs(t1["cost_usd"] - 0.0001) < 1e-9


def test_dedupes_repeat_import_and_labels_cost_basis():
    runs = runs_from_spend_logs(LOGS + LOGS)  # same logs imported twice
    t1 = next(r for r in runs if r["run_id"] == "litellm-t1")
    assert len(t1["attempts"][0]["llm_calls"]) == 3  # not 6
    assert t1["metadata"]["cost_basis"] == "provider-reported"


def test_start_time_becomes_event_ts():
    runs = runs_from_spend_logs(LOGS)
    t1 = next(r for r in runs if r["run_id"] == "litellm-t1")
    ts = [c["ts"] for c in t1["attempts"][0]["llm_calls"]]
    assert ts == sorted(ts)
    from datetime import datetime, timezone
    expect = datetime(2026, 11, 2, 10, 0, 0,
                      tzinfo=timezone.utc).timestamp()
    assert ts[0] == expect


def test_missing_start_time_omits_ts():
    runs = runs_from_spend_logs([{"request_id": "n1", "spend": 0.01,
                                  "metadata": {"trace_id": "nt"}}])
    assert "ts" not in runs[0]["attempts"][0]["llm_calls"][0]
