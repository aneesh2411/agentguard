from agentguard import RunTracker, PricingTable


def test_completed_run_aggregates_all_attempts(tmp_path):
    sink = tmp_path / "runs.jsonl"
    pricing = PricingTable({"m": (1.0, 1.0)})
    with RunTracker("ticket", sink=sink, pricing=pricing) as t:
        t.llm("m", 500_000, 0)
        t.fail(retry=True)
        t.llm("m", 500_000, 0)
        t.tool("lookup", cost_usd=0.01)
        t.complete()
    assert t.run.status == "completed"
    assert t.run.retry_count == 1
    assert abs(t.run.cost_usd - 1.01) < 1e-9
    assert sink.read_text().strip()


def test_context_manager_auto_completes(tmp_path):
    with RunTracker("ticket", sink=tmp_path / "r.jsonl",
                    pricing=PricingTable({"m": (1.0, 1.0)})) as t:
        t.llm("m", 100, 100)
    assert t.run.status == "completed"
