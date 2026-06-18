# bench/eval/verifier.py
"""
The verifier oracle for Builder workflow synthesis.

Three free, programmatic stages, in the order the program design specifies
(NEXUS_PATH_TO_OUTPERFORM_v0.1.md, task family 1):

    1. JSON parse      -- strip markdown fences + repair control chars, then parse
    2. node whitelist  -- every node.type must be in the Builder whitelist
    3. n8n validate     -- n8n-mcp's validate_workflow against the real node DB

Stages 1 and 2 are a faithful port of Nexus.Builder NODE 4 ("Parse and Validate").
Stage 3 is delegated to oracle_bridge/validate_oracle.js, which instantiates the
exact WorkflowValidator the `validate_workflow` MCP tool uses. A candidate is
`valid` only if it clears all three stages -- that boolean is what valid@1 and
valid@k are computed over. There is no gold-JSON comparison: the oracle is the
ground truth, which is the whole point of leading with a verifiable task.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Stage labels (also the failure-attribution buckets in the run report).
STAGE_PARSE = "parse"
STAGE_WHITELIST = "whitelist"
STAGE_VALIDATE = "validate"
STAGE_PASS = "pass"


@dataclass
class Verdict:
    valid: bool
    stage_failed: Optional[str]  # None when valid
    errors: List[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    parsed: Optional[Dict[str, Any]] = None


def _repair_control_chars(raw: str) -> str:
    """Escape raw control chars inside JSON string values.

    Port of NODE 4's repairJson: Qwen sometimes emits literal newlines/tabs inside
    string values, which json.loads rejects. We only touch chars inside strings.
    """
    out = []
    in_string = False
    escaped = False
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 32:
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append("\\u%04x" % ord(ch))
            continue
        out.append(ch)
    return "".join(out)


def parse_workflow(raw_content: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract a workflow dict from an LLM completion. Mirrors NODE 4 steps A-B.

    Returns (parsed, None) on success or (None, error_message) on failure.
    """
    if raw_content is None:
        return None, "LLM returned null content"
    text = raw_content.strip()
    if not text:
        return None, "empty completion"
    # Strip markdown fences if present.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text[3:] if text.startswith("```") else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        # Also handle a leading ```json that survived the split.
        text = text.lstrip()
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        try:
            return json.loads(_repair_control_chars(text)), None
        except json.JSONDecodeError:
            return None, f"JSON parse failed: {e}"


def check_whitelist(parsed: Dict[str, Any], whitelist: List[str]) -> Tuple[bool, List[str]]:
    """Node-whitelist check. Mirrors NODE 4 step C. Also enforces basic structure
    (nodes array + connections object) the way NODE 4 step D does."""
    wl = set(whitelist)
    nodes = parsed.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False, ['missing or empty "nodes" array']
    if not isinstance(parsed.get("connections"), dict):
        return False, ['missing "connections" object']
    bad = sorted({n.get("type", "<no type>") for n in nodes if n.get("type") not in wl})
    if bad:
        return False, [f"non-whitelisted node types: {', '.join(bad)}"]
    return True, []


class ValidateOracle:
    """Long-lived bridge to n8n-mcp validate_workflow (oracle_bridge/validate_oracle.js).

    Spawns the Node process once, loads the node DB once, then streams candidates
    over stdin/stdout. Use as a context manager.
    """

    def __init__(
        self,
        n8n_mcp_dir: str,
        profile: str = "runtime",
        node_db_path: Optional[str] = None,
        script_path: Optional[str] = None,
    ):
        self.n8n_mcp_dir = n8n_mcp_dir
        self.profile = profile
        self.node_db_path = node_db_path
        self.script_path = script_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "oracle_bridge", "validate_oracle.js"
        )
        self._proc: Optional[subprocess.Popen] = None
        self.db_nodes: Optional[int] = None

    def __enter__(self) -> "ValidateOracle":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def start(self) -> None:
        env = dict(os.environ)
        # Node resolves the dist requires relative to N8N_MCP_DIR, so it must be
        # absolute regardless of the caller's cwd.
        env["N8N_MCP_DIR"] = os.path.abspath(self.n8n_mcp_dir)
        if self.node_db_path:
            env["NODE_DB_PATH"] = self.node_db_path
        self._proc = subprocess.Popen(
            ["node", self.script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # logger noise; verdicts come on stdout
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        # Block on the readiness handshake.
        ready = self._read_json_line()
        if not ready or not ready.get("ready"):
            raise RuntimeError(f"validate oracle failed to start: {ready}")
        self.db_nodes = ready.get("dbNodes")

    def _read_json_line(self) -> Optional[Dict[str, Any]]:
        assert self._proc and self._proc.stdout
        while True:
            line = self._proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # skip any stray non-JSON line

    def validate(self, workflow: Dict[str, Any], req_id: str = "x") -> Dict[str, Any]:
        assert self._proc and self._proc.stdin
        req = {"id": req_id, "workflow": workflow, "profile": self.profile}
        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()
        verdict = self._read_json_line()
        if verdict is None:
            raise RuntimeError("validate oracle closed unexpectedly")
        return verdict

    def close(self) -> None:
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self._proc.kill()
            self._proc = None


def verify_candidate(
    raw_text: str, whitelist: List[str], oracle: ValidateOracle, req_id: str = "x"
) -> Verdict:
    """Run one LLM completion through the full parse -> whitelist -> validate chain."""
    parsed, perr = parse_workflow(raw_text)
    if parsed is None:
        return Verdict(valid=False, stage_failed=STAGE_PARSE, errors=[perr or "parse failed"])

    ok, werr = check_whitelist(parsed, whitelist)
    if not ok:
        return Verdict(valid=False, stage_failed=STAGE_WHITELIST, errors=werr, parsed=parsed)

    verdict = oracle.validate(parsed, req_id=req_id)
    if verdict.get("valid"):
        return Verdict(
            valid=True,
            stage_failed=None,
            warning_count=verdict.get("warningCount", 0),
            parsed=parsed,
        )
    errs = [e.get("message", "") for e in verdict.get("errors", [])]
    if "error" in verdict:  # bridge-level failure
        errs = errs or [verdict["error"]]
    return Verdict(
        valid=False,
        stage_failed=STAGE_VALIDATE,
        errors=errs,
        error_count=verdict.get("errorCount", len(errs)),
        warning_count=verdict.get("warningCount", 0),
        parsed=parsed,
    )


if __name__ == "__main__":  # tiny self-test of the parse/whitelist stages
    sample = '```json\n{"name":"X","nodes":[{"type":"n8n-nodes-base.set"}],"connections":{}}\n```'
    p, e = parse_workflow(sample)
    print("parsed:", p, "err:", e, file=sys.stderr)
