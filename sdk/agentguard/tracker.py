"""RunTracker: wrap one unit of agent work and price it."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .events import Attempt, Run
from .policy import (
    REQUIRE_APPROVAL,
    STOP,
    SWITCH_MODEL,
    ApprovalRequired,
    BudgetExceeded,
    BudgetPolicy,
    PolicyDecision,
)
from .pricing import PricingTable


class RunTracker:
    """Track one task run. Usage:

        with RunTracker("support_ticket", sink="runs.jsonl") as t:
            t.llm("gpt-4o-mini", input_tokens=800, output_tokens=200)
            t.tool("zendesk_lookup")
            t.complete()          # or t.fail() -> retry via t.retry()

    With a BudgetPolicy attached, every recorded call is checked against
    the run's total spend; see agentguard.policy for the action semantics.
    """

    def __init__(
        self,
        task_type: str,
        sink: str | Path | None = None,
        api_url: str | None = None,
        pricing: PricingTable | None = None,
        metadata: dict | None = None,
        policy: BudgetPolicy | None = None,
    ):
        self.run = Run(task_type=task_type, metadata=metadata or {})
        self.run.metadata.setdefault("cost_basis", "estimated-local")
        self.pricing = pricing or PricingTable()
        self.sink = Path(sink) if sink else None
        self.api_url = api_url
        if policy is not None and policy.task_type != task_type:
            raise ValueError(
                f"policy is for {policy.task_type!r}, not {task_type!r}")
        self.policy = policy
        self._decision: PolicyDecision | None = None
        self._awaiting_approval = False
        self._attempt = self._new_attempt()

    def _new_attempt(self) -> Attempt:
        a = Attempt()
        self.run.attempts.append(a)
        return a

    @property
    def decision(self) -> PolicyDecision | None:
        """Latest non-stop policy decision, if any threshold has fired."""
        return self._decision

    def recommended_model(self, current: str) -> str:
        """Fallback model once a SWITCH_MODEL threshold fired, else current."""
        if self._decision is not None and self._decision.action == SWITCH_MODEL:
            return self._decision.fallback_model or current
        return current

    def approve(self) -> None:
        """Resume a run paused by a REQUIRE_APPROVAL threshold."""
        self._awaiting_approval = False

    def llm(self, model: str, input_tokens: int, output_tokens: int) -> float:
        cost = self.pricing.cost(model, input_tokens, output_tokens)
        from .events import LLMCall

        self._attempt.llm_calls.append(LLMCall(model, input_tokens, output_tokens, cost))
        self._evaluate_policy()
        return cost

    def tool(self, name: str, cost_usd: float = 0.0, status: str = "ok") -> None:
        from .events import ToolCall

        self._attempt.tool_calls.append(ToolCall(name, cost_usd, status))
        self._evaluate_policy()

    def _evaluate_policy(self) -> None:
        if self.policy is None:
            return
        if self._awaiting_approval:
            raise ApprovalRequired(self._decision)
        spend = self.run.cost_usd
        threshold = self.policy.evaluate(spend)
        if threshold is None:
            return
        decision = PolicyDecision(
            action=threshold.action,
            threshold_usd=threshold.at_usd,
            spend_usd=spend,
            task_type=self.run.task_type,
            fallback_model=threshold.fallback_model,
        )
        if threshold.action == STOP:
            self.run.metadata["stopped_by"] = "budget_policy"
            self.run.metadata["stop_threshold_usd"] = threshold.at_usd
            # Fail and finish first so the runaway spend is recorded and
            # shipped before the caller sees the error.
            self.fail()
            raise BudgetExceeded(decision)
        self._decision = decision
        if threshold.action == REQUIRE_APPROVAL:
            self._awaiting_approval = True
            raise ApprovalRequired(decision)
        # SWITCH_MODEL: signal only; the caller reads decision /
        # recommended_model and switches its own client.

    def complete(self) -> Run:
        self._attempt.status = "succeeded"
        self.run.status = "completed"
        return self._finish()

    def fail(self, retry: bool = False) -> Run | None:
        self._attempt.status = "failed"
        if retry:
            self._attempt = self._new_attempt()
            return None
        self.run.status = "failed"
        return self._finish()

    def _finish(self) -> Run:
        payload = json.dumps(self.run.to_dict())
        if self.sink:
            with self.sink.open("a") as f:
                f.write(payload + "\n")
        if self.api_url:
            req = urllib.request.Request(
                self.api_url.rstrip("/") + "/runs",
                data=payload.encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        return self.run

    def __enter__(self) -> "RunTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.run.status == "running":
            self.fail() if exc else self.complete()
        return False
