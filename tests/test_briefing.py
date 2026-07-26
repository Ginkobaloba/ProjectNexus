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
