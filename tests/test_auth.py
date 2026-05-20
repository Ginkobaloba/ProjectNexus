"""
Sprint 3b auth tests.

Coverage targets from the brief:
  - Unauthenticated request returns 401.
  - Invalid token returns 401.
  - Valid token returns 200.
  - Token revocation works (a previously-valid token starts returning 401).
  - Health endpoint works without auth.

The tests run against a real FastAPI TestClient with a tmp token store
and the brainstem's outbound dependencies stubbed out. We do not need a
live Cortex / embedder for the auth-layer assertions; we patch the
cortex/embedder clients to return synthetic payloads so the test
exercises the middleware and the wiring without spinning the full stack.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Standalone TokenStore unit tests (no FastAPI required)
# ---------------------------------------------------------------------------


def test_mint_token_shape():
    from brainstem_4070.auth import mint_token, TOKEN_PREFIX, looks_like_token

    t = mint_token()
    assert t.startswith(TOKEN_PREFIX)
    assert looks_like_token(t)
    assert t != mint_token()


def test_token_store_create_and_verify(tmp_path: Path):
    from brainstem_4070.auth import TokenStore

    store = TokenStore.load(tmp_path / "tokens.json")
    token, entry = store.create("laptop")

    raw = json.loads((tmp_path / "tokens.json").read_text("utf-8"))
    assert raw["tokens"][0]["name"] == "laptop"
    assert raw["tokens"][0]["hash"] != token
    assert raw["tokens"][0]["hash"].startswith("$")

    matched = store.verify(token)
    assert matched is not None
    assert matched.name == "laptop"
    assert matched.use_count == 1
    assert store.verify(token + "x") is None
    assert store.verify("nxs_bogus_token_value_that_will_never_match") is None


def test_token_store_revoke(tmp_path: Path):
    from brainstem_4070.auth import TokenStore

    store = TokenStore.load(tmp_path / "tokens.json")
    token, _ = store.create("phone")
    assert store.verify(token) is not None

    assert store.revoke("phone") is True
    assert store.verify(token) is None
    assert store.revoke("phone") is False


def test_token_store_duplicate_name_rejected(tmp_path: Path):
    from brainstem_4070.auth import TokenStore

    store = TokenStore.load(tmp_path / "tokens.json")
    store.create("laptop")
    with pytest.raises(ValueError):
        store.create("laptop")


def test_token_store_reloads_on_mtime_change(tmp_path: Path):
    """A second TokenStore instance pointing at the same file picks up
    writes the first instance made. This is the property the live
    brainstem relies on to see freshly-minted tokens without restart."""
    from brainstem_4070.auth import TokenStore

    path = tmp_path / "tokens.json"
    store_a = TokenStore.load(path)
    token, _ = store_a.create("a")

    store_b = TokenStore.load(path)
    assert store_b.verify(token) is not None


# ---------------------------------------------------------------------------
# FastAPI middleware tests (full app, stubbed downstream calls)
# ---------------------------------------------------------------------------


@pytest.fixture
def brainstem_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Boot the brainstem FastAPI app against a tmp token store with the
    outbound clients (Cortex, embedder, NAS) stubbed.

    The brainstem reads `settings.token_store_path` at import time via
    `configure_store(...)`, so we set the env var before import and then
    reload the store against tmp inside the test.
    """
    store_path = tmp_path / "tokens.json"
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(store_path))
    metrics_path = tmp_path / "brainstem_metrics.jsonl"
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(metrics_path))

    import importlib
    import sys

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(store_path)

    def fake_memory_query(**_kwargs):
        return {"matches": []}

    def fake_memory_write(**_kwargs):
        return {"ok": True, "chunks": 1}

    def fake_embedder_health():
        return {"reachable": True}

    def fake_cortex_generate(**_kwargs):
        return {
            "text": "stub response",
            "model": "stub-model",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    monkeypatch.setattr(server.embedder, "memory_query", fake_memory_query)
    monkeypatch.setattr(server.embedder, "memory_write", fake_memory_write)
    monkeypatch.setattr(server.embedder, "health", fake_embedder_health)
    monkeypatch.setattr(server.cortex, "generate", fake_cortex_generate)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        store = TokenStore.load(store_path)
        token, _entry = store.create("laptop")
        yield client, token, store, server


def test_health_does_not_require_auth(brainstem_client):
    client, _token, _store, _server = brainstem_client
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"


def test_root_does_not_require_auth(brainstem_client):
    client, _token, _store, _server = brainstem_client
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert "/generate" in body["endpoints"]["authenticated"]
    assert "/health" in body["endpoints"]["anonymous"]


def test_generate_without_auth_returns_401(brainstem_client):
    client, _token, _store, _server = brainstem_client
    res = client.post(
        "/generate",
        headers={"X-Session-Id": "sess_test"},
        json={"prompt": "hi"},
    )
    assert res.status_code == 401
    assert "Authorization" in res.json()["detail"]


def test_generate_with_invalid_token_returns_401(brainstem_client):
    client, _token, _store, _server = brainstem_client
    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_test",
            "Authorization": "Bearer nxs_definitely_not_a_real_token",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid token"


def test_generate_with_valid_token_returns_200(brainstem_client):
    client, token, _store, _server = brainstem_client
    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_test",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "stub response"
    assert body["session_id"] == "sess_test"
    assert body["memory_written"] is True


def test_revoked_token_starts_returning_401(brainstem_client):
    client, token, store, _server = brainstem_client

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_test",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 200

    removed = store.revoke("laptop")
    assert removed is True

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_test",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 401


def test_malformed_authorization_header_returns_401(brainstem_client):
    client, token, _store, _server = brainstem_client
    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_test",
            "Authorization": token,
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 401


def test_token_attribution_in_metric_record(brainstem_client, tmp_path: Path):
    client, token, _store, _server = brainstem_client
    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_attr",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 200

    metrics_path = Path(os.environ["BRAINSTEM_METRICS_PATH"])
    assert metrics_path.exists()
    lines = [json.loads(l) for l in metrics_path.read_text("utf-8").splitlines() if l.strip()]
    assert lines, "expected at least one metric record"
    last = lines[-1]
    # MetricRecord.to_dict() flattens the `extra` dict into top-level
    # fields, so token_name lives at the root of the JSONL record.
    assert last.get("token_name") == "laptop"
    assert last.get("session_id") == "sess_attr"
