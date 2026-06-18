"""
Sprint 3d integration: the Sprint 3c Cortex-down 503 contract observed
from a generic client. See docs/exposure_and_cortex_down.md.

Layered on top of tests/test_cortex_down.py: the unit-level coverage
lives there. This file checks the contract from the outside, including
the X-Session-Id propagation through the 503 body and that the
Retry-After header carries the same integer the body advertises.
"""
from __future__ import annotations


def test_generate_returns_503_when_cortex_down(brainstem):
    """Connection-refused failure flavor: short retry window."""
    token = brainstem.mint_token("laptop")
    brainstem.cortex.down = True
    brainstem.cortex.failure_kind = "connection"

    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_down",
    )
    assert res.status_code == 503

    body = res.json()
    assert body["error"] == "cortex_unavailable"
    assert isinstance(body["retry_after_seconds"], int)
    assert body["retry_after_seconds"] >= 1
    assert body["session_id"] == "sess_down"
    assert body["turn_idx"] is None
    assert "brainstem is up" in body["message"].lower()


def test_cortex_down_response_has_retry_after_header(brainstem):
    """RFC-7231 compliant clients consume Retry-After; the brainstem
    contract carries the same integer in body and header."""
    token = brainstem.mint_token("laptop")
    brainstem.cortex.down = True
    brainstem.cortex.failure_kind = "connection"

    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_retry_after",
    )
    assert res.status_code == 503
    assert res.headers.get("Retry-After") == str(res.json()["retry_after_seconds"])


def test_cortex_timeout_is_classified_separately(brainstem):
    """A timeout means Cortex took the request but is slow. Earns the
    longer retry window and the cortex_timeout error code."""
    token = brainstem.mint_token("laptop")
    brainstem.cortex.down = True
    brainstem.cortex.failure_kind = "timeout"

    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_timeout",
    )
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "cortex_timeout"
    assert body["retry_after_seconds"] >= 10
    assert res.headers.get("Retry-After") == str(body["retry_after_seconds"])


def test_health_stays_200_while_cortex_down(brainstem):
    """A Cortex outage must not take the brainstem out of rotation. The
    /health endpoint is only allowed to fail if the brainstem itself is
    in trouble; downstream peer failures do not count."""
    brainstem.cortex.down = True

    res = brainstem.client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["embedder_reachable"] is True


def test_root_contract_documents_cortex_down_shape(brainstem):
    """The `/` index advertises the 503 shape for client discoverability."""
    res = brainstem.client.get("/")
    assert res.status_code == 200
    contract = res.json().get("cortex_down_contract") or {}
    assert contract.get("status") == 503
    assert contract.get("header") == "Retry-After"
    codes = contract.get("error_codes") or []
    assert "cortex_unavailable" in codes
    assert "cortex_timeout" in codes


def test_cortex_down_followed_by_recovery_succeeds(brainstem):
    """The first call sees Cortex down, the second sees it up. The
    brainstem should not be sticky about the failure: a recovered
    Cortex starts producing 200s again. This guards against the
    pattern where a process-level circuit breaker would unexpectedly
    keep failing past the retry window."""
    token = brainstem.mint_token("laptop")

    brainstem.cortex.down = True
    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_recover",
    )
    assert res.status_code == 503

    brainstem.cortex.down = False
    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_recover",
    )
    assert res.status_code == 200, res.text
    assert res.json()["text"] == "stub response"
