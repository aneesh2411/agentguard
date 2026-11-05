"""End-to-end local demo: SDK tracking -> ingest API -> dashboard.

Runs three simulated support-ticket agents against the local ingestion
API; the third pushes the workflow over its budget so the alert log
fires. Everything is simulated: NO real provider calls are made and no
money is spent - token counts are hardcoded and costs come from the
shipped pricing table.

Usage:
    pip install -e sdk/ -r api/requirements.txt
    uvicorn api.app.main:app --port 8000          # in another terminal
    python sdk/examples/end_to_end_demo.py        # then open http://localhost:8000
"""
import json
import urllib.request

from agentguard import RunTracker

API = "http://localhost:8000"


def set_budget():
    req = urllib.request.Request(
        API + "/budgets",
        data=json.dumps({"task_type": "support_ticket",
                         "max_cost_per_task": 0.40}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        print("budget set:", json.loads(r.read()))


def simulated_run(steps, model="gpt-4o", fail_first=False):
    """A fake agent loop: hardcoded token counts, no provider calls."""
    with RunTracker("support_ticket", api_url=API) as t:
        if fail_first:
            t.llm(model, input_tokens=40_000, output_tokens=10_000)
            t.tool("zendesk_lookup", status="error")
            t.fail(retry=True)
        for _ in range(steps):
            t.llm(model, input_tokens=40_000, output_tokens=10_000)
            t.tool("zendesk_lookup")
    print(f"  {t.run.run_id}: {t.run.status}, ${t.run.cost_usd:.4f}, "
          f"{t.run.retry_count} retries")


def main():
    set_budget()
    print("Run 1: two cheap steps, completes under budget")
    simulated_run(steps=2, model="gpt-4o-mini")
    print("Run 2: two expensive steps, still under budget")
    simulated_run(steps=2)
    print("Run 3: fails once, retries on the expensive model - breaches "
          "the $0.40/task budget and logs an alert")
    simulated_run(steps=3, fail_first=True)
    print("Done - open http://localhost:8000 for the dashboard "
          "(budget alerts section shows the breach), "
          "http://localhost:8000/alerts for the raw alert log.")


if __name__ == "__main__":
    main()
