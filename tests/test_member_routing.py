"""Sprint 5 Card 2: hub member routing + presence.

Done-criteria under test:
  - chat to an awake member round-trips (spec injected as base system).
  - chat to an asleep member returns 202 + msg_id, readable via inbox.
  - chat to a loading member returns 503 member_loading + Retry-After.
  - sessions are hub-minted per (person, member) and turn counters
    survive a restart (the Sprint 2 wart).

Mirrors the tests/test_cortex_down.py fixture: real TestClient, tmp
token store, outbound clients stubbed.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Boot the brainstem as a family hub with stubbed outbound clients.

    Yields (client, token, server, captured) where `captured` records
    what reached the stubbed cortex so tests can assert on the system
    prompt layering.
    """
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("BRAINSTEM_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("BRAINSTEM_INBOX_STORE_PATH", str(tmp_path / "inbox.json"))

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(tmp_path / "tokens.json")

    captured = {"system": None, "prompt": None, "temperature": None}

    def fake_cortex_generate(**kwargs):
        captured.update(
            system=kwargs.get("system"),
            prompt=kwargs.get("prompt"),
            temperature=kwargs.get("temperature"),
        )
        return {
            "text": "stub response",
            "model": "stub-model",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    monkeypatch.setattr(server.embedder, "memory_query", lambda **_: {"matches": []})
    monkeypatch.setattr(server.embedder, "memory_write", lambda **_: {"ok": True})
    monkeypatch.setattr(server.embedder, "health", lambda: {"reachable": True})
    monkeypatch.setattr(server.cortex, "generate", fake_cortex_generate)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        store = TokenStore.load(tmp_path / "tokens.json")
        token, _ = store.create("drew")
        yield client, token, server, captured


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Roster + detail
# ---------------------------------------------------------------------------


def test_family_roster_is_anonymous_and_lists_vera(hub):
    client, _token, _server, _cap = hub
    res = client.get("/family")
    assert res.status_code == 200
    members = res.json()["members"]
    assert [m["id"] for m in members] == ["vera"]
    assert members[0]["presence"] == "awake"
    assert members[0]["queue_depth"] == 0


def test_member_detail_and_unknown_member(hub):
    client, _token, _server, _cap = hub
    res = client.get("/members/vera")
    assert res.status_code == 200
    assert res.json()["runtime"]["offload_policy"] == "vram_then_ram"
    assert client.get("/members/nobody").status_code == 404


# ---------------------------------------------------------------------------
# Awake: live turn with spec layering
# ---------------------------------------------------------------------------


def test_awake_chat_roundtrips_with_spec_as_base_system(hub):
    client, token, _server, captured = hub
    res = client.post(
        "/members/vera/chat",
        headers=_auth(token),
        json={"prompt": "hello", "system": "Answer in one word."},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "stub response"
    assert body["member_id"] == "vera"
    assert body["memory_written"] is True
    assert body["session_id"].startswith("sess_")
    # Spec first, caller system after it — the member's identity is the
    # base layer (V2 Section 5).
    assert captured["system"].startswith("# Vera")
    assert "Answer in one word." in captured["system"]
    # Registry sampling default applied when the caller didn't override.
    assert captured["temperature"] == pytest.approx(0.7)


def test_chat_requires_auth(hub):
    client, _token, _server, _cap = hub
    res = client.post("/members/vera/chat", json={"prompt": "hi"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Hub-minted sessions: stable per (person, member), turn_idx survives restart
# ---------------------------------------------------------------------------


def test_sessions_are_stable_and_turns_survive_restart(hub, tmp_path):
    client, token, server, _cap = hub

    first = client.post("/members/vera/chat", headers=_auth(token), json={"prompt": "a"}).json()
    second = client.post("/members/vera/chat", headers=_auth(token), json={"prompt": "b"}).json()
    assert first["session_id"] == second["session_id"]
    assert (first["turn_idx"], second["turn_idx"]) == (0, 1)

    # Simulate a restart: wipe the in-memory counter, rebuild the store
    # from disk. The next turn must continue at 2, not reset to 0.
    server._turn_idx_by_session.clear()
    server.hub_sessions = server.HubSessionStore(tmp_path / "sessions.json")

    third = client.post("/members/vera/chat", headers=_auth(token), json={"prompt": "c"}).json()
    assert third["session_id"] == first["session_id"]
    assert third["turn_idx"] == 2


# ---------------------------------------------------------------------------
# Asleep/busy: 202 + inbox custody. Waking: 503 member_loading.
# ---------------------------------------------------------------------------


def test_asleep_member_queues_with_202_and_msg_id(hub):
    client, token, _server, _cap = hub
    assert client.post(
        "/members/vera/presence", headers=_auth(token), json={"presence": "asleep"}
    ).status_code == 200

    res = client.post("/members/vera/chat", headers=_auth(token), json={"prompt": "later"})
    assert res.status_code == 202
    body = res.json()
    assert body["queued"] is True
    assert body["msg_id"].startswith("msg_")

    # Queue depth is visible on the roster.
    roster = client.get("/family").json()["members"][0]
    assert roster["queue_depth"] == 1

    # The sender can read their queued message.
    status = client.get(body["status_url"], headers=_auth(token))
    assert status.status_code == 200
    assert status.json()["status"] == "queued"


def test_inbox_is_private_to_the_sender(hub, tmp_path):
    client, token, _server, _cap = hub
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "busy"})
    msg = client.post(
        "/members/vera/chat", headers=_auth(token), json={"prompt": "secret"}
    ).json()

    from brainstem_4070.auth import TokenStore

    other_token, _ = TokenStore.load(tmp_path / "tokens.json").create("guest")
    res = client.get(msg["status_url"], headers=_auth(other_token))
    # 404, not 403: existence itself is private (custody, not memory).
    assert res.status_code == 404


def test_waking_member_returns_member_loading_503(hub):
    client, token, server, _cap = hub
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "waking"})

    res = client.post("/members/vera/chat", headers=_auth(token), json={"prompt": "hi"})
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "member_loading"
    assert body["presence"] == "waking"
    assert res.headers["Retry-After"] == str(body["retry_after_seconds"])
    assert body["retry_after_seconds"] == server.settings.member_loading_retry_after_seconds


def test_invalid_presence_rejected(hub):
    client, token, _server, _cap = hub
    res = client.post(
        "/members/vera/presence", headers=_auth(token), json={"presence": "hibernating"}
    )
    assert res.status_code == 400
