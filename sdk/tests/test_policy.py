"""Budget policy guard: switch-model signal, approval pause, hard stop."""
import json

import pytest

from agentguard import (
    ApprovalRequired,
    BudgetExceeded,
    BudgetPolicy,
    RunTracker,
    Threshold,
)
from agentguard.policy import REQUIRE_APPROVAL, STOP, SWITCH_MODEL


def policy(**over):
    kwargs = dict(
        task_type="support_ticket",
        thresholds=[
            Threshold(0.10, SWITCH_MODEL, fallback_model="gpt-4o-mini"),
            Threshold(0.50, REQUIRE_APPROVAL),
            Threshold(1.00, STOP),
        ],
    )
    kwargs.update(over)
    return BudgetPolicy(**kwargs)


def test_no_policy_is_unchanged():
    t = RunTracker("support_ticket")
    t.llm("gpt-4o", 100_000, 100_000)
    assert t.decision is None
    assert t.recommended_model("gpt-4o") == "gpt-4o"


def test_under_budget_no_decision():
    t = RunTracker("support_ticket", policy=policy())
    t.llm("gpt-4o-mini", 1_000, 1_000)  # $0.00075
    assert t.decision is None


def test_switch_model_signals_without_interrupting():
    t = RunTracker("support_ticket", policy=policy())
    # gpt-4o: $2.50/$10.00 per 1M -> 40k in / 10k out = $0.20
    t.llm("gpt-4o", 40_000, 10_000)
    assert t.decision is not None
    assert t.decision.action == SWITCH_MODEL
    assert t.decision.fallback_model == "gpt-4o-mini"
    assert t.recommended_model("gpt-4o") == "gpt-4o-mini"
    # Run continues normally on the signal.
    run = t.complete()
    assert run.status == "completed"


def test_threshold_fires_once():
    t = RunTracker("support_ticket", policy=policy())
    t.llm("gpt-4o", 40_000, 10_000)  # $0.20 -> switch fired
    t.llm("gpt-4o-mini", 1_000, 1_000)
    # Still the same single decision; evaluate did not re-fire it.
    assert t.decision.threshold_usd == 0.10


def test_require_approval_pauses_then_approve_resumes():
    t = RunTracker("support_ticket", policy=policy())
    with pytest.raises(ApprovalRequired) as exc:
        t.llm("gpt-4o", 200_000, 10_000)  # $0.60
    assert exc.value.decision.action == REQUIRE_APPROVAL
    assert exc.value.decision.spend_usd == pytest.approx(0.60)
    # The triggering call's cost was recorded before pausing.
    assert t.run.cost_usd == pytest.approx(0.60)
    # Further calls keep raising until approved.
    with pytest.raises(ApprovalRequired):
        t.llm("gpt-4o-mini", 1_000, 1_000)
    t.approve()
    t.llm("gpt-4o-mini", 1_000, 1_000)  # resumes cleanly
    assert t.complete().status == "completed"


def test_highest_crossed_threshold_wins():
    # One call blows past switch and approval straight into stop.
    t = RunTracker("support_ticket", policy=policy())
    with pytest.raises(BudgetExceeded) as exc:
        t.llm("gpt-4o", 500_000, 10_000)  # $1.35
    assert exc.value.decision.action == STOP
    assert t.run.status == "failed"
    assert t.run.metadata["stopped_by"] == "budget_policy"


def test_stop_records_spend_to_sink(tmp_path):
    sink = tmp_path / "runs.jsonl"
    t = RunTracker("support_ticket", sink=sink, policy=policy())
    t.llm("gpt-4o", 40_000, 10_000)  # $0.20, switch fires
    with pytest.raises(BudgetExceeded):
        t.llm("gpt-4o", 500_000, 10_000)  # +$1.35 -> stop
    lines = sink.read_text().strip().splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["status"] == "failed"
    assert stored["cost_usd"] == pytest.approx(1.55)
    assert stored["metadata"]["stopped_by"] == "budget_policy"
    assert stored["metadata"]["stop_threshold_usd"] == 1.00


def test_spend_accumulates_across_retries():
    # Failed-attempt spend is real cost: the retry attempt's budget check
    # counts what the failed attempt already burned.
    p = BudgetPolicy("support_ticket", thresholds=[Threshold(1.00, STOP)])
    t = RunTracker("support_ticket", policy=p)
    t.llm("gpt-4o", 300_000, 10_000)  # $0.85
    t.fail(retry=True)
    with pytest.raises(BudgetExceeded):
        t.llm("gpt-4o", 300_000, 10_000)  # total $1.70 -> stop
    assert t.run.status == "failed"
    assert t.run.retry_count == 1


def test_policy_task_type_must_match_tracker():
    with pytest.raises(ValueError):
        RunTracker("other_task", policy=policy())


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        Threshold(1.00, "explode")
    with pytest.raises(ValueError):
        Threshold(1.00, SWITCH_MODEL)  # needs fallback_model
    with pytest.raises(ValueError):
        BudgetPolicy("t", thresholds=[Threshold(1.0, STOP),
                                      Threshold(1.0, STOP)])
