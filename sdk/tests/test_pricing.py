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
