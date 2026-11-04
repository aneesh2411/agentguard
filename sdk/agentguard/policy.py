"""Budget policies: act on runaway spend while a run is still in flight.

Attach a BudgetPolicy to a RunTracker. After every recorded call the
tracker evaluates the policy against the run's total spend so far - all
attempts, retries included, since failed-attempt spend is real cost - and
acts on the highest crossed threshold:

- STOP: the run is marked failed and finished (its spend is still
  recorded and shipped to the sink/API), then BudgetExceeded is raised.
  The exception carries the PolicyDecision, so the caller sees the
  threshold, the spend, and the workflow it stopped.
- REQUIRE_APPROVAL: ApprovalRequired is raised, pausing the run before
  the call is recorded... it is not paused mid-call: the triggering
  call's cost IS recorded first, then the exception is raised. The
  caller obtains approval out of band and resumes with
  tracker.approve(). Recording another call before approving raises
  ApprovalRequired again.
- SWITCH_MODEL: no interruption. tracker.decision is updated and
  tracker.recommended_model(current) returns the fallback model.
  AgentGuard does not own the caller's model client, so the switch is
  the caller's action on the tracker's signal.

Each threshold fires once per run: after a switch signal or an approval,
the same threshold does not trigger again on later calls.

Costs are local estimates (see pricing.ESTIMATE_BASIS): thresholds
compare against estimated spend, not the provider invoice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Actions, in increasing severity.
SWITCH_MODEL = "switch_model"
REQUIRE_APPROVAL = "require_approval"
STOP = "stop"

_ACTIONS = {SWITCH_MODEL, REQUIRE_APPROVAL, STOP}


@dataclass(frozen=True)
class Threshold:
    """One budget line: when run spend reaches at_usd, take action."""
    at_usd: float
    action: str
    fallback_model: str | None = None  # required for SWITCH_MODEL

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise ValueError(f"unknown action {self.action!r}")
        if self.at_usd <= 0:
            raise ValueError("at_usd must be positive")
        if self.action == SWITCH_MODEL and not self.fallback_model:
            raise ValueError("SWITCH_MODEL needs a fallback_model")


@dataclass(frozen=True)
class PolicyDecision:
    """What the policy decided at a moment in the run."""
    action: str
    threshold_usd: float
    spend_usd: float
    task_type: str
    fallback_model: str | None = None


class BudgetExceeded(RuntimeError):
    """Raised when a STOP threshold is crossed. Carries the decision."""

    def __init__(self, decision: PolicyDecision):
        self.decision = decision
        super().__init__(
            f"budget exceeded on {decision.task_type!r}: "
            f"spend ${decision.spend_usd:.4f} reached "
            f"${decision.threshold_usd:.4f}; run stopped"
        )


class ApprovalRequired(RuntimeError):
    """Raised when a REQUIRE_APPROVAL threshold is crossed.

    Catch it, get approval, then call tracker.approve() to resume.
    """

    def __init__(self, decision: PolicyDecision):
        self.decision = decision
        super().__init__(
            f"approval required on {decision.task_type!r}: "
            f"spend ${decision.spend_usd:.4f} reached "
            f"${decision.threshold_usd:.4f}"
        )


@dataclass
class BudgetPolicy:
    """Ordered spend thresholds for one workflow.

        policy = BudgetPolicy("support_ticket", thresholds=[
            Threshold(1.00, SWITCH_MODEL, fallback_model="gpt-4o-mini"),
            Threshold(5.00, REQUIRE_APPROVAL),
            Threshold(10.00, STOP),
        ])
    """
    task_type: str
    thresholds: list[Threshold] = field(default_factory=list)
    _fired: set[float] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        ats = [t.at_usd for t in self.thresholds]
        if len(set(ats)) != len(ats):
            raise ValueError("duplicate threshold amounts")

    def evaluate(self, spend_usd: float) -> Threshold | None:
        """Highest crossed threshold not yet fired, else None."""
        crossed = [t for t in sorted(self.thresholds, key=lambda t: -t.at_usd)
                   if spend_usd >= t.at_usd and t.at_usd not in self._fired]
        if not crossed:
            return None
        top = crossed[0]
        # Lower crossed thresholds are superseded; none of them fire later.
        for t in crossed:
            self._fired.add(t.at_usd)
        return top

    def mark_fired(self, at_usd: float) -> None:
        self._fired.add(at_usd)
