"""
Sprint 3d integration: X-Session-Id propagation and cross-session
memory recall, observed end-to-end through the brainstem.

These are the Sprint 2 done-criteria, validated with Sprint 3b auth in
place. The brainstem is supposed to:

1. Require X-Session-Id on /generate (Sprint 2 contract).
2. Write each turn into memory under that session_id.
3. Retrieve, before the next generation, across ALL sessions (the
   default retrieval is cross-session).

The fake memory store in conftest is dumb on purpose: it ranks by
token-overlap, not by embedding similarity. That is enough to assert
that a prior turn in session A is recovered when session B asks
something with overlapping tokens.

Token-flavor coverage:
- same token, two sessions: retrieval should still cross between them.
- different token, two sessions: retrieval is NOT scoped by token; the
  brainstem only scopes by session_id, and the default retrieval is
  unscoped. So a turn written by Alice's token should be retrievable
  in a session opened with Bob's token. If that's a future security
  requirement, this test will surface it loudly.
"""
from __future__ import annotations


def test_x_session_id_is_required(brainstem):
    """Sprint 2: explicit X-Session-Id is mandatory. Missing -> 400."""
    token = brainstem.mint_token("laptop")
    res = brainstem.client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "hi"},
    )
    assert res.status_code == 400
    assert "X-Session-Id" in res.json()["detail"]


def test_session_id_propagates_to_memory_write(brainstem):
    """A successful turn writes a memory row stamped with the same
    session_id the client sent."""
    token = brainstem.mint_token("laptop")
    res = brainstem.post_generate(
        prompt="my favorite color is teal",
        token=token,
        session_id="sess_alpha",
    )
    assert res.status_code == 200, res.text
    assert res.json()["session_id"] == "sess_alpha"

    rows = [r for r in brainstem.memory.rows if r["session_id"] == "sess_alpha"]
    assert rows, "expected a memory row written under the request's session_id"
    assert rows[-1]["user_text"] == "my favorite color is teal"
    assert rows[-1]["turn_idx"] == 0


def test_session_id_propagates_to_memory_query(brainstem):
    """The brainstem's retrieve-before-generate call should include
    the request's session_id on the query so the embedder can do
    session-aware ranking if it wants to. The brainstem itself does
    NOT pass a session_id_filter; retrieval is cross-session by
    default. We assert both behaviors."""
    token = brainstem.mint_token("laptop")
    res = brainstem.post_generate(
        prompt="anything will do",
        token=token,
        session_id="sess_query_propagation",
    )
    assert res.status_code == 200, res.text

    assert brainstem.memory.last_query is not None
    assert brainstem.memory.last_query["session_id"] == "sess_query_propagation"
    # Brainstem does not scope retrieval to one session: that is the
    # whole point of the cross-session done-criterion.
    assert brainstem.memory.last_query["session_id_filter"] is None


def test_cross_session_recall_same_token(brainstem):
    """Sprint 2 done-criterion, same-token flavor.

    Write a turn in session A with token X. Open session B with the
    SAME token X. Ask something that shares tokens with the session A
    turn. The brainstem should retrieve the session A turn and inject
    it into the system prompt that lands at Cortex.
    """
    token = brainstem.mint_token("laptop")

    # Turn 1 in session A: introduce a fact.
    res = brainstem.post_generate(
        prompt="my dog is named pavlov and he loves peanut butter",
        token=token,
        session_id="sess_A_same_token",
    )
    assert res.status_code == 200, res.text

    # Turn 2 in session B (same token): ask about the fact.
    brainstem.cortex.calls.clear()
    res = brainstem.post_generate(
        prompt="what is the name of my dog?",
        token=token,
        session_id="sess_B_same_token",
    )
    assert res.status_code == 200, res.text

    # The brainstem must have built a system prompt that includes the
    # prior turn. The fake Cortex records what the brainstem sent.
    assert brainstem.cortex.calls, "expected the brainstem to call cortex"
    sent_system = brainstem.cortex.calls[-1]["system"] or ""
    assert "pavlov" in sent_system.lower(), (
        f"prior turn from session A should appear in the system prompt "
        f"sent to Cortex; got: {sent_system!r}"
    )


def test_cross_session_recall_different_token(brainstem):
    """Sprint 2 cross-session recall, different-token flavor.

    The default retrieval is not token-scoped. A turn written by one
    client's token should be retrievable from a request bearing a
    different valid token. If a future security pass wants to scope
    memory by client identity, this test will turn red and we will
    update the contract intentionally.
    """
    laptop_token = brainstem.mint_token("laptop")
    phone_token = brainstem.mint_token("phone")

    # Laptop writes a fact in session A.
    res = brainstem.post_generate(
        prompt="my favorite mountain is mount rainier",
        token=laptop_token,
        session_id="sess_A_xtok",
    )
    assert res.status_code == 200, res.text

    # Phone opens session B and asks about the fact.
    brainstem.cortex.calls.clear()
    res = brainstem.post_generate(
        prompt="what is my favorite mountain?",
        token=phone_token,
        session_id="sess_B_xtok",
    )
    assert res.status_code == 200, res.text

    sent_system = brainstem.cortex.calls[-1]["system"] or ""
    assert "rainier" in sent_system.lower(), (
        f"a turn written under one token should be retrievable in a "
        f"session opened with a different token; got: {sent_system!r}"
    )


def test_turn_idx_increments_per_session(brainstem):
    """turn_idx is per-session-monotonic. Two sessions should have
    independent counters; this is the Sprint 2 contract."""
    token = brainstem.mint_token("laptop")

    for i in range(3):
        res = brainstem.post_generate(
            prompt=f"session A turn {i}",
            token=token,
            session_id="sess_idx_A",
        )
        assert res.status_code == 200, res.text
        assert res.json()["turn_idx"] == i

    # Second session: counter starts at 0 again.
    res = brainstem.post_generate(
        prompt="session B turn 0",
        token=token,
        session_id="sess_idx_B",
    )
    assert res.status_code == 200, res.text
    assert res.json()["turn_idx"] == 0
