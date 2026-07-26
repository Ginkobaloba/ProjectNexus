"""Household sensor feed: born-shared events + timeline.

Done-criteria under test:
  - a sensor event lands in shared:household with origin=sensor and
    full attribution (sensor_source + reporting token), never touching
    any private scope;
  - the embedder's timeline path reads only the shared scope and
    orders newest-first with missing-ts rows sinking to the end;
  - the hub endpoints require auth and pass attribution through.

The embedder service is exercised with a real TestClient — the model
and Chroma are stubbed at their module seams, everything else runs.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest

from embedder_4070.scopes import build_event_metadata
from embedder_4070.server import newest_first


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_event_metadata_is_born_shared():
    meta = build_event_metadata("jetson_backdoor_cam", "2026-07-26T01:00:00+00:00", "jetson1")
    assert meta["scope"] == "shared:household"
    assert meta["member_id"] == "household"
    assert meta["origin"] == "sensor"
    assert meta["sensor_source"] == "jetson_backdoor_cam"
    assert meta["reported_by"] == "jetson1"


def test_event_requires_sensor_source():
    with pytest.raises(ValueError):
        build_event_metadata("  ", "2026-07-26T01:00:00+00:00", "jetson1")


def test_newest_first_orders_and_sinks_missing_ts():
    rows = newest_first(
        ids=["a", "b", "c"],
        documents=["old", "new", "no-ts"],
        metadatas=[{"ts": "2026-07-25T00:00:00"}, {"ts": "2026-07-26T00:00:00"}, {}],
        limit=10,
    )
    assert [r["id"] for r in rows] == ["b", "a", "c"]
    assert newest_first(["a", "b"], ["x", "y"],
                        [{"ts": "1"}, {"ts": "2"}], limit=1)[0]["id"] == "b"


# ---------------------------------------------------------------------------
# Embedder service (model + Chroma stubbed at their seams)
# ---------------------------------------------------------------------------


@pytest.fixture
def embedder_app(monkeypatch: pytest.MonkeyPatch):
    import embedder_4070.server as eserver

    store: dict = {}

    def fake_add(ids, documents, embeddings, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            store[i] = {"doc": d, "meta": m}

    def fake_get_where(where, limit=1000):
        assert where == {"scope": "shared:household"}, "timeline must filter to shared scope"
        hits = {i: r for i, r in store.items() if r["meta"].get("scope") == "shared:household"}
        return {
            "ids": list(hits.keys()),
            "documents": [r["doc"] for r in hits.values()],
            "metadatas": [r["meta"] for r in hits.values()],
        }

    monkeypatch.setattr(eserver.chroma_store, "add_documents", fake_add)
    monkeypatch.setattr(eserver.chroma_store, "get_where", fake_get_where)
    monkeypatch.setattr(eserver, "embed_texts", lambda texts: [[0.0, 1.0]] * len(texts))

    from fastapi.testclient import TestClient

    return TestClient(eserver.app), store


def test_event_write_and_timeline_roundtrip(embedder_app):
    client, store = embedder_app

    res = client.post("/memory/event", json={
        "summary": "the dog went out the back door",
        "sensor_source": "jetson_backdoor_cam",
        "ts": "2026-07-26T01:00:00+00:00",
        "reported_by": "jetson1",
    })
    assert res.status_code == 200, res.text
    event_id = res.json()["id"]
    assert event_id.startswith("event:jetson_backdoor_cam:")
    assert store[event_id]["meta"]["origin"] == "sensor"

    # A private row must never surface on the timeline.
    store["private_row"] = {
        "doc": "secret 1-on-1", "meta": {"scope": "private:vera", "ts": "2026-07-27T00:00:00"},
    }

    res = client.get("/memory/timeline")
    assert res.status_code == 200
    events = res.json()["events"]
    assert [e["id"] for e in events] == [event_id]


def test_event_rejects_empty_summary(embedder_app):
    client, _ = embedder_app
    res = client.post("/memory/event", json={
        "summary": "  ", "sensor_source": "cam", "ts": "t",
    })
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Hub endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("BRAINSTEM_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("BRAINSTEM_INBOX_STORE_PATH", str(tmp_path / "inbox.json"))

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(tmp_path / "tokens.json")

    captured = {}
    monkeypatch.setattr(
        server.embedder, "memory_event",
        lambda **kw: captured.update(kw) or {"id": "event:cam:abc", "scope": "shared:household"},
    )
    monkeypatch.setattr(
        server.embedder, "memory_timeline",
        lambda limit: {"events": [], "limit_seen": limit},
    )

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        token, _ = TokenStore.load(tmp_path / "tokens.json").create("jetson_kitchen")
        yield client, token, captured


def test_hub_event_ingest_stamps_reporting_token(hub):
    client, token, captured = hub
    res = client.post(
        "/household/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"summary": "dog went outside", "sensor_source": "jetson_backdoor_cam"},
    )
    assert res.status_code == 200, res.text
    assert captured["reported_by"] == "jetson_kitchen"
    assert captured["sensor_source"] == "jetson_backdoor_cam"
    assert captured["ts"]  # defaulted to now


def test_hub_household_endpoints_require_auth(hub):
    client, _token, _captured = hub
    assert client.post(
        "/household/events", json={"summary": "x", "sensor_source": "cam"}
    ).status_code == 401
    assert client.get("/household/timeline").status_code == 401
