# bench/eval/run_builder_eval.py
"""
Track C MVE runner: verifier-guided best-of-N on the held-out Builder set.

This is the experiment NEXUS_PATH_TO_OUTPERFORM_v0.1.md section 3 calls the
headline Track C result: take the *unchanged* base model and measure how far a
free programmatic verifier pushes Builder valid@1 when you sample N candidates and
keep the first that validates.

It reports three numbers per the program's eval discipline (bootstrap 95% CIs on
every score, resampling over the 50 specs):

  * valid@1 (greedy)   -- temperature 0, one shot. THE baseline bar.
  * valid@1 (sampled)  -- expected pass rate of a single temp=0.8 draw (so the
                          best-of-N lift is not conflated with greedy-vs-sampled).
  * valid@N (best-of-N) -- a spec counts as solved if ANY of N samples validates.
                          This equals verifier-picked best-of-N for a pass/fail
                          oracle, and is the Track-C-raised bar Tracks A/B must beat.

It also records the cost axis (tokens, latency, the inference multiplier best-of-N
buys) and a per-stage failure breakdown (parse / whitelist / n8n-validate), and
commits the bar to baseline_v1.json.

Usage:
    python -m bench.eval.run_builder_eval [--n 8] [--limit N] [--profile runtime]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from bench.eval.builder_prompt import PROMPT_VERSION, build_messages
from bench.eval.cortex_client import CortexClient, CortexError
from bench.eval.verifier import (
    STAGE_PARSE,
    STAGE_VALIDATE,
    STAGE_WHITELIST,
    ValidateOracle,
    verify_candidate,
)
from bench.stats import bootstrap_ci, summarize

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", _REPO_ROOT, "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _n8n_mcp_version(mcp_dir: str) -> str:
    try:
        with open(os.path.join(mcp_dir, "package.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("version", "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _ci(values: List[float]) -> Dict[str, Any]:
    mean, lo, hi = bootstrap_ci(values)
    return {"mean": mean, "ci95": [lo, hi], "n": len(values)}


def _norm_error(msg: str) -> str:
    """Normalize a validator error so the histogram groups the same failure class:
    strip quoted specifics and numbers (node names, ids, versions, indices)."""
    norm = re.sub(r'"[^"]*"', '"X"', msg or "")
    norm = re.sub(r"\d+", "N", norm)
    return norm.strip()[:100]


def _dump_yaml(obj: Any, indent: int = 0) -> str:
    """Tiny YAML emitter for the nested dict of scalars / lists we write to
    runs.yaml. Avoids a PyYAML dependency (the bench package is stdlib-only)."""
    pad = "  " * indent
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_dump_yaml(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_dump_yaml(v, indent + 1))
            else:
                lines.append(f"{pad}- {_scalar(v)}")
    return "\n".join(lines)


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return v if v and all(c not in v for c in ":#") else json.dumps(v)
    return str(v)


def run(args: argparse.Namespace) -> Dict[str, Any]:
    specs = _load_jsonl(args.dataset)
    if args.limit:
        specs = specs[: args.limit]
    with open(args.registry, "r", encoding="utf-8") as f:
        whitelist = json.load(f).get("nodeWhitelist", [])

    client = CortexClient(base_url=args.url, model=args.model, timeout=args.timeout)
    model_meta = client.model_meta()
    vllm_version = client.server_version()
    print(f"cortex   : {client.model}  (max_model_len={model_meta.get('max_model_len')})")
    print(f"vllm     : {vllm_version}")
    print(f"specs    : {len(specs)}  |  N={args.n}  |  profile={args.profile}")
    print()

    per_spec: List[Dict[str, Any]] = []
    greedy_calls: List[Dict[str, float]] = []
    sampled_calls: List[Dict[str, float]] = []
    error_hist: Counter = Counter()  # normalized failure classes across all candidates

    with ValidateOracle(
        n8n_mcp_dir=args.n8n_mcp_dir, profile=args.profile, node_db_path=args.node_db
    ) as oracle:
        print(f"oracle   : n8n-mcp validate_workflow, {oracle.db_nodes} nodes loaded")
        print()
        for i, spec in enumerate(specs):
            messages = build_messages(spec, whitelist, prompt_variant=args.prompt_variant)

            # Baseline: greedy single shot.
            g = client.chat(messages, temperature=args.baseline_temp, n=1, seed=args.seed,
                            max_tokens=args.max_tokens)
            gv = verify_candidate(g.texts[0], whitelist, oracle, req_id=f"{spec['id']}#g")
            greedy_calls.append({"latency_ms": g.latency_ms, "prompt": g.prompt_tokens,
                                 "completion": g.completion_tokens})
            for e in gv.errors:
                error_hist[_norm_error(e)] += 1

            # Best-of-N: N stochastic samples in one batched request.
            s = client.chat(messages, temperature=args.sample_temp, top_p=args.top_p,
                            n=args.n, seed=args.seed, max_tokens=args.max_tokens)
            sample_verdicts = [
                verify_candidate(s.texts[k], whitelist, oracle, req_id=f"{spec['id']}#{k}")
                for k in range(len(s.texts))
            ]
            sampled_calls.append({"latency_ms": s.latency_ms, "prompt": s.prompt_tokens,
                                  "completion": s.completion_tokens})
            for v in sample_verdicts:
                for e in v.errors:
                    error_hist[_norm_error(e)] += 1

            sample_pass = [v.valid for v in sample_verdicts]
            rec = {
                "id": spec["id"],
                "domain": spec["domain"],
                "source": spec["source"],
                "greedy_pass": gv.valid,
                "greedy_stage": gv.stage_failed or "pass",
                "sample_pass": sample_pass,
                "sample_stages": [v.stage_failed or "pass" for v in sample_verdicts],
                "any_pass": any(sample_pass),
                "first_pass_index": next((k for k, p in enumerate(sample_pass) if p), None),
            }
            per_spec.append(rec)
            mark = "ok " if gv.valid else f"x:{gv.stage_failed}"
            print(f"[{i + 1:>2}/{len(specs)}] {spec['id']:<28} greedy={mark:<14} "
                  f"best{args.n}={'pass' if rec['any_pass'] else 'FAIL'} "
                  f"({sum(sample_pass)}/{len(sample_pass)})")

    # ---- aggregate ---------------------------------------------------------
    n = len(per_spec)
    greedy_vals = [1.0 if r["greedy_pass"] else 0.0 for r in per_spec]
    sampled_per_draw = [sum(r["sample_pass"]) / len(r["sample_pass"]) for r in per_spec]
    best_of_n_vals = [1.0 if r["any_pass"] else 0.0 for r in per_spec]

    best_of_k = {}
    for k in range(1, args.n + 1):
        vals = [1.0 if any(r["sample_pass"][:k]) else 0.0 for r in per_spec]
        best_of_k[str(k)] = round(sum(vals) / n, 4)

    def _stage_counts(stage_lists: List[str]) -> Dict[str, int]:
        from collections import Counter

        c = Counter(stage_lists)
        return {s: c.get(s, 0) for s in (STAGE_PARSE, STAGE_WHITELIST, STAGE_VALIDATE, "pass")}

    greedy_stage_counts = _stage_counts([r["greedy_stage"] for r in per_spec])
    sampled_stage_counts = _stage_counts(
        [st for r in per_spec for st in r["sample_stages"]]
    )

    g_comp = sum(c["completion"] for c in greedy_calls)
    s_comp = sum(c["completion"] for c in sampled_calls)
    results = {
        "valid@1_greedy": _ci(greedy_vals),
        "valid@1_sampled": _ci(sampled_per_draw),
        f"valid@{args.n}_best_of_{args.n}": _ci(best_of_n_vals),
        "best_of_k": best_of_k,
        "stage_failures": {
            "greedy": greedy_stage_counts,
            "sampled_all_draws": sampled_stage_counts,
        },
        "validate_error_histogram": dict(error_hist.most_common(20)),
        "cost": {
            "greedy_completion_tokens": g_comp,
            "best_of_n_completion_tokens": s_comp,
            "inference_multiplier": round(s_comp / g_comp, 2) if g_comp else None,
            "greedy_latency_ms": summarize([c["latency_ms"] for c in greedy_calls]),
            "best_of_n_latency_ms": summarize([c["latency_ms"] for c in sampled_calls]),
        },
    }

    n_reg = sum(1 for s in specs if s["source"] == "registry")
    config = {
        "task_family": "1-builder-workflow-synthesis",
        "experiment": "track-c-verifier-guided-best-of-n",
        "metric": "valid@k = parse -> node-whitelist -> n8n validate_workflow, all pass",
        "dataset": {
            "path": os.path.relpath(args.dataset, _REPO_ROOT).replace("\\", "/"),
            "n": len(specs),
            "sha256": _sha256_file(args.dataset),
            "registry": n_reg,
            "synthesized": len(specs) - n_reg,
        },
        "model": {
            "id": client.model,
            "quant": "AWQ-4bit compressed-tensors",
            "max_model_len": model_meta.get("max_model_len"),
            "endpoint": args.url,
        },
        "sampling": {
            "prompt_version": PROMPT_VERSION,
            "prompt_variant": args.prompt_variant,
            "baseline_temperature": args.baseline_temp,
            "sample_temperature": args.sample_temp,
            "top_p": args.top_p,
            "n": args.n,
            "seed": args.seed,
            "max_tokens": args.max_tokens,
        },
        "verifier": {
            "oracle": "n8n-mcp validate_workflow",
            "profile": args.profile,
            "db_nodes": oracle.db_nodes,
            "n8n_mcp_version": _n8n_mcp_version(args.n8n_mcp_dir),
        },
        "harness": {
            "git_sha": _git_sha(),
            "vllm_version": vllm_version,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "hardware": {"role": "Cortex", "gpu": "RTX 4090 24GB", "host": "DREWSPC"},
    }

    return {"config": config, "results": results, "per_spec": per_spec}


def main() -> int:
    ap = argparse.ArgumentParser(description="Track C verifier-guided best-of-N Builder eval")
    ap.add_argument("--dataset", default=os.path.join(_HERE, "datasets", "builder_heldout_v1.jsonl"))
    ap.add_argument("--registry", default=os.path.join(_REPO_ROOT, "automation", "workflow-registry.json"))
    ap.add_argument("--n8n-mcp-dir", default=os.path.join(_REPO_ROOT, "Nexus_N8N-MCP"))
    ap.add_argument("--node-db", default=None, help="override path to nodes.db")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--model", default=None, help="None = auto-detect from /v1/models")
    ap.add_argument("--n", type=int, default=8, help="best-of-N sample count")
    ap.add_argument("--baseline-temp", type=float, default=0.0)
    ap.add_argument("--sample-temp", type=float, default=0.8)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--profile", default="runtime", choices=["minimal", "runtime", "ai-friendly", "strict"])
    ap.add_argument("--prompt-variant", default="faithful", choices=["faithful", "augmented"],
                    help="faithful = frozen production Builder prompt; augmented = + gap-closing rules")
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--limit", type=int, default=0, help="cap specs (smoke test); 0 = all")
    ap.add_argument("--out-dir", default=os.path.join(_HERE, "results"))
    ap.add_argument("--baseline-out", default=os.path.join(_HERE, "baseline_v1.json"),
                    help="write the committed bar here; '' to skip")
    args = ap.parse_args()

    try:
        report = run(args)
    except CortexError as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    results_path = os.path.join(args.out_dir, "builder_best_of_n_results.json")
    with open(results_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
    runs_yaml_path = os.path.join(args.out_dir, "runs.yaml")
    with open(runs_yaml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_dump_yaml({"config": report["config"], "results": report["results"]}) + "\n")

    r = report["results"]
    nkey = f"valid@{args.n}_best_of_{args.n}"
    summary = {
        "baseline_version": "v1",
        **report["config"],
        "results": {
            "valid@1_greedy": r["valid@1_greedy"],
            "valid@1_sampled": r["valid@1_sampled"],
            nkey: r[nkey],
            "best_of_k": r["best_of_k"],
            "stage_failures": r["stage_failures"],
            "validate_error_histogram": r["validate_error_histogram"],
            "cost": r["cost"],
        },
    }
    if args.baseline_out:
        with open(args.baseline_out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, indent=2)

    print()
    print("=" * 64)
    g = r["valid@1_greedy"]; sp = r["valid@1_sampled"]; bo = r[nkey]
    print(f"valid@1 (greedy, baseline) : {g['mean']:.3f}  CI95 {g['ci95']}")
    print(f"valid@1 (sampled, t=0.8)   : {sp['mean']:.3f}  CI95 {sp['ci95']}")
    print(f"valid@{args.n} (best-of-{args.n})        : {bo['mean']:.3f}  CI95 {bo['ci95']}")
    lift = bo["mean"] - g["mean"]
    print(f"lift (best-of-{args.n} - greedy) : {lift:+.3f}  "
          f"({'CIs disjoint' if bo['ci95'][0] > g['ci95'][1] else 'CIs OVERLAP'})")
    print(f"inference multiplier       : {r['cost']['inference_multiplier']}x completion tokens")
    print("=" * 64)
    print(f"\nwrote: {results_path}\n       {runs_yaml_path}")
    if args.baseline_out:
        print(f"       {args.baseline_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
