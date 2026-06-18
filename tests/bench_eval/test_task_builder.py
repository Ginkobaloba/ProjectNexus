"""Task 1 (Builder) scorer is deterministic given a fixed completion, and the
validator chain catches the right failure modes."""
from __future__ import annotations

import json

import pytest

from bench.eval.base import Problem
from bench.eval.tasks.builder import (
    BuilderTask,
    _extract_json_block,
    _structural_exec_sim,
    _validate_builder_output,
)


# ---- A canonical valid workflow we can mutate to exercise failure paths ----

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


def _wrap(json_obj):
    return "```json\n" + json.dumps(json_obj) + "\n```"


def _ref():
    return {"required_nodes": ["webhook", "set", "http"], "min_nodes": 3}


def test_extract_json_block_handles_fenced_and_bare():
    fenced = "```json\n{\"a\": 1}\n```"
    assert _extract_json_block(fenced) == '{"a": 1}'
    bare = "{\"a\": 1}"
    assert _extract_json_block(bare) == bare
    assert _extract_json_block("not json at all") is None


def test_validator_accepts_valid_workflow():
    ok, parsed, err = _validate_builder_output(_wrap(VALID_WF), _ref())
    assert ok is True
    assert err is None
    assert parsed is not None


def test_validator_rejects_unparseable_json():
    ok, parsed, err = _validate_builder_output("not json", _ref())
    assert ok is False
    assert err == "no_fenced_json"


def test_validator_rejects_unknown_node_type():
    wf = json.loads(json.dumps(VALID_WF))
    wf["nodes"][1]["type"] = "kafka"  # not on the whitelist
    ok, _, err = _validate_builder_output(_wrap(wf), _ref())
    assert ok is False
    assert "node_type_not_whitelisted" in err


def test_validator_rejects_missing_required_node():
    wf = json.loads(json.dumps(VALID_WF))
    # Drop the http node entirely
    wf["nodes"] = wf["nodes"][:2]
    wf["connections"] = {"in": [{"node": "tag"}]}
    ok, _, err = _validate_builder_output(_wrap(wf), _ref())
    assert ok is False
    assert "required_node_missing" in err


def test_validator_rejects_dangling_connection():
    wf = json.loads(json.dumps(VALID_WF))
    wf["connections"]["in"] = [{"node": "ghost"}]
    ok, _, err = _validate_builder_output(_wrap(wf), _ref())
    assert ok is False
    assert "edge_dst_unknown" in err


def test_structural_exec_sim_passes_on_valid_workflow():
    assert _structural_exec_sim(VALID_WF) is True


def test_structural_exec_sim_fails_on_disconnected_graph():
    wf = json.loads(json.dumps(VALID_WF))
    # Drop the connection that reaches fwd, leaving it isolated.
    wf["connections"] = {"in": [{"node": "tag"}]}
    assert _structural_exec_sim(wf) is False


def test_builder_score_is_deterministic_given_fixed_completion():
    task = BuilderTask()
    p = next(iter(task.load_problems()))
    # craft a completion that satisfies p
    wf = {
        "name": p.problem_id,
        "nodes": [{"name": n, "type": n} for n in p.reference["required_nodes"]],
        "connections": {},
    }
    # chain them: required[0] -> required[1] -> ... so structural sim passes
    req = p.reference["required_nodes"]
    for i in range(len(req) - 1):
        wf["connections"][req[i]] = [{"node": req[i + 1]}]
    completion = _wrap(wf)

    m1 = task.score(p, completion)
    m2 = task.score(p, completion)
    assert m1 == m2
    assert m1["valid_at_1"] == 1.0
    assert m1["exec_success"] == 1.0


def test_builder_score_zero_on_garbage_completion():
    task = BuilderTask()
    p = next(iter(task.load_problems()))
    m = task.score(p, "I cannot help with that")
    assert m["valid_at_1"] == 0.0
    assert m["exec_success"] == 0.0
