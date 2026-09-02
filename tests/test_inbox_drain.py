"""Sprint 5 Card 5: durable inbox + drain on wake.

Done-criteria under test:
  - a message sent while the member is asleep is answered after wake,
    on the sender's own (person, member) session — correct continuity;
  - the answer is retrievable by msg_id;
  - queued messages survive a hub restart (durable custody);
  - a cortex failure mid-drain leaves the remaining messages queued;
  - custody is not memory: nothing is written to any scope until the
    member actually processes the turn.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest


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

    class Control:
        cortex_down = False

    control = Control()
    writes = []

    def fake_cortex_generate(**kwargs):
        if control.cortex_down:
            from brainstem_4070.cortex_client import CortexError
            raise CortexError("POST http://stubbed failed: Connection refused")
        return {
            "text": f"reply to: {kwargs.get('prompt')}",
            "model": "stub-model",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    def fake_memory_write(**kwargs):
        writes.append(kwargs)
        return {"ok": True, "chunks": 1}

    monkeypatch.setattr(server.embedder, "memory_query", lambda **_: {"matches": []})
    monkeypatch.setattr(server.embedder, "memory_write", fake_memory_write)
    monkeypatch.setattr(server.embedder, "health", lambda: {"reachable": True})
    monkeypatch.setattr(server.cortex, "generate", fake_cortex_generate)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        token, _ = TokenStore.load(tmp_path / "tokens.json").create("drew")
        yield client, token, server, control, writes


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_queued_message_is_answered_on_wake_with_session_continuity(hub):
    client, token, _server, _control, writes = hub

    # A live turn first, so the (drew, vera) session has history.
    live = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "one"}
    ).json()
    assert live["turn_idx"] == 0

    # Vera goes to sleep; a message arrives; custody, not memory.
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})
    writes_before = len(writes)
    msg = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "two"}
    ).json()
    assert len(writes) == writes_before  # nothing hit any memory scope

    # Wake: the queue drains through the normal chat path.
    woke = client.post(
        "/members/vera/presence", headers=_auth(token), json={"presence": "awake"}
    ).json()
    assert woke["drained"] == 1

    # The answer is retrievable by msg_id, on the same session, at the
    # next turn index — exactly as if the sender had waited.
    status = client.get(msg["status_url"], headers=_auth(token)).json()
    assert status["status"] == "answered"
    assert status["result"]["text"] == "reply to: two"
    assert status["result"]["session_id"] == live["session_id"]
    assert status["result"]["turn_idx"] == 1
    assert status["result"]["memory_written"] is True

    # The drained turn wrote to Vera's private scope like any turn.
    assert writes[-1]["scope"] == "private:vera"
    assert writes[-1]["participants"] == ["drew"]


def test_drain_emits_queue_wait_metric(hub, tmp_path):
    """Card 7: the waiting is measured, not just the turn."""
    import json

    client, token, _server, _control, _writes = hub
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})
    msg = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "measure me"}
    ).json()
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "awake"})

    records = [
        json.loads(line)
        for line in (tmp_path / "metrics.jsonl").read_text().splitlines()
    ]
    drains = [r for r in records if r["probe_id"] == "brainstem.inbox_drain"]
    assert len(drains) == 1
    assert drains[0]["member_id"] == "vera"
    assert drains[0]["msg_id"] == msg["msg_id"]
    assert drains[0]["queue_wait_ms"] >= 0.0
    assert drains[0]["token_name"] == "drew"

    # And the fabric status feed carries the family roster (Card 7).
    fabric = client.get("/fabric/status").json()
    assert fabric["family"][0]["id"] == "vera"
    assert fabric["family"][0]["queue_depth"] == 0


def test_queued_messages_survive_restart(hub, tmp_path):
    client, token, server, _control, _writes = hub

    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})
    msg = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "persist me"}
    ).json()

    # Simulate a restart: rebuild FamilyState from the same store file.
    reborn = server.FamilyState(
        ["vera"], default_presence="asleep", store_path=tmp_path / "inbox.json"
    )
    record = reborn.get_message("vera", msg["msg_id"])
    assert record is not None
    assert record["status"] == "queued"
    assert record["prompt"] == "persist me"


def test_cortex_down_mid_drain_leaves_messages_queued(hub):
    client, token, _server, control, _writes = hub

    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})
    msg = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "hold on"}
    ).json()

    control.cortex_down = True
    woke = client.post(
        "/members/vera/presence", headers=_auth(token), json={"presence": "awake"}
    ).json()
    assert woke["drained"] == 0

    # Still queued — it will be retried on the next wake.
    status = client.get(msg["status_url"], headers=_auth(token)).json()
    assert status["status"] == "queued"

    control.cortex_down = False
    rewoke = client.post(
        "/members/vera/presence", headers=_auth(token), json={"presence": "awake"}
    ).json()
    assert rewoke["drained"] == 1
    assert client.get(
        msg["status_url"], headers=_auth(token)
    ).json()["status"] == "answered"
