"""
Sprint 3d integration: auth paths exercised end-to-end.

These mirror tests/test_auth.py at the unit level, but from a generic
client's perspective: HTTP in, HTTP out, no reaching into the internals
of the auth module. A client that talks to the brainstem only over the
public contract should observe exactly the behaviors asserted below.
"""
from __future__ import annotations


def test_generate_without_bearer_returns_401(brainstem):
    """No Authorization header -> 401. Body carries `detail` so a CLI or
    web client can print something useful."""
    res = brainstem.post_generate(
        prompt="hello",
        token=None,
        session_id="sess_no_auth",
    )
    assert res.status_code == 401
    body = res.json()
    assert "detail" in body
    assert "Authorization" in body["detail"]


def test_generate_with_invalid_token_returns_401(brainstem):
    """Bearer header present but the token is not a real one."""
    res = brainstem.post_generate(
        prompt="hello",
        token="nxs_definitely_not_a_real_token_value_at_all",
        session_id="sess_bad_token",
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid token"


def test_generate_with_revoked_token_returns_401(brainstem):
    """A previously-valid token starts returning 401 after revocation
    without restarting the brainstem. The token-store mtime reload is
    what makes this work; this test asserts the observable behavior."""
    token = brainstem.mint_token("laptop")

    # Sanity: token works first.
    res = brainstem.post_generate(
        prompt="hi", token=token, session_id="sess_revoke",
    )
    assert res.status_code == 200, res.text

    # Revoke and immediately re-use; should now 401.
    assert brainstem.revoke("laptop") is True
    res = brainstem.post_generate(
        prompt="hi", token=token, session_id="sess_revoke",
    )
    assert res.status_code == 401


def test_generate_with_valid_token_returns_200(brainstem):
    """Happy path: valid token, cortex up, get a response back."""
    token = brainstem.mint_token("laptop")
    res = brainstem.post_generate(
        prompt="say hi please",
        token=token,
        session_id="sess_happy",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "stub response"
    assert body["session_id"] == "sess_happy"
    assert body["memory_written"] is True
    # The brainstem should attribute the call to the token. Metrics
    # check lives in a dedicated test below, but the immediate response
    # also has the model id from the fake cortex.
    assert body["model"] == "fake-cortex/llama-stub"


def test_malformed_authorization_header_returns_401(brainstem):
    """Authorization header without the `Bearer` scheme -> 401. Catches
    a class of client mistakes (raw token, basic auth, etc.) loudly."""
    token = brainstem.mint_token("laptop")
    headers = {"X-Session-Id": "sess_bad_header", "Authorization": token}
    res = brainstem.client.post(
        "/generate",
        headers=headers,
        json={"prompt": "hi"},
    )
    assert res.status_code == 401


def test_health_anonymous_even_with_no_tokens_minted(brainstem):
    """A fresh deploy with zero tokens minted must still be observable
    by a load balancer hitting /health. No auth required, ever."""
    res = brainstem.client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
