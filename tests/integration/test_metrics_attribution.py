"""
Sprint 3d integration: metric attribution holds across the happy path
and the Sprint 3c 503 path. The dashboard depends on the per-token,
per-session attribution being present in BOTH cases. A silent loss of
attribution on the failure path would make outages invisible per
client; we want to see Drew's phone failing distinct from Drew's
laptop failing.
"""
from __future__ import annotations

import json
from pathlib import Path


def _read_metric_lines(metrics_path: Path) -> list:
    return [
        json.loads(l)
        for l in metrics_path.read_text("utf-8").splitlines()
        if l.strip()
    ]


def test_metric_record_attributes_token_on_happy_path(brainstem):
    token = brainstem.mint_token("laptop")
    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_attr_ok",
    )
    assert res.status_code == 200, res.text

    lines = _read_metric_lines(brainstem.metrics_path)
    assert lines, "expected a metric record from the successful call"
    last = lines[-1]
    assert last.get("token_name") == "laptop"
    assert last.get("session_id") == "sess_attr_ok"
    assert last.get("ok") is True
    assert last.get("memory_written") is True


def test_metric_record_attributes_token_on_cortex_down(brainstem):
    token = brainstem.mint_token("phone")
    brainstem.cortex.down = True

    res = brainstem.post_generate(
        prompt="hello",
        token=token,
        session_id="sess_attr_down",
    )
    assert res.status_code == 503

    lines = _read_metric_lines(brainstem.metrics_path)
    assert lines, "expected a metric record even on a Cortex-down call"
    last = lines[-1]
    assert last.get("token_name") == "phone"
    assert last.get("session_id") == "sess_attr_down"
    assert last.get("ok") is False
    assert last.get("memory_written") is False
