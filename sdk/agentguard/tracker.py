"""RunTracker: wrap one unit of agent work and price it."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .events import Attempt, Run
from .pricing import PricingTable


class RunTracker:
    """Track one task run. Usage:

        with RunTracker("support_ticket", sink="runs.jsonl") as t:
            t.llm("gpt-4o-mini", input_tokens=800, output_tokens=200)
            t.tool("zendesk_lookup")
            t.complete()          # or t.fail() -> retry via t.retry()
    """

    def __init__(
        self,
        task_type: str,
        sink: str | Path | None = None,
        api_url: str | None = None,
        pricing: PricingTable | None = None,
        metadata: dict | None = None,
    ):
        self.run = Run(task_type=task_type, metadata=metadata or {})
        self.pricing = pricing or PricingTable()
        self.sink = Path(sink) if sink else None
        self.api_url = api_url
        self._attempt = self._new_attempt()

    def _new_attempt(self) -> Attempt:
        a = Attempt()
        self.run.attempts.append(a)
        return a

    def llm(self, model: str, input_tokens: int, output_tokens: int) -> float:
        cost = self.pricing.cost(model, input_tokens, output_tokens)
        from .events import LLMCall

        self._attempt.llm_calls.append(LLMCall(model, input_tokens, output_tokens, cost))
        return cost

    def tool(self, name: str, cost_usd: float = 0.0, status: str = "ok") -> None:
        from .events import ToolCall

        self._attempt.tool_calls.append(ToolCall(name, cost_usd, status))

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
