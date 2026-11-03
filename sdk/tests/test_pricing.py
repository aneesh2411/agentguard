from agentguard.pricing import PricingTable


def test_known_model_cost():
    p = PricingTable({"test-model": (1.00, 2.00)})
    assert p.cost("test-model", 1_000_000, 500_000) == 2.00


def test_unknown_model_raises():
    p = PricingTable({})
    try:
        p.cost("nope", 1, 1)
    except KeyError:
        return
    raise AssertionError("unknown model must not be silently free")


def test_shipped_rates_are_verified_format():
    from agentguard.pricing import DEFAULT_RATES, VERIFIED_ON
    assert VERIFIED_ON == "2026-11-02"
    assert "gemini-2.0-flash" not in DEFAULT_RATES  # retired upstream
    assert DEFAULT_RATES["gpt-4o"] == (2.50, 10.00)
    assert DEFAULT_RATES["claude-sonnet-5"] == (2.00, 10.00)


def test_retired_ids_fail_explicitly():
    p = PricingTable()
    for retired in ("claude-sonnet-4", "claude-haiku-3.5",
                    "claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"):
        try:
            p.cost(retired, 1, 1)
        except KeyError:
            continue
        raise AssertionError(f"retired id {retired} must not price silently")
