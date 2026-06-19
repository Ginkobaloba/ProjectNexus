"""Card 5 Decision 3: n8n MCP `validate_workflow` replaces the structural
single-trigger reachability sim as the canonical exec-success oracle for
Task 1 (Builder). When the MCP is unreachable, the structural sim stands in.

These tests exercise both paths without touching a real MCP container.
"""
from __future__ import annotations

import json

import pytest

from bench.eval.tasks import _n8n_oracle
from bench.eval.tasks.builder import BuilderTask


VALID_WF = {
    "name": "intake",
    "nodes": [
        {"name": "in", "type": "webhook"},
        {"name": "tag", "type": "set"},
        {"name": "fwd", "type": "http"},
    ],
    "connections": {
        "in": [{"node": "tag"}],
        "tag": [{"node": "fwd"}],
    },
}


def _wrap(obj):
    return "```json\n" + json.dumps(obj) + "\n```"


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


def test_oracle_mode_explicit_structural(monkeypatch):
    """An explicit override picks structural without probing."""
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "structural")
    # Make probing fail loudly if called.
    monkeypatch.setattr(
        _n8n_oracle,
        "is_n8n_mcp_available",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not probe")),
    )
    task = BuilderTask()
    assert task.oracle_mode == "structural_sim"


def test_oracle_mode_explicit_mcp(monkeypatch):
    """An explicit override picks mcp without probing."""
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "mcp")
    monkeypatch.setattr(
        _n8n_oracle,
        "is_n8n_mcp_available",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not probe")),
    )
    task = BuilderTask()
    assert task.oracle_mode == "mcp"


def test_oracle_mode_auto_falls_back_to_structural_when_mcp_offline(monkeypatch):
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "auto")
    monkeypatch.setattr(_n8n_oracle, "is_n8n_mcp_available", lambda *_a, **_k: False)
    task = BuilderTask()
    assert task.oracle_mode == "structural_sim"


def test_oracle_mode_auto_picks_mcp_when_available(monkeypatch):
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "auto")
    monkeypatch.setattr(_n8n_oracle, "is_n8n_mcp_available", lambda *_a, **_k: True)
    task = BuilderTask()
    assert task.oracle_mode == "mcp"


# ---------------------------------------------------------------------------
# Scoring uses the active oracle
# ---------------------------------------------------------------------------


def test_score_uses_mcp_path_when_mode_is_mcp(monkeypatch):
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "mcp")
    calls = []

    def fake_validate(workflow, cfg=None):
        calls.append({"workflow": workflow, "cfg": cfg})
        return True, {"result": {"valid": True}}

    monkeypatch.setattr(_n8n_oracle, "validate_workflow_via_mcp", fake_validate)
    task = BuilderTask()
    p = next(iter(task.load_problems()))
    # build a wf that passes the validator chain
    wf = {
        "name": p.problem_id,
        "nodes": [{"name": n, "type": n} for n in p.reference["required_nodes"]],
        "connections": {},
    }
    req = p.reference["required_nodes"]
    for i in range(len(req) - 1):
        wf["connections"][req[i]] = [{"node": req[i + 1]}]
    m = task.score(p, _wrap(wf))
    assert m["valid_at_1"] == 1.0
    assert m["exec_success"] == 1.0
    assert len(calls) == 1, "MCP oracle must be invoked exactly once per scored problem"


def test_score_uses_structural_when_mode_is_structural(monkeypatch):
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "structural")

    def must_not_be_called(*_a, **_k):
        raise AssertionError("structural mode must not call MCP")

    monkeypatch.setattr(_n8n_oracle, "validate_workflow_via_mcp", must_not_be_called)
    task = BuilderTask()
    p = next(iter(task.load_problems()))
    wf = {
        "name": p.problem_id,
        "nodes": [{"name": n, "type": n} for n in p.reference["required_nodes"]],
        "connections": {},
    }
    req = p.reference["required_nodes"]
    for i in range(len(req) - 1):
        wf["connections"][req[i]] = [{"node": req[i + 1]}]
    m = task.score(p, _wrap(wf))
    assert m["valid_at_1"] == 1.0
    assert m["exec_success"] == 1.0


def test_score_records_mcp_invalid_as_zero(monkeypatch):
    """If the MCP says valid=False, exec_success is 0 even when the validator
    chain accepted the workflow. This is the whole point of replacing the
    permissive structural sim with the canonical oracle."""
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "mcp")
    monkeypatch.setattr(
        _n8n_oracle,
        "validate_workflow_via_mcp",
        lambda wf, cfg=None: (False, {"result": {"valid": False, "errors": ["bad expr"]}}),
    )
    task = BuilderTask()
    p = next(iter(task.load_problems()))
    wf = {
        "name": p.problem_id,
        "nodes": [{"name": n, "type": n} for n in p.reference["required_nodes"]],
        "connections": {},
    }
    req = p.reference["required_nodes"]
    for i in range(len(req) - 1):
        wf["connections"][req[i]] = [{"node": req[i + 1]}]
    m = task.score(p, _wrap(wf))
    assert m["valid_at_1"] == 1.0
    assert m["exec_success"] == 0.0


# ---------------------------------------------------------------------------
# Probe behavior
# ---------------------------------------------------------------------------


def test_probe_returns_false_on_unreachable(monkeypatch):
    """Point the probe at a port no one is listening on and confirm it returns
    False within the probe timeout."""
    monkeypatch.setenv("NEXUS_BENCH_N8N_MCP_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("NEXUS_BENCH_N8N_MCP_PROBE_TIMEOUT", "0.5")
    cfg = _n8n_oracle.oracle_config_from_env()
    assert _n8n_oracle.is_n8n_mcp_available(cfg) is False


# ---------------------------------------------------------------------------
# task_meta reports the active oracle mode (Card 5 requirement)
# ---------------------------------------------------------------------------


def test_task_meta_records_oracle_mode(monkeypatch):
    monkeypatch.setenv("NEXUS_BENCH_BUILDER_ORACLE", "structural")
    task = BuilderTask()
    meta = task.task_meta()
    assert meta["oracle"]["mode"] == "structural_sim"
    assert "n8n_mcp_config" in meta["oracle"]
    assert "dataset_caveat" in meta
    assert "5-example" in meta["dataset_caveat"]
