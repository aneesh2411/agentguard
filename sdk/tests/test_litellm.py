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
     "metadata": {"trace_id": "t1", "tags": ["taskName:support_ticket"]}},
    {"request_id": "b1", "model": "gpt-4o", "prompt_tokens": 500,
     "completion_tokens": 0, "spend": 0.0013, "status": "failure",
     "startTime": "2026-11-02T10:01:00", "metadata": {}},
]


def test_groups_by_trace_and_uses_litellm_spend():
    runs = runs_from_spend_logs(LOGS)
    assert len(runs) == 2
    t1 = next(r for r in runs if r["run_id"] == "litellm-t1")
    assert t1["task_type"] == "support_ticket"
    assert t1["status"] == "completed"  # last call succeeded
    assert abs(t1["cost_usd"] - 0.0015) < 1e-9  # LiteLLM spend, not our table
    assert len(t1["attempts"][0]["llm_calls"]) == 3


def test_failed_run_and_fallback_grouping():
    runs = runs_from_spend_logs(LOGS)
    orphan = next(r for r in runs if r["run_id"] == "litellm-b1")
    assert orphan["task_type"] == "litellm"  # no taskName tag
    assert orphan["status"] == "failed"
