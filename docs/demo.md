# Local demo: SDK -> ingest API -> dashboard

A five-minute end-to-end run with simulated agents. No real provider
calls are made and no money is spent: token counts are hardcoded in the
example and costs come from the shipped pricing table. Real integrations
(LiteLLM import, or pointing a live agent's RunTracker at the API) use
the same ingestion endpoints with real usage.

## Run it

    pip install -e sdk/ -r api/requirements.txt
    uvicorn api.app.main:app --port 8000
    python sdk/examples/end_to_end_demo.py   # in another terminal

Then open http://localhost:8000 - the dashboard shows cost per completed
task for the support_ticket workflow, the run-cost-by-day chart, and a
breach in the Budget alerts section. http://localhost:8000/alerts is the
raw alert log.

## What the demo does

1. Sets a $0.40/task budget on the support_ticket workflow.
2. Runs a cheap gpt-4o-mini agent (2 steps, completes, $0.024).
3. Runs an expensive gpt-4o agent (2 steps, completes, $0.40) - still
   under budget on a per-completed-task basis.
4. Runs an agent that fails once and retries on gpt-4o ($0.80 total) -
   cost per completed task crosses the budget and a breach alert is
   logged.

## Individual pieces

- `sdk/examples/support_ticket.py` - minimal tracked run with one retry.
- `sdk/examples/budget_guard.py` - in-run policy: switch-model signal,
  human-approval pause, hard stop.
