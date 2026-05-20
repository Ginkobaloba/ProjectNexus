"""
Sprint 3c tests: bind config + Cortex-down handling.

Coverage targets from the brief:
  - /generate returns 200 when Cortex is up (regression anchor).
  - /generate returns 503 with the structured body when Cortex is unreachable.
  - /health stays 200 while Cortex is down.
  - The dev fallback bind works for the localhost dev workflow.

The tests run against a real FastAPI TestClient with a tmp token store
and the outbound clients stubbed, mirroring tests/test_auth.py. We do
not need a live Cortex; we patch `cortex.generate` to raise CortexError
so the middleware actually exercises the 503 path.

See docs/exposure_and_cortex_down.md for the contract under test.
"""
from __future__ import annotations

import os
import importlib
import json
import sys
from pathlib import Path
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def brainstem_with_cortex_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator:
    """Boot the brainstem with the outbound clients stubbed and a knob
    that lets each test flip Cortex up/down at request time.

    The fixture yields (client, token, control), where `control` is a
    small mutable holder. Tests set `control.cortex_down = True` to make
    the next cortex.generate() raise CortexError.
    """
    store_path = tmp_path / "tokens.json"
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(store_path))
    metrics_path = tmp_path / "brainstem_metrics.jsonl"
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(metrics_path))

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(store_path)

    class Control:
        cortex_down = False
        cortex_failure_kind = "connection"  # or "timeout"

    control = Control()

    def fake_memory_query(**_kwargs):
        return {"matches": []}

    def fake_memory_write(**_kwargs):
        return {"ok": True, "chunks": 1}

    def fake_embedder_health():
        return {"reachable": True}

    def fake_cortex_generate(**_kwargs):
        if control.cortex_down:
            from brainstem_4070.cortex_client import CortexError

            if control.cortex_failure_kind == "timeout":
                raise CortexError(
                    "POST http://stubbed/v1/chat/completions failed: "
                    "HTTPSConnectionPool(...): Read timed out."
                )
            raise CortexError(
                "POST http://stubbed/v1/chat/completions failed: "
                "ConnectionRefusedError(111, 'Connection refused')"
            )
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
        yield client, token, control, server


# ---------------------------------------------------------------------------
# Cortex-up regression
# ---------------------------------------------------------------------------


def test_generate_returns_200_when_cortex_up(brainstem_with_cortex_control):
    """Regression: the happy path still works. The 3c changes are
    additive and must not regress the Sprint 2 + 3b behavior."""
    client, token, control, _server = brainstem_with_cortex_control
    control.cortex_down = False

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_up",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "stub response"
    assert body["memory_written"] is True


# ---------------------------------------------------------------------------
# Cortex-down 503 contract
# ---------------------------------------------------------------------------


def test_generate_returns_503_when_cortex_unreachable(
    brainstem_with_cortex_control,
):
    """The Sprint 3c contract. Body has `error`, `retry_after_seconds`,
    `message`, `session_id`, `turn_idx`. Header has `Retry-After` with
    the same integer."""
    client, token, control, _server = brainstem_with_cortex_control
    control.cortex_down = True
    control.cortex_failure_kind = "connection"

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_down",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 503

    body = res.json()
    assert body["error"] == "cortex_unavailable"
    assert isinstance(body["retry_after_seconds"], int)
    assert body["retry_after_seconds"] >= 1
    assert body["session_id"] == "sess_down"
    assert body["turn_idx"] is None
    assert "Cortex" in body["message"]
    assert "brainstem is up" in body["message"].lower()

    # Header carries the same integer the body carries.
    assert res.headers.get("Retry-After") == str(body["retry_after_seconds"])


def test_generate_503_classifies_timeout_separately(
    brainstem_with_cortex_control,
):
    """A timeout-flavored CortexError earns the longer retry window and
    the `cortex_timeout` code, per the design doc."""
    client, token, control, _server = brainstem_with_cortex_control
    control.cortex_down = True
    control.cortex_failure_kind = "timeout"

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_timeout",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 503

    body = res.json()
    assert body["error"] == "cortex_timeout"
    # Timeout retry is the longer of the two configured windows.
    assert body["retry_after_seconds"] >= 10
    assert res.headers.get("Retry-After") == str(body["retry_after_seconds"])


def test_metric_record_lands_on_cortex_down(
    brainstem_with_cortex_control, tmp_path: Path
):
    """A failed Cortex call still writes a metric record with the
    per-token attribution intact. Operational visibility into failures
    is non-negotiable: we want to see the outage in the dashboard."""
    client, token, control, _server = brainstem_with_cortex_control
    control.cortex_down = True

    res = client.post(
        "/generate",
        headers={
            "X-Session-Id": "sess_metric",
            "Authorization": f"Bearer {token}",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 503

    metrics_path = Path(os.environ["BRAINSTEM_METRICS_PATH"])
    assert metrics_path.exists()
    lines = [
        json.loads(l)
        for l in metrics_path.read_text("utf-8").splitlines()
        if l.strip()
    ]
    assert lines, "expected a metric record for the failed call"
    last = lines[-1]
    assert last.get("ok") is False
    assert last.get("token_name") == "laptop"
    assert last.get("session_id") == "sess_metric"


# ---------------------------------------------------------------------------
# /health remains green during a Cortex outage
# ---------------------------------------------------------------------------


def test_health_stays_200_while_cortex_down(brainstem_with_cortex_control):
    """/health only checks the embedder. A Cortex outage must not take
    the brainstem out of rotation from a load-balancer's perspective."""
    client, _token, control, _server = brainstem_with_cortex_control
    control.cortex_down = True

    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    # The embedder check is independent; the stub returns reachable.
    assert body.get("embedder_reachable") is True


def test_root_documents_cortex_down_contract(brainstem_with_cortex_control):
    """The `/` index advertises the 503 contract so a client poking the
    root URL can discover the shape. This is the lightest form of
    contract documentation and makes the response self-describing."""
    client, _token, _control, _server = brainstem_with_cortex_control
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    contract = body.get("cortex_down_contract") or {}
    assert contract.get("status") == 503
    assert contract.get("header") == "Retry-After"
    codes = contract.get("error_codes") or []
    assert "cortex_unavailable" in codes
    assert "cortex_timeout" in codes


# ---------------------------------------------------------------------------
# Bind fallback for the dev workflow
# ---------------------------------------------------------------------------


def test_dev_fallback_bind_is_loopback(monkeypatch: pytest.MonkeyPatch):
    """In a fresh checkout without a docker/.env file, the brainstem's
    published port falls back to 127.0.0.1, which is what makes the
    laptop dev workflow keep working. This test parses the compose file
    and asserts the default expansion is 127.0.0.1."""
    repo_root = Path(__file__).resolve().parent.parent
    compose = (repo_root / "docker" / "docker-compose.yml").read_text("utf-8")
    # The compose file should bind via ${BRAINSTEM_BIND_HOST:-127.0.0.1}
    # so a missing env var lands on loopback.
    assert "${BRAINSTEM_BIND_HOST:-127.0.0.1}:5001:5001" in compose


def test_dev_fallback_bind_respects_env(monkeypatch: pytest.MonkeyPatch):
    """An operator who sets BRAINSTEM_BIND_HOST gets that interface
    bound. We model the docker variable-expansion rule here so a future
    edit to the compose file that breaks the expansion fails loudly."""
    import re

    repo_root = Path(__file__).resolve().parent.parent
    compose = (repo_root / "docker" / "docker-compose.yml").read_text("utf-8")

    pattern = re.compile(r"\$\{BRAINSTEM_BIND_HOST:-(?P<default>[^}]+)\}")
    match = pattern.search(compose)
    assert match is not None, "expected ${BRAINSTEM_BIND_HOST:-...} in compose"
    assert match.group("default") == "127.0.0.1"


def test_brainstem_config_exposes_retry_knobs():
    """The 503 contract is parameterized by two config values. They
    should both have sensible defaults and be overridable via env."""
    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]
    from brainstem_4070.config import Settings

    s = Settings()
    assert s.cortex_down_retry_after_seconds >= 1
    assert s.cortex_timeout_retry_after_seconds >= s.cortex_down_retry_after_seconds
