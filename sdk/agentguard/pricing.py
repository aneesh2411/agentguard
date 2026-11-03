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

CURRENCY = "USD"

# What a computed cost IS: an estimate of standard-tier, uncached token
# usage at the shipped rates. What it is NOT: an exact provider invoice.
# Cached-input discounts, batch/flex/priority tiers, thinking-token
# surcharges, and tool or provider fees can materially change the real bill.
ESTIMATE_BASIS = (
    "estimate: standard-tier uncached tokens, USD per 1M, shipped table "
    f"verified {VERIFIED_ON}; excludes cached/batch/priority tiers, "
    "thinking surcharges, and tool fees"
)

SOURCES = {
    "openai": "https://platform.openai.com/docs/pricing",
    "anthropic": "https://docs.anthropic.com/en/docs/about-claude/pricing",
    "google": "https://ai.google.dev/gemini-api/docs/pricing",
}

# Rates with a published expiry: model -> (last promo day, promo rate,
# standard rate after). Checked at call time so costs switch over instead
# of silently undercounting after the promo ends.
EXPIRING_RATES = {
    "gemini-3.8-flash": ("2026-12-31", (0.75, 3.75), (1.50, 7.50)),
}

# (input_per_1m, output_per_1m)
DEFAULT_RATES: dict[str, tuple[float, float]] = {
    # OpenAI (standard tier)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    # Anthropic (base input / output; keys are exact Claude API IDs/aliases
    # per docs.anthropic.com/en/docs/about-claude/models/overview)
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # Retired Anthropic IDs (claude-sonnet-4-20250514, claude-3-5-haiku-
    # 20241022, ...) are deliberately absent: unknown models raise below.
    # Google: promo through 2026-12-31, then $1.50 / $7.50
    "gemini-3.8-flash": (0.75, 3.75),
}


class PricingTable:
    def __init__(self, rates: dict[str, tuple[float, float]] | None = None):
        self._rates = dict(DEFAULT_RATES if rates is None else rates)

    def set(self, model: str, input_per_1m: float, output_per_1m: float) -> None:
        self._rates[model] = (input_per_1m, output_per_1m)

    def _rate_for(self, model: str, on_date) -> tuple[float, float]:
        if model in EXPIRING_RATES:
            last_promo_day, promo, standard = EXPIRING_RATES[model]
            import datetime as _dt

            promo_end = _dt.date.fromisoformat(last_promo_day)
            return promo if on_date <= promo_end else standard
        return self._rates[model]

    def cost(self, model: str, input_tokens: int, output_tokens: int,
             on_date=None) -> float:
        """Return estimated USD cost (see ESTIMATE_BASIS).

        Unknown models raise so nothing is silently free.
        """
        if model not in self._rates:
            raise KeyError(f"no pricing for model {model!r}; add it to the table")
        import datetime as _dt

        in_rate, out_rate = self._rate_for(model, on_date or _dt.date.today())
        return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
