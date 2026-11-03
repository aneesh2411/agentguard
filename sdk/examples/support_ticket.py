"""Simulated support-ticket agent: one retry, then success."""
from agentguard import RunTracker

with RunTracker("support_ticket", sink="runs.jsonl") as t:
    # Attempt 1: model hallucinates, tool call errors, we retry.
    t.llm("gpt-4o", input_tokens=4200, output_tokens=900)
    t.tool("zendesk_lookup", status="error")
    t.fail(retry=True)

    # Attempt 2: cheaper model finishes the job.
    t.llm("gpt-4o-mini", input_tokens=3800, output_tokens=450)
    t.tool("zendesk_lookup")
    t.tool("send_reply")

run = t.run
print(f"task completed: {run.status}")
print(f"attempts: {len(run.attempts)} (retries: {run.retry_count})")
print(f"total cost: ${run.cost_usd:.4f}")
