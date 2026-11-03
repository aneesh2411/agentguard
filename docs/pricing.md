# Pricing data policy

Decision (initial, issue #6): versioned shipped table + explicit overrides +
imported provider-reported spend. No silent scraping or remote config fetches.

- Shipped table (`sdk/agentguard/pricing.py`) is versioned in git, carries
  VERIFIED_ON, CURRENCY, per-provider SOURCES, and ESTIMATE_BASIS.
- A computed cost is an **estimate** of standard-tier, uncached token usage -
  not an exact provider invoice. Cached-input discounts, batch/flex/priority
  tiers, thinking-token surcharges, and tool/provider fees can materially
  change the real bill.
- Rates with published expiries (e.g. gemini-3.8-flash promo ending
  2026-12-31) switch automatically at the boundary instead of silently
  undercounting.
- Unknown or retired model IDs raise; nothing prices silently at $0.
- Runs record their cost basis: "estimated-local" (SDK, shipped table) or
  "provider-reported" (imported, e.g. LiteLLM computed spend).
- Re-verify the table against SOURCES before quoting dollars to customers.
