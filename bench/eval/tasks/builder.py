"""
Task 1: Builder (workflow synthesis).

Headline metric per NEXUS_PATH_TO_OUTPERFORM section 1.3:
    valid@1 and exec-success on the Builder held-out set.

This skeleton ships:
    - the frozen Builder prompt at bench/eval/prompts/builder.txt
    - a 5-example placeholder dataset at
      bench/eval/datasets/builder_skeleton_v1.jsonl
    - a deterministic verifier chain:
        1. parse fenced JSON out of the completion
        2. validate the schema (name + nodes + connections, dict shape)
        3. validate every node type is in the whitelist
        4. validate every reference in connections points at a real node
        5. validate the spec's `required_nodes` are present
        6. exec-success: a separate "would this n8n actually run" check;
           in the skeleton this is a static structural simulator. Card 5+
           swaps it for the n8n MCP `validate_workflow` oracle.

Metrics emitted:
    valid_at_1     1.0 if the completion parses + validates + meets required_nodes
    exec_success   1.0 if valid AND the structural exec sim passes

Both are 0/1 per problem; the task aggregates them as the per-seed mean.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem, load_jsonl


HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE.parent / "datasets" / "builder_skeleton_v1.jsonl"
PROMPT_PATH = HERE.parent / "prompts" / "builder.txt"

NODE_WHITELIST = {
    "webhook",
    "function",
    "if",
    "set",
    "http",
    "schedule",
    "code",
}

# Regex pulls the first fenced code block out of a completion. The Builder
# prompt explicitly asks for "exactly one fenced code block of JSON". The
# scorer is tolerant of either ```json or ``` fence opener.
_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


class BuilderTask(EvalTaskBase):
    task_id = "builder"
    primary_metric = "valid_at_1"
    secondary_metrics = ["exec_success"]
    stub_placeholder = False
    dataset_id = "builder_skeleton_v1"

    def __init__(self, dataset_path: Path = DATASET_PATH, prompt_path: Path = PROMPT_PATH):
        self.dataset_path = Path(dataset_path)
        self.prompt_path = Path(prompt_path)
        self._prompt_template: str | None = None

    # -----------------------------------------------------------------
    # EvalTaskBase hooks
    # -----------------------------------------------------------------

    def load_problems(self) -> Sequence[Problem]:
        records = load_jsonl(str(self.dataset_path))
        out: List[Problem] = []
        for rec in records:
            out.append(
                Problem(
                    problem_id=rec["problem_id"],
                    prompt=rec["spec"],
                    reference=rec.get("reference", {}),
                    meta=rec.get("meta", {}),
                )
            )
        return out

    def build_prompt(self, problem: Problem) -> str:
        if self._prompt_template is None:
            self._prompt_template = self.prompt_path.read_text(encoding="utf-8")
        return self._prompt_template.replace("{spec}", problem.prompt)

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        valid, parsed_or_none, _err = _validate_builder_output(
            completion=completion,
            reference=problem.reference,
        )
        exec_ok = 0.0
        if valid and parsed_or_none is not None:
            exec_ok = 1.0 if _structural_exec_sim(parsed_or_none) else 0.0
        return {
            "valid_at_1": 1.0 if valid else 0.0,
            "exec_success": exec_ok,
        }

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = len(self.load_problems())
        meta["dataset_path"] = os.path.relpath(self.dataset_path, HERE.parent.parent.parent)
        meta["prompt_path"] = os.path.relpath(self.prompt_path, HERE.parent.parent.parent)
        meta["node_whitelist"] = sorted(NODE_WHITELIST)
        return meta


def get_task() -> BuilderTask:
    return BuilderTask()


# ---------------------------------------------------------------------------
# Scoring internals (kept pure so tests can drive them directly)
# ---------------------------------------------------------------------------


def _extract_json_block(text: str) -> str | None:
    """Pull the first fenced code block out of `text`. If no fence is present,
    fall back to the raw text if it looks like a JSON object."""
    m = _FENCE_RE.search(text or "")
    if m is not None:
        return m.group("body")
    stripped = (text or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    return None


def _validate_builder_output(
    completion: str,
    reference: Dict[str, Any],
) -> tuple[bool, Dict[str, Any] | None, str | None]:
    """Deterministic validator chain. Returns (valid, parsed_or_none, error)."""
    body = _extract_json_block(completion)
    if body is None:
        return False, None, "no_fenced_json"

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        return False, None, f"json_parse_error: {e.msg}"

    if not isinstance(parsed, dict):
        return False, None, "root_not_object"
    if "nodes" not in parsed or "connections" not in parsed:
        return False, None, "missing_required_keys"
    if not isinstance(parsed["nodes"], list) or not parsed["nodes"]:
        return False, None, "nodes_not_nonempty_list"
    if not isinstance(parsed["connections"], dict):
        return False, None, "connections_not_object"

    node_names: List[str] = []
    for n in parsed["nodes"]:
        if not isinstance(n, dict):
            return False, parsed, "node_not_object"
        if "name" not in n or "type" not in n:
            return False, parsed, "node_missing_name_or_type"
        node_type = str(n["type"]).lower()
        if node_type not in NODE_WHITELIST:
            return False, parsed, f"node_type_not_whitelisted: {n['type']}"
        node_names.append(str(n["name"]))

    if len(set(node_names)) != len(node_names):
        return False, parsed, "duplicate_node_names"

    # Connection references must point at real nodes.
    for src, edges in parsed["connections"].items():
        if src not in node_names:
            return False, parsed, f"connection_src_unknown: {src}"
        if not isinstance(edges, list):
            return False, parsed, "edges_not_list"
        for edge in edges:
            if not isinstance(edge, dict) or "node" not in edge:
                return False, parsed, "edge_missing_node_field"
            if edge["node"] not in node_names:
                return False, parsed, f"edge_dst_unknown: {edge['node']}"

    # Required-nodes check from the reference.
    required = [str(t).lower() for t in reference.get("required_nodes", [])]
    if required:
        present_types = [str(n["type"]).lower() for n in parsed["nodes"]]
        for req in required:
            if req not in present_types:
                return False, parsed, f"required_node_missing: {req}"

    min_nodes = int(reference.get("min_nodes", 0))
    if min_nodes and len(parsed["nodes"]) < min_nodes:
        return False, parsed, f"too_few_nodes: {len(parsed['nodes'])} < {min_nodes}"

    return True, parsed, None


def _structural_exec_sim(parsed: Dict[str, Any]) -> bool:
    """Skeleton exec-success oracle. The real oracle is the n8n MCP
    `validate_workflow` + execution; this stand-in is structural only:

        - workflow has exactly one trigger node (no incoming edge); n8n
          workflows have a single entry point
        - every other node is reachable from that trigger via connections

    A passing structural sim is necessary but not sufficient for true exec
    success. Card 5+ swaps in the real oracle.
    """
    nodes = {str(n["name"]) for n in parsed.get("nodes", [])}
    if not nodes:
        return False

    # Build outgoing/incoming maps.
    out_edges: Dict[str, List[str]] = {n: [] for n in nodes}
    in_edges: Dict[str, List[str]] = {n: [] for n in nodes}
    for src, edges in parsed.get("connections", {}).items():
        for edge in edges:
            dst = edge.get("node")
            if dst in nodes and src in nodes:
                out_edges[src].append(dst)
                in_edges[dst].append(src)

    sources = [n for n, ins in in_edges.items() if not ins]
    # An n8n workflow has exactly one trigger. Multiple sources usually means
    # a node was left orphan; zero sources means a cycle with no entry point.
    if len(sources) != 1:
        return False

    # Reachability: BFS from the single trigger; every node must be visited.
    visited = set()
    queue = list(sources)
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        queue.extend(out_edges.get(cur, []))
    return visited == nodes
