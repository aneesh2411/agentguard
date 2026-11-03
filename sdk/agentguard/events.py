"""Event model: one task run, many attempts, many calls per attempt."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict


def _id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class LLMCall:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    ts: float = field(default_factory=time.time)


@dataclass
class ToolCall:
    name: str
    cost_usd: float = 0.0
    status: str = "ok"  # ok | error
    ts: float = field(default_factory=time.time)


@dataclass
class Attempt:
    attempt_id: str = field(default_factory=_id)
    llm_calls: list[LLMCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    status: str = "running"  # running | succeeded | failed

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.llm_calls) + sum(
            t.cost_usd for t in self.tool_calls
        )


@dataclass
class Run:
    task_type: str
    run_id: str = field(default_factory=_id)
    attempts: list[Attempt] = field(default_factory=list)
    status: str = "running"  # running | completed | failed
    metadata: dict = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        return sum(a.cost_usd for a in self.attempts)

    @property
    def retry_count(self) -> int:
        return max(0, len(self.attempts) - 1)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cost_usd"] = self.cost_usd
        d["retry_count"] = self.retry_count
        return d
