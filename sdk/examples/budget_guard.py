"""Budget guard: switch models, pause for approval, hard stop.

A policy watches the run's total estimated spend while work is in flight.
Run it:  python sdk/examples/budget_guard.py
"""
from agentguard import (
    ApprovalRequired,
    BudgetExceeded,
    BudgetPolicy,
    RunTracker,
    Threshold,
)


def make_policy():
    return BudgetPolicy("support_ticket", thresholds=[
        # Past $0.10: signal the caller to move to a cheaper model.
        Threshold(0.10, "switch_model", fallback_model="gpt-4o-mini"),
        # Past $0.50: pause until a human approves more spend.
        Threshold(0.50, "require_approval"),
        # Past $1.00: stop the run; spend so far is still recorded.
        Threshold(1.00, "stop"),
    ])


def work(t, steps=10):
    """A fake agent loop: one LLM call per step."""
    model = "gpt-4o"
    for _ in range(steps):
        try:
            t.llm(model, input_tokens=40_000, output_tokens=10_000)
        except ApprovalRequired as e:
            print(f"  paused at ${e.decision.spend_usd:.2f}; approving for the demo")
            t.approve()
        except BudgetExceeded as e:
            print(f"  STOPPED: {e}")
            return
        model = t.recommended_model(model)


print("Run 1: caller follows the switch signal")
with RunTracker("support_ticket", sink="runs.jsonl", policy=make_policy()) as t:
    work(t)
print(f"  status={t.run.status} spend=${t.run.cost_usd:.4f} (cheap model kept it under budget)")

print("Run 2: caller ignores the switch signal")
with RunTracker("support_ticket", sink="runs.jsonl", policy=make_policy()) as t:
    model = "gpt-4o"
    for _ in range(10):
        try:
            t.llm(model, input_tokens=40_000, output_tokens=10_000)
        except ApprovalRequired as e:
            print(f"  paused at ${e.decision.spend_usd:.2f}; approving for the demo")
            t.approve()
        except BudgetExceeded as e:
            print(f"  STOPPED: {e}")
            break
print(f"  status={t.run.status} spend=${t.run.cost_usd:.4f} (failed run, spend still recorded)")
