"""Aggregate per-task summaries into bench/baselines/baseline_v1.json.

Card 5 deliverable. Reads `bench/results/baseline_v1_*_summary.json` files
and writes a single headline JSON with per-task per-seed scores, bootstrap
95% CIs, and the run-level metadata (provider, oracle path, dataset size
caveats). Stub tasks are included with `stub_placeholder=True` so consumers
can filter them.

Run from the repo root:
    python -m bench.baselines.build_baseline_v1
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "bench" / "results"
BASELINES_DIR = REPO_ROOT / "bench" / "baselines"
OUT_PATH = BASELINES_DIR / "baseline_v1.json"

TASK_IDS = ["builder", "code_pub", "routing", "tool_use", "rag_qa", "guards"]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
            cwd=REPO_ROOT,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def _now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _read_summary(task_id: str) -> Dict[str, Any]:
    path = RESULTS_DIR / f"baseline_v1_{task_id}_summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_seed_meta(task_id: str, seed: int) -> Dict[str, Any]:
    path = RESULTS_DIR / f"baseline_v1_{task_id}_seed{seed}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> Dict[str, Any]:
    tasks: Dict[str, Any] = {}
    provider_snapshot = None
    sampling_snapshot = None
    builder_oracle = None
    for tid in TASK_IDS:
        summary = _read_summary(tid)
        seed0 = _read_seed_meta(tid, 0)
        provider = seed0.get("provider")
        sampling = seed0.get("sampling")
        task_meta = seed0.get("task_meta", {})
        if provider_snapshot is None and provider is not None and not summary["stub_placeholder"]:
            provider_snapshot = provider
        if sampling_snapshot is None and sampling is not None and not summary["stub_placeholder"]:
            sampling_snapshot = sampling
        if tid == "builder":
            builder_oracle = task_meta.get("oracle")
        tasks[tid] = {
            "primary_metric": summary["primary_metric"],
            "stub_placeholder": summary["stub_placeholder"],
            "seeds": summary["seeds"],
            "metrics": summary["metrics"],
            "n_problems": task_meta.get("n_problems"),
            "dataset_id": task_meta.get("dataset_id"),
            "dataset_path": task_meta.get("dataset_path"),
        }
        if tid == "builder":
            tasks[tid]["oracle"] = builder_oracle
            tasks[tid]["dataset_caveat"] = task_meta.get("dataset_caveat", "")

    headline = {
        "label": "baseline_v1",
        "harness_version": "0.1.0",
        "git_sha": _git_sha(),
        "timestamp_utc": _now(),
        "pre_registration": "bench/baselines/pre_registration_v1.md",
        "host": "DREWSPC (4090 cortex)",
        "provider": provider_snapshot,
        "sampling": sampling_snapshot,
        "tolerances": {
            "builder_valid_at_1_win_pp": 10.0,
            "family_6_tolerance_abs_points": 3.0,
            "non_overlapping_ci_required_over_seeds": 3,
        },
        "caveats": {
            "dataset_size": (
                "Builder ran on the 5-example placeholder dataset shipped in PR #7. "
                "Statistically thin; bootstrap CIs over 3 seeds will be degenerate when "
                "the model is deterministic. Expanding to 50 examples is the n+1 follow-on."
            ),
            "oracle": (
                "Builder exec_success scored via structural single-trigger reachability "
                "simulator, not the n8n MCP validate_workflow oracle, because the n8n MCP "
                "container was offline on DREWSPC at run time. The MCP code path is wired, "
                "unit-tested, and selectable via NEXUS_BENCH_BUILDER_ORACLE=mcp."
            ),
            "deterministic_variance": (
                "Temperature 0.0 + seeded vLLM gives identical per-seed completions on this "
                "model. Per-seed metric values are identical across seeds, so the bootstrap "
                "95% CI collapses to a point. Wider CIs require either a larger held-out "
                "set, nonzero temperature, or both."
            ),
        },
        "tasks": tasks,
    }
    return headline


def main() -> int:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    headline = build()
    OUT_PATH.write_text(json.dumps(headline, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    # Print the headline in plain terms.
    for tid, block in headline["tasks"].items():
        if block["stub_placeholder"]:
            print(f"  {tid:10s}  STUB_PLACEHOLDER (not measured)")
            continue
        pm = block["primary_metric"]
        m = block["metrics"].get(pm, {})
        ci = m.get("ci95", [0.0, 0.0])
        print(
            f"  {tid:10s}  {pm}: mean={m.get('mean', 0.0):.4f}  ci95=[{ci[0]:.4f}, {ci[1]:.4f}]"
            f"  n={block['n_problems']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
