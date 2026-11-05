"""Request-level hardening: malformed/mismatched Content-Length, run-detail auth."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.main as m  # noqa: E402
from app.store import Store  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "store", Store(tmp_path / "t.db"))
    return TestClient(m.app)


@pytest.fixture
def client_read_key(client, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_READ_KEY", "rk")
    return client


def test_malformed_content_length_rejected(client):
    resp = client.post("/runs", content=b'{"x": 1}',
                       headers={"Content-Length": "abc"})
    assert resp.status_code == 400


def test_underclaimed_content_length_still_capped(client):
    big = b"x" * (m.MAX_BODY_BYTES + 1)
    resp = client.post("/runs", content=big,
                       headers={"Content-Length": "10"})
    assert resp.status_code == 413


def test_run_detail_requires_read_key(client_read_key):
    c = client_read_key
    assert c.get("/runs/whatever").status_code == 401
    assert c.get("/runs/whatever",
                 headers={"X-API-Key": "wrong"}).status_code == 401
    # unknown id with the right key -> 404 (auth passed, not found)
    assert c.get("/runs/whatever",
                 headers={"X-API-Key": "rk"}).status_code == 404


def test_run_detail_open_when_read_key_unset(client, monkeypatch):
    monkeypatch.delenv("AGENTGUARD_READ_KEY", raising=False)
    assert client.get("/runs/whatever").status_code == 404


def test_otel_endpoint_roundtrip(client, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_KEY", "k")
    h = {"X-API-Key": "k"}
    spans = [{"traceId": "t9", "spanId": "r", "name": "ticket",
              "startTimeUnixNano": "1762087200000000000",
              "attributes": {"agentguard_outcome": "completed"}},
             {"traceId": "t9", "spanId": "c", "parentSpanId": "r",
              "startTimeUnixNano": "1762087201000000000",
              "attributes": {"gen_ai.request.model": "gpt-4o-mini",
                             "gen_ai.usage.input_tokens": 100,
                             "gen_ai.usage.output_tokens": 50}}]
    resp = client.post("/integrations/otel/spans", json={"spans": spans},
                       headers=h)
    assert resp.status_code == 201
    assert resp.json()["run_ids"] == ["otel-t9"]
    bad = client.post("/integrations/otel/spans", json={"spans": "no"},
                      headers=h)
    assert bad.status_code == 422
    # receiver fails closed without a key
    assert client.post("/integrations/otel/spans",
                       json={"spans": spans}).status_code == 401


def test_otel_accepts_real_otlp_envelope(client, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_KEY", "k")
    envelope = {"resourceSpans": [{
        "resource": {"attributes": []},
        "scopeSpans": [{"scope": {"name": "lib"},
                        "spans": [
                            {"traceId": "tx", "spanId": "s",
                             "name": "chat",
                             "startTimeUnixNano": "1762087200000000000",
                             "attributes": [
                                 {"key": "gen_ai.request.model",
                                  "value": {"stringValue": "gpt-4o-mini"}},
                                 {"key": "gen_ai.usage.input_tokens",
                                  "value": {"intValue": 100}}]}]}]}]}
    resp = client.post("/integrations/otel/spans", json=envelope,
                       headers={"X-API-Key": "k"})
    assert resp.status_code == 201
    assert resp.json()["run_ids"] == ["otel-tx"]
    assert resp.json()["received_spans"] == 1


def test_receiver_repost_is_idempotent(client, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_KEY", "k")
    h = {"X-API-Key": "k"}
    spans = [{"traceId": "t9", "spanId": "c", "name": "ticket",
              "attributes": {"gen_ai.request.model": "gpt-4o-mini",
                             "gen_ai.usage.input_tokens": 1000,
                             "gen_ai.usage.output_tokens": 200}}]
    for _ in range(2):
        assert client.post("/integrations/otel/spans",
                           json={"spans": spans}, headers=h).status_code == 201
    runs = client.get("/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["otel-t9"]
    # same spend once, not doubled
    assert abs(runs[0]["cost_usd"] - 0.00027) < 1e-9
    s = client.get("/summary").json()
    assert abs(s["task_types"][0]["total_spend"] - 0.00027) < 1e-9


def test_summary_surfaces_unknown_cost_runs(client, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_KEY", "k")
    h = {"X-API-Key": "k"}
    spans = [{"traceId": "tu", "spanId": "c", "name": "mystery",
              "attributes": {"gen_ai.request.model": "no-such-model",
                             "gen_ai.usage.input_tokens": 5000}},
             {"traceId": "tk", "spanId": "c", "name": "mystery",
              "attributes": {"gen_ai.request.model": "gpt-4o-mini",
                             "gen_ai.usage.input_tokens": 1000}}]
    assert client.post("/integrations/otel/spans",
                       json={"spans": spans}, headers=h).status_code == 201
    s = client.get("/summary").json()
    assert s["unknown_cost_runs"] == 1
    row = s["task_types"][0]
    assert row["unknown_cost_runs"] == 1
    # the unknown run's spend is $0 in totals - the flag is what keeps
    # that from reading as free
    page = client.get("/").text
    assert "pricing is" in page and "understate" in page
