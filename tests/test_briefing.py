"""Sprint 6 R1 + R2: concierge registry block + data-only briefing.

Done-criteria under test:
  - the concierge parses/validates as staff, not family: absent block
    is fine, id collision with a member is a boot failure, and Jeffery
    never appears on the roster;
  - the briefing windows household events to the member's last sleep
    edge (24h fallback before first sleep) and survives the store
    across a restart;
  - privacy invariant: queued message CONTENTS never appear anywhere
    in the briefing payload — custody metadata only.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Iterator

import pytest

from core.family import RegistryError, load_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# R1 — concierge in the registry
# ---------------------------------------------------------------------------


def test_checked_in_registry_has_jeffery_as_staff():
    registry = load_registry(REPO_ROOT / "family" / "registry.yaml")
    assert registry.concierge is not None
    assert registry.concierge.id == "jeffery"
    # Staff, not family.
    assert "jeffery" not in registry
    assert all(m.id != "jeffery" for m in registry.members)


def test_registry_without_concierge_is_valid(tmp_path):
    (tmp_path / "family").mkdir()
    spec = tmp_path / "family" / "vera"
    spec.mkdir()
    (spec / "spec.md").write_text("# Vera\nBe kind.\n")
    (tmp_path / "family" / "registry.yaml").write_text("""
members:
  - id: "vera"
    display_name: "Vera"
    spec_file: "family/vera/spec.md"
    model: {source: "hf:x/y", format: "gguf", quant: "Q4_K_M", context_length: 1024}
    runtime: {offload_policy: "vram_then_ram"}
    memory: {collection: "member_vera"}
""")
    registry = load_registry(tmp_path / "family" / "registry.yaml")
    assert registry.concierge is None


def test_concierge_member_id_collision_fails(tmp_path):
    (tmp_path / "family").mkdir()
    spec = tmp_path / "family" / "vera"
    spec.mkdir()
    (spec / "spec.md").write_text("# Vera\n")
    (tmp_path / "family" / "registry.yaml").write_text("""
concierge:
  id: "vera"
  display_name: "Not Vera"
  spec_file: "family/vera/spec.md"
  model: {source: "hf:x/y", format: "gguf", quant: "Q5_K_M", context_length: 1024}
  runtime: {offload_policy: "vram_then_ram"}
members:
  - id: "vera"
    display_name: "Vera"
    spec_file: "family/vera/spec.md"
    model: {source: "hf:x/y", format: "gguf", quant: "Q4_K_M", context_length: 1024}
    runtime: {offload_policy: "vram_then_ram"}
    memory: {collection: "member_vera"}
""")
    with pytest.raises(RegistryError, match="collides"):
        load_registry(tmp_path / "family" / "registry.yaml")


# ---------------------------------------------------------------------------
# R2 — briefing
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

    timeline_events = []
    monkeypatch.setattr(
        server.embedder, "memory_timeline",
        lambda limit: {"events": list(timeline_events)},
    )

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        token, _ = TokenStore.load(tmp_path / "tokens.json").create("drew")
        yield client, token, server, timeline_events


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_briefing_windows_to_sleep_edge_and_hides_message_contents(hub):
    client, token, _server, timeline_events = hub

    # Before first sleep: 24h fallback window.
    res = client.get("/members/vera/briefing", headers=_auth(token)).json()
    assert res["since_source"] == "24h_fallback"

    # Vera sleeps; an event happens during the nap; a secret message queues.
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})
    asleep_at = res["generated_at"]  # any ts >= now works for ordering
    timeline_events.extend([
        {"id": "e_new", "text": "dog went out", "metadata": {"ts": "2999-01-01T00:00:00"}},
        {"id": "e_old", "text": "ancient history", "metadata": {"ts": "2000-01-01T00:00:00"}},
    ])
    msg = client.post(
        "/members/vera/chat", headers=_auth(token),
        json={"prompt": "SECRET-BANANA-PHRASE do not leak"},
    ).json()
    assert msg["queued"] is True

    briefing = client.get("/members/vera/briefing", headers=_auth(token)).json()
    assert briefing["since_source"] == "last_asleep_at"
    # Event window: the nap-time event is in, the ancient one is out.
    assert [e["id"] for e in briefing["household_events"]] == ["e_new"]
    # Custody metadata present…
    assert briefing["queued_messages"][0]["msg_id"] == msg["msg_id"]
    assert briefing["queued_messages"][0]["person"] == "drew"
    # …but the message CONTENTS appear nowhere in the payload.
    assert "SECRET-BANANA-PHRASE" not in json.dumps(briefing)
    _ = asleep_at


def test_sleep_edge_survives_restart(hub, tmp_path):
    client, token, server, _events = hub
    client.post("/members/vera/presence", headers=_auth(token), json={"presence": "asleep"})

    reborn = server.FamilyState(
        ["vera"], default_presence="asleep", store_path=tmp_path / "inbox.json"
    )
    assert reborn.last_asleep_at("vera") is not None


def test_briefing_degrades_without_embedder(hub, monkeypatch):
    client, token, server, _events = hub
    from brainstem_4070.embedder_client import EmbedderError

    def boom(limit):
        raise EmbedderError("down")

    monkeypatch.setattr(server.embedder, "memory_timeline", boom)
    res = client.get("/members/vera/briefing", headers=_auth(token))
    assert res.status_code == 200
    body = res.json()
    assert body["household_events"] == []
    assert body["household_events_error"]
    assert "queued_messages" in body


# ---------------------------------------------------------------------------
# R4 — spoken briefing. R5 — wake-cycle attachment.
# ---------------------------------------------------------------------------


class FakeJeffery:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "text": "Good morning. One message from drew; the dog went out.",
            "model": "jeffery-8b",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        }


def test_spoken_briefing_uses_jeffery_and_only_the_digest(hub, monkeypatch):
    client, token, server, _events = hub
    fake = FakeJeffery()
    monkeypatch.setattr(server, "concierge", fake)
    monkeypatch.setattr(server, "concierge_spec", "# Jeffery\nBrief factually.")

    res = client.get("/members/vera/briefing?spoken=true", headers=_auth(token)).json()
    assert res["spoken"].startswith("Good morning")
    assert res["spoken_source"] == "jeffery"
    # Jeffery's entire input is spec + the R2 JSON — nothing else.
    call = fake.calls[0]
    assert call["system"].startswith("# Jeffery")
    assert '"queued_messages"' in call["prompt"]


def test_spoken_briefing_falls_back_when_jeffery_absent(hub):
    client, token, _server, _events = hub
    # Default test config: concierge_url unset -> concierge is None.
    res = client.get("/members/vera/briefing?spoken=true", headers=_auth(token)).json()
    assert res["spoken"] is None
    assert res["spoken_source"] is None
    assert "queued_messages" in res  # the R2 contract is intact


def test_wake_drain_attaches_briefing_to_first_turn_only(tmp_path, monkeypatch):
    """R5 uses the drain path, so it needs the full cortex-stubbed rig."""
    import importlib
    import sys as _sys

    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("BRAINSTEM_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("BRAINSTEM_INBOX_STORE_PATH", str(tmp_path / "inbox.json"))
    for mod in list(_sys.modules):
        if mod.startswith("brainstem_4070"):
            del _sys.modules[mod]
    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(tmp_path / "tokens.json")

    systems_seen = []

    def fake_cortex_generate(**kwargs):
        systems_seen.append(kwargs.get("system") or "")
        return {"text": "ok", "model": "stub", "finish_reason": "stop",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(server.embedder, "memory_query", lambda **_: {"matches": []})
    monkeypatch.setattr(server.embedder, "memory_write", lambda **_: {"ok": True})
    monkeypatch.setattr(server.embedder, "memory_timeline", lambda limit: {"events": []})
    monkeypatch.setattr(server.embedder, "health", lambda: {"reachable": True})
    monkeypatch.setattr(server.cortex, "generate", fake_cortex_generate)

    from fastapi.testclient import TestClient
    from brainstem_4070.auth import TokenStore

    with TestClient(server.app) as client:
        token, _ = TokenStore.load(tmp_path / "tokens.json").create("drew")
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/members/vera/presence", headers=headers, json={"presence": "asleep"})
        client.post("/members/vera/chat", headers=headers, json={"prompt": "first"})
        client.post("/members/vera/chat", headers=headers, json={"prompt": "second"})
        woke = client.post(
            "/members/vera/presence", headers=headers, json={"presence": "awake"}
        ).json()
        assert woke["drained"] == 2

    # Two drained turns: briefing context on the first only (Jeffery is
    # absent here, so it's the data-digest fallback).
    assert "You just woke up." in systems_seen[0]
    assert '"queued_messages"' in systems_seen[0]
    assert "You just woke up." not in systems_seen[1]
