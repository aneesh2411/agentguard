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


## Budget guard (SDK policies)

A `BudgetPolicy` acts on runaway spend while a run is still in flight, not
after the bill arrives. Attach it to a tracker; after every recorded call
the policy is checked against the run's total estimated spend (all attempts,
retries included):

```python
from agentguard import BudgetPolicy, RunTracker, Threshold

policy = BudgetPolicy("support_ticket", thresholds=[
    Threshold(0.10, "switch_model", fallback_model="gpt-4o-mini"),
    Threshold(0.50, "require_approval"),
    Threshold(1.00, "stop"),
])

with RunTracker("support_ticket", policy=policy) as t:
    t.llm("gpt-4o", input_tokens=40_000, output_tokens=10_000)
    model = t.recommended_model("gpt-4o")  # -> "gpt-4o-mini" past $0.10
```

- `switch_model` sets `t.decision` and makes `t.recommended_model()` return
  the fallback; switching the actual client is the caller's action on that
  signal.
- `require_approval` raises `ApprovalRequired` and pauses the run; resume
  with `t.approve()` after a human OK.
- `stop` fails the run (spend so far is still recorded and shipped), then
  raises `BudgetExceeded`. The exception carries the decision: threshold,
  spend, workflow.

Each threshold fires once per run, and when one call crosses several
thresholds only the highest acts. Thresholds compare against locally
estimated spend (see `sdk/agentguard/pricing.py` ESTIMATE_BASIS), not the
provider invoice. Demo: `python sdk/examples/budget_guard.py`.

## Windows and budgets

GET /runs paginates with `limit` / `offset` (newest event first) and
returns a `total`; the dashboard's runs table pages 50 at a time with
newer/older links that preserve the window and workflow filter.

The dashboard also shows an inline SVG chart (no JS) of run cost per
last-event day for the current view, and the runs table can be filtered
by workflow with
`?task_type=<name>` (links above the table preserve the active window).
Each run's full estimated cost is attributed to the day of its last
event (the same event time the summary window uses), so the chart always
agrees with the summary totals for the same filter - it is not a per-call
breakdown.

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

Budgets are also evaluated at write time: POST /runs answers with a
`budget` field for the run's workflow (`budget_per_task`,
`cost_per_completed_task`, `over_budget`), or null when no budget is
configured - so an integrating caller learns about a breach in the ingest
response itself.

Budget breaches are logged as alert events: when a workflow's over_budget
state flips, an event (breach / recovered, with cost vs budget and the
triggering run) is recorded and shown on the dashboard and at
GET /alerts. A workflow already over budget does not re-alert on every
ingest; it alerts again only after recovering and breaching once more.
This log is local-only - no external delivery (webhook/email) is
configured.

See `docs/concept.md` for the product framing.
