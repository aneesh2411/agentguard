"""Model pricing table and cost computation.

Rates are USD per 1M tokens (standard tier, input / output), verified
2026-11-02 against the providers' pricing pages:
- OpenAI:    platform.openai.com/docs/pricing
- Anthropic: docs.anthropic.com/en/docs/about-claude/pricing
- Google:    ai.google.dev/gemini-api/docs/pricing

Prices change; re-verify before quoting dollar figures to customers.
Override at runtime with PricingTable.set() or a custom table.
"""
from __future__ import annotations

VERIFIED_ON = "2026-11-02"

# (input_per_1m, output_per_1m)
DEFAULT_RATES: dict[str, tuple[float, float]] = {
    # OpenAI (standard tier)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    # Anthropic (base input / output)
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4.5": (1.00, 5.00),
    # Retired on first-party API; still served on Bedrock/Google Cloud:
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-3.5": (0.80, 4.00),
    # Google: promo through 2026-12-31, then $1.50 / $7.50
    "gemini-3.8-flash": (0.75, 3.75),
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
