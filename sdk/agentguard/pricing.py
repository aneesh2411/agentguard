"""Model pricing table and cost computation.

Rates are USD per 1M tokens. They are placeholders gathered for the scaffold
(2026-11) - verify against each provider's current pricing page before
reporting real dollar figures to anyone. Override at runtime with
`PricingTable.set()` or a custom table passed to RunTracker.
"""
from __future__ import annotations

# (input_per_1m, output_per_1m)
DEFAULT_RATES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-3.5": (0.80, 4.00),
    "gemini-2.0-flash": (0.10, 0.40),
}


class PricingTable:
    def __init__(self, rates: dict[str, tuple[float, float]] | None = None):
        self._rates = dict(DEFAULT_RATES if rates is None else rates)

    def set(self, model: str, input_per_1m: float, output_per_1m: float) -> None:
        self._rates[model] = (input_per_1m, output_per_1m)

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Return USD cost. Unknown models raise so nothing is silently free."""
        if model not in self._rates:
            raise KeyError(f"no pricing for model {model!r}; add it to the table")
        in_rate, out_rate = self._rates[model]
        return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
