"""
Sprint 3d integration: live-stack smoke tests.

These run only when NEXUS_LIVE_URL and NEXUS_LIVE_TOKEN are set. They
hit a real brainstem and exercise the contracts end-to-end. They are
NOT run by default in CI, because they need the 4070 stack to be up.

To run from the 4070 host or any Tailscale-connected device:

    NEXUS_LIVE_URL=http://100.89.210.52:5001 \
    NEXUS_LIVE_TOKEN=nxs_xxx \
    pytest tests/integration/test_live_smoke.py -v

The test set is intentionally tiny: the in-process suite exercises the
contracts. The live smoke just confirms the wire really works.
"""
from __future__ import annotations

import os

import pytest
import requests


LIVE_URL = os.environ.get("NEXUS_LIVE_URL")
LIVE_TOKEN = os.environ.get("NEXUS_LIVE_TOKEN")
LIVE_SESSION = os.environ.get("NEXUS_LIVE_SESSION", "sess_live_smoke")

pytestmark = pytest.mark.skipif(
    not (LIVE_URL and LIVE_TOKEN),
    reason="set NEXUS_LIVE_URL and NEXUS_LIVE_TOKEN to run live-stack smoke tests",
)


def test_live_health_returns_200():
    res = requests.get(f"{LIVE_URL.rstrip('/')}/health", timeout=10)
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"


def test_live_root_advertises_cortex_down_contract():
    res = requests.get(f"{LIVE_URL.rstrip('/')}/", timeout=10)
    assert res.status_code == 200
    contract = res.json().get("cortex_down_contract") or {}
    assert contract.get("status") == 503


def test_live_generate_unauthenticated_returns_401():
    res = requests.post(
        f"{LIVE_URL.rstrip('/')}/generate",
        headers={"X-Session-Id": LIVE_SESSION},
        json={"prompt": "ping"},
        timeout=15,
    )
    assert res.status_code == 401


def test_live_generate_authenticated_returns_text():
    res = requests.post(
        f"{LIVE_URL.rstrip('/')}/generate",
        headers={
            "X-Session-Id": LIVE_SESSION,
            "Authorization": f"Bearer {LIVE_TOKEN}",
        },
        json={"prompt": "Reply with the single word OK.", "max_tokens": 16},
        timeout=180,
    )
    # 503 is acceptable if Cortex is down at the moment; we surface that
    # as a skipped assertion rather than a failure, since the live smoke
    # is about wire-up, not Cortex availability.
    if res.status_code == 503:
        pytest.skip(
            f"live brainstem returned 503: {res.json().get('message')}"
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body.get("text"), str)
    assert body["text"].strip(), "expected non-empty text from cortex"
    assert body.get("session_id") == LIVE_SESSION
