# AgentGuard

Know what every completed business task actually costs when AI agents do the work.

Running agents feels productive until the bill arrives. A retry loop or a runaway
tool call can turn a $2 task into a $50 mistake. AgentGuard tracks the full cost
of each *successfully completed task* - not just tokens or API calls - by
connecting retries, failed attempts, tool calls, and model switches into one
number: cost per completed task.

This repository is an early scaffold. Status and plans live in `docs/`.

## What it does (today)

- `sdk/` - Python SDK: wrap an agent run, record LLM calls, tool calls, and
  retries, compute per-run cost from a pricing table, and emit structured events.
- `api/` - FastAPI service: ingests run events and serves read-only aggregates
  (cost per completed task, per workflow, wasted spend on failed attempts).

## Roadmap (proposed)

1. Read-only dashboard measuring cost per completed task across providers.
2. Integrations with the gateways teams already run (LiteLLM, Langfuse, etc.).
3. Warnings when a workflow burns budget.
4. Safe fallbacks (cheaper model, human approval, hard stop).

## Pricing (proposal, not validated)

- $49-$199/mo small teams
- $299-$999/mo agencies managing multiple clients
- $500+ high-volume workflows with policy enforcement

## Quick start

```bash
pip install -e sdk/
python sdk/examples/support_ticket.py
```

See `docs/concept.md` for the product framing.
