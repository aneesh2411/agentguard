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
  and a small dashboard.

## Metric definition

Cost per completed task is outcome-level: **all** spend on a workflow -
completed runs, failed runs, and every retry attempt - divided by the number
of completed business tasks. Failed-run spend is real cost, not excluded
overhead. A successful model call is not proof a task completed: imported
runs count as completed only with an explicit outcome signal, otherwise they
are unresolved - their spend still counts. When nothing has completed yet
the metric is undefined (n/a), never zero.

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

Run the API locally (loopback only):

```bash
pip install -r api/requirements.txt
uvicorn app.main:app --host 127.0.0.1 --app-dir api
```

## Local usage and security

This is a local prototype, not production-secure. Read endpoints
(GET /, /summary, /runs, /budgets) are unauthenticated, so anyone who can
reach the server can see workflow and cost data. Bind to loopback and do
not expose it.

Write endpoints (POST /runs, /budgets) require an `X-API-Key` header when
`AGENTGUARD_API_KEY` is set; with it unset they run open for local
development. The LiteLLM receiver
(POST /integrations/litellm/spend-logs) always requires the key and fails
closed with 503 when `AGENTGUARD_API_KEY` is unset. The receiver stores
only a fixed whitelist of fields (model, token counts, spend, task and
outcome tags); prompts and arbitrary request metadata are never stored.
Batches are capped at 10,000 logs and request bodies at 2 MB
(Content-Length checked before parsing; chunked bodies without a declared
length are not covered).

## Windows and budgets

GET /summary and the dashboard accept `since` / `until` (unix seconds or
ISO 8601; naive ISO is read as UTC). A window is an event-time filter:
runs are counted by their last event time and each run's full spend is
attributed to the window containing it - it is not a cohort of tasks
completed in the window. With no completions in the window, cost per
completed task is n/a, never zero.

POST /budgets stores a per-workflow budget in USD per completed task. The
summary flags `over_budget` when the windowed cost per completed task is
strictly greater than the budget, and the dashboard highlights those
rows.

See `docs/concept.md` for the product framing.
