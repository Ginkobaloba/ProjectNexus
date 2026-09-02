"""Sprint 5 Card 3: scoped memory + provenance.

Done-criteria under test:
  - the server-side scope filter is always present and never widenable
    (a member's query can only ever see private:M + shared:household +
    experiential:M);
  - write-on-turn stamps provenance and lands in the member's private
    scope, for both /members/{id}/chat and the legacy /generate path;
  - cross-member writes are rejected;
  - the migration planner backfills exactly the unscoped rows
    (idempotent, copy-nothing, delete-nothing).

The scope rules are pure functions in embedder_4070.scopes so they get
tested without loading the embedding model.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest

from embedder_4070.scopes import (
    build_where,
    plan_scope_backfill,
    readable_scopes,
    validate_origin,
    validate_write_scope,
)


# ---------------------------------------------------------------------------
# Pure scope rules
# ---------------------------------------------------------------------------


def test_readable_scopes_are_exactly_three():
    assert readable_scopes("vera") == [
        "private:vera", "shared:household", "experiential:vera",
    ]


def test_where_clause_always_carries_the_scope_filter():
    where = build_where("vera")
    assert where == {"scope": {"$in": readable_scopes("vera")}}

    refined = build_where("vera", session_id_filter="sess_1",
                          exclude_parent_turn_id="sess_1:3")
    assert "$and" in refined
    # The scope condition survives every refinement.
    assert refined["$and"][0] == {"scope": {"$in": readable_scopes("vera")}}


def test_another_members_private_scope_is_never_readable():
    for scope in readable_scopes("vera"):
        assert "juno" not in scope


def test_cross_member_writes_rejected():
    validate_write_scope("private:vera", "vera")
    validate_write_scope("shared:household", "vera")
    with pytest.raises(ValueError):
        validate_write_scope("private:juno", "vera")
    with pytest.raises(ValueError):
        validate_write_scope("experiential:juno", "vera")


def test_unknown_origin_rejected():
    validate_origin("conversation")
    validate_origin("promotion")
    with pytest.raises(ValueError):
        validate_origin("osmosis")


# ---------------------------------------------------------------------------
# Migration planner
# ---------------------------------------------------------------------------


def test_backfill_touches_only_unscoped_rows():
    ids = ["a", "b", "c"]
    metas = [
        {"session_id": "s1"},                       # pre-scope row
        {"session_id": "s2", "scope": "private:vera"},  # already migrated
        None,                                        # degenerate row
    ]
    upd_ids, upd_metas = plan_scope_backfill(ids, metas, "vera", ["drew"])
    assert upd_ids == ["a", "c"]
    for meta in upd_metas:
        assert meta["scope"] == "private:vera"
        assert meta["member_id"] == "vera"
        assert meta["origin"] == "conversation"
        assert meta["participants"] == "drew"
    # Original metadata keys survive the merge.
    assert upd_metas[0]["session_id"] == "s1"


def test_backfill_is_idempotent():
    ids = ["a"]
    metas = [{"session_id": "s1"}]
    upd_ids, upd_metas = plan_scope_backfill(ids, metas, "vera")
    again_ids, _ = plan_scope_backfill(upd_ids, upd_metas, "vera")
    assert again_ids == []


# ---------------------------------------------------------------------------
# Hub integration: provenance flows through both chat paths
# ---------------------------------------------------------------------------


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Same boot recipe as tests/test_member_routing.py, but the
    embedder stubs capture the memory_write / memory_query kwargs."""
    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("BRAINSTEM_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))

    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(tmp_path / "tokens.json")

    captured = {"write": None, "query": None}

    def fake_memory_query(**kwargs):
        captured["query"] = kwargs
        return {"matches": []}

    def fake_memory_write(**kwargs):
        captured["write"] = kwargs
        return {"ok": True, "chunks": 1}

    monkeypatch.setattr(server.embedder, "memory_query", fake_memory_query)
    monkeypatch.setattr(server.embedder, "memory_write", fake_memory_write)
    monkeypatch.setattr(server.embedder, "health", lambda: {"reachable": True})
    monkeypatch.setattr(server.cortex, "generate", lambda **_: {
        "text": "stub", "model": "stub-model", "finish_reason": "stop",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    })

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        from brainstem_4070.auth import TokenStore

        token, _ = TokenStore.load(tmp_path / "tokens.json").create("drew")
        yield client, token, captured


def test_member_chat_writes_private_scope_with_provenance(hub):
    client, token, captured = hub
    res = client.post(
        "/members/vera/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "remember the dog went out at 5"},
    )
    assert res.status_code == 200, res.text

    write = captured["write"]
    assert write["scope"] == "private:vera"
    assert write["member_id"] == "vera"
    assert write["origin"] == "conversation"
    assert write["participants"] == ["drew"]

    query = captured["query"]
    assert query["member_id"] == "vera"


def test_legacy_generate_runs_as_default_member(hub):
    """/generate is the hub's default member now — no unscoped writes
    remain anywhere in the system."""
    client, token, captured = hub
    res = client.post(
        "/generate",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Session-Id": "sess_legacy",
        },
        json={"prompt": "hi"},
    )
    assert res.status_code == 200, res.text
    assert captured["write"]["scope"] == "private:vera"
    assert captured["write"]["member_id"] == "vera"
    assert captured["query"]["member_id"] == "vera"
