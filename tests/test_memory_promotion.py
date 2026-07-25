"""Sprint 5 Card 6: promotion — private -> shared:household.

Done-criteria under test:
  - the shared copy carries the full paper trail and lands in
    shared:household (visible to any member's read filter);
  - the private original is untouched (copy, never move);
  - promotion is idempotent per source row (deterministic id);
  - a member can only promote out of its own private scope;
  - the hub endpoint stamps promoted_by from token attribution.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest

from embedder_4070.scopes import (
    build_promotion_metadata,
    promoted_id,
    readable_scopes,
)


# ---------------------------------------------------------------------------
# Pure promotion rules
# ---------------------------------------------------------------------------


def test_promoted_copy_lands_in_shared_scope_with_paper_trail():
    source = {
        "scope": "private:vera",
        "member_id": "vera",
        "origin": "conversation",
        "participants": "drew",
        "session_id": "s1",
        "ts": "2026-07-25T22:00:00+00:00",
    }
    meta = build_promotion_metadata(source, "vera", "drew", "s1:0:0")
    assert meta["scope"] == "shared:household"
    assert meta["member_id"] == "household"
    assert meta["origin"] == "promotion"
    assert meta["promoted_from"] == "s1:0:0"
    assert meta["promoted_from_member"] == "vera"
    assert meta["promoted_by"] == "drew"
    # Non-provenance metadata (ts, session) survives the copy.
    assert meta["ts"] == source["ts"]
    # The source dict is not mutated — copy, never move.
    assert source["scope"] == "private:vera"


def test_promoted_copy_is_visible_to_every_member():
    meta = build_promotion_metadata(
        {"scope": "private:vera"}, "vera", "drew", "row1"
    )
    for member in ("vera", "juno", "anyone"):
        assert meta["scope"] in readable_scopes(member)


def test_cannot_promote_out_of_someone_elses_scope():
    with pytest.raises(ValueError):
        build_promotion_metadata({"scope": "private:juno"}, "vera", "drew", "row1")
    with pytest.raises(ValueError):
        build_promotion_metadata({"scope": "shared:household"}, "vera", "drew", "row1")
    with pytest.raises(ValueError):
        build_promotion_metadata({}, "vera", "drew", "row1")


def test_promoted_id_is_deterministic():
    assert promoted_id("s1:0:0") == promoted_id("s1:0:0")
    assert promoted_id("s1:0:0") != promoted_id("s1:0:1")


# ---------------------------------------------------------------------------
# Hub endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("BRAINSTEM_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(tmp_path / "tokens.json")

    captured = {}

    def fake_promote(**kwargs):
        captured.update(kwargs)
        return {
            "promoted_id": promoted_id(kwargs["memory_id"]),
            "promoted_from": kwargs["memory_id"],
            "already_promoted": False,
        }

    monkeypatch.setattr(server.embedder, "memory_promote", fake_promote)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        token, _ = TokenStore.load(tmp_path / "tokens.json").create("drew")
        yield client, token, captured


def test_hub_promotion_stamps_person_from_token(hub):
    client, token, captured = hub
    res = client.post(
        "/members/vera/memory/promote",
        headers={"Authorization": f"Bearer {token}"},
        json={"memory_id": "sess_abc:3:0"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["promoted_id"] == promoted_id("sess_abc:3:0")
    assert captured == {
        "member_id": "vera",
        "memory_id": "sess_abc:3:0",
        "promoted_by": "drew",
    }


def test_hub_promotion_requires_auth_and_known_member(hub):
    client, token, _captured = hub
    assert client.post(
        "/members/vera/memory/promote", json={"memory_id": "x"}
    ).status_code == 401
    assert client.post(
        "/members/nobody/memory/promote",
        headers={"Authorization": f"Bearer {token}"},
        json={"memory_id": "x"},
    ).status_code == 404
