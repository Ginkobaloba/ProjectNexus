"""
n8n MCP `validate_workflow` oracle for Task 1 (Builder) exec-success scoring.

This module replaces the structural single-trigger reachability simulator at
`bench.eval.tasks.builder._structural_exec_sim` when the n8n MCP HTTP
Streamable server is reachable. If the MCP is offline, the caller is expected
to fall back to the structural sim and flag that explicitly in the result
metadata.

Contract (from Nexus_N8N-MCP/src/mcp/tools.ts validate_workflow):

    Input  { workflow: <n8n JSON>,
             options: { validateNodes, validateConnections,
                        validateExpressions, profile } }
    Output { valid: bool,
             summary: {...},
             errors: [...], warnings: [...], suggestions: [...] }

We always pass profile="runtime" for baseline runs. exec_success = 1.0 iff
the MCP response's `valid` field is True.

Transport (from Nexus_N8N-MCP/N8N_HTTP_STREAMABLE_SETUP.md):

    POST <base>/mcp
    Authorization: Bearer <token>  (optional in single-user dev)
    Content-Type: application/json
    Body: JSON-RPC 2.0 envelope with method="tools/call",
          params={ name: "validate_workflow", arguments: {...} }

Env vars:
    NEXUS_BENCH_N8N_MCP_URL       default http://localhost:3000
    NEXUS_BENCH_N8N_MCP_TOKEN     default "" (omit Authorization header if empty)
    NEXUS_BENCH_N8N_MCP_TIMEOUT   default 30.0 (seconds, per call)
    NEXUS_BENCH_N8N_MCP_PROBE_TIMEOUT  default 2.0 (seconds, probe only)

The probe is cheap (an unauthenticated POST that the server rejects fast). We
use the response code to distinguish reachable + speaking-MCP from offline.
Unit tests cover both branches end to end.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleConfig:
    """Snapshot of the n8n MCP target. Captured into bench task_meta so any
    later re-run can tell which MCP it actually talked to."""
    base_url: str
    token_present: bool
    timeout_s: float
    profile: str = "runtime"

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "token_present": self.token_present,
            "timeout_s": self.timeout_s,
            "profile": self.profile,
        }


def oracle_config_from_env() -> OracleConfig:
    return OracleConfig(
        base_url=os.environ.get("NEXUS_BENCH_N8N_MCP_URL", "http://localhost:3000").rstrip("/"),
        token_present=bool(os.environ.get("NEXUS_BENCH_N8N_MCP_TOKEN", "")),
        timeout_s=float(os.environ.get("NEXUS_BENCH_N8N_MCP_TIMEOUT", "30.0")),
        profile="runtime",
    )


def is_n8n_mcp_available(cfg: Optional[OracleConfig] = None) -> bool:
    """Cheap probe: POST a malformed envelope and expect any HTTP response.

    A reachable n8n MCP rejects bad JSON-RPC with 200 + error envelope or 400.
    Either is "speaking MCP". Connection-refused, DNS-fail, or socket timeout
    means offline.

    The probe is intentionally tolerant: we do not need a 200 to call the
    server reachable. The caller (BuilderTask.__init__) treats this boolean as
    the gate for the oracle path vs. the structural sim fallback.
    """
    cfg = cfg or oracle_config_from_env()
    probe_timeout = float(os.environ.get("NEXUS_BENCH_N8N_MCP_PROBE_TIMEOUT", "2.0"))
    body = b"{}"
    headers = {"Content-Type": "application/json"}
    if cfg.token_present:
        token = os.environ.get("NEXUS_BENCH_N8N_MCP_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{cfg.base_url}/mcp",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=probe_timeout) as resp:
            resp.read(64)
            return True
    except urllib.error.HTTPError:
        # Server answered with a non-2xx; that still means "reachable".
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def validate_workflow_via_mcp(
    workflow: Dict[str, Any],
    cfg: Optional[OracleConfig] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Call the n8n MCP `validate_workflow` tool. Returns (valid, raw_response).

    `raw_response` is the parsed MCP envelope when the call succeeded, or a
    {"error": ...} dict if the call failed (network or protocol). In the
    failure case we return (False, ...) so the metric is conservative.
    """
    cfg = cfg or oracle_config_from_env()
    envelope = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "validate_workflow",
            "arguments": {
                "workflow": workflow,
                "options": {
                    "validateNodes": True,
                    "validateConnections": True,
                    "validateExpressions": True,
                    "profile": cfg.profile,
                },
            },
        },
    }
    headers = {"Content-Type": "application/json"}
    if cfg.token_present:
        token = os.environ.get("NEXUS_BENCH_N8N_MCP_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{cfg.base_url}/mcp",
        data=json.dumps(envelope).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, {"error": f"http_{e.code}", "body": body}
    except urllib.error.URLError as e:
        return False, {"error": "url_error", "detail": str(e)}
    except (TimeoutError, OSError) as e:
        return False, {"error": "transport", "detail": str(e)}
    except json.JSONDecodeError as e:
        return False, {"error": "decode", "detail": str(e)}

    # Extract the tool result. MCP tools/call returns either:
    #   { jsonrpc, id, result: { content: [...], structuredContent: {...} } }
    # depending on the server version. We accept both shapes and look for the
    # `valid` boolean on whichever shape carries it.
    result = data.get("result", data)
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    if isinstance(structured, dict) and "valid" in structured:
        return bool(structured["valid"]), data

    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                txt = item.get("text", "")
                try:
                    parsed = json.loads(txt)
                    if isinstance(parsed, dict) and "valid" in parsed:
                        return bool(parsed["valid"]), data
                except json.JSONDecodeError:
                    continue

    # Last-ditch: tolerate servers that return {valid: ...} at the top level.
    if isinstance(result, dict) and "valid" in result:
        return bool(result["valid"]), data

    return False, {"error": "malformed_response", "raw": data}
