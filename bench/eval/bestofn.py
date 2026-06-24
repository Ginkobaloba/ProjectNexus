"""
bench.eval.bestofn: verifier-guided best-of-N sampling on top of the existing
bench harness.

Sprint 3d Card 6 implementation. Per NEXUS_PATH_TO_OUTPERFORM_v0.1.md section 3
(Track C MVE):

    sample N=8 candidate completions at temp=0.8, run each through the task's
    free programmatic verifier (the existing `EvalTask.score()` method), and
    pick the first candidate whose primary metric == 1.0, else the candidate
    with the highest primary metric.

Design constraints:
    1. The verifier is the task's own `score()` method. There is no separate
       verifier code path for best-of-N. This eliminates a whole class of
       "the best-of-N verifier scored differently than the baseline verifier"
       bugs by construction.
    2. The runner can drive any EvalTask (builder, code_pub, future task
       families) without per-task wiring. The selection key is whatever the
       task names as `primary_metric`.
    3. Both arms (baseline greedy and best-of-N) can run in a single
       invocation so the comparison artifact is self-contained. No dependency
       on a baseline_v1.json being on disk; the comparison is between the two
       arms of this run.
    4. The per-seed JSON records every candidate's full score block plus which
       candidate was picked and why ("oracle_pass" or "highest_score"). The
       full per-candidate completion text is recorded so audit-trail re-runs
       are possible without re-sampling the model.

Result file layout under `results_dir/`:
    <run_label>_<task_id>_bestofn_seed<seed>.json    per seed, per task
    <run_label>_<task_id>_bestofn_summary.json       per task, aggregated
    <run_label>_<task_id>_comparison.json            baseline vs best-of-N
    <run_label>_<task_id>_comparison.svg             two-bar chart

The chart is the headline; the JSONs are the audit trail.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__ as HARNESS_VERSION
from .base import (
    EvalTask,
    Problem,
    ProblemResult,
    ProviderConfig,
    Sampling,
    SeedResult,
    TaskSummary,
    write_json,
)
from .provider import LLMProvider, ProviderError
from .runner import BenchRunner, DEFAULT_RESULTS_DIR, _now_iso, _detect_git_sha
from .scoring import aggregate_seed_metrics, bootstrap_ci, mean, percentile


# Default best-of-N parameters per sprint plan section 5.
DEFAULT_BESTOFN_N = 8
DEFAULT_BESTOFN_TEMPERATURE = 0.8
DEFAULT_BESTOFN_TOP_P = 0.95

# Selection mode tags written into the per-seed JSON.
PICKED_ORACLE_PASS = "oracle_pass"
PICKED_HIGHEST_SCORE = "highest_score"
PICKED_NO_VALID = "no_valid_candidate"


@dataclass
class CandidateResult:
    """One of N candidates for one problem at one seed.

    Carries the candidate completion text and the full per-candidate metrics so
    a future agent can re-score with a new oracle without re-sampling.
    """
    candidate_idx: int
    completion: str
    metrics: Dict[str, float]
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    error: Optional[str] = None


@dataclass
class BestOfNProblemResult:
    """Per-problem outcome of a best-of-N run.

    `picked_idx` is the index into `candidates` that the selector chose, or -1
    when every candidate errored. `picked_reason` is one of PICKED_*. The
    `primary_metric_value` field is the selected candidate's primary metric
    score and is what aggregates into the seed-level mean.
    """
    problem_id: str
    candidates: List[CandidateResult]
    picked_idx: int
    picked_reason: str
    primary_metric_value: float
    primary_metric_name: str
    selected_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class BestOfNSeedResult:
    """One seed of a best-of-N run on one task. Written to disk as
    <run_label>_<task_id>_bestofn_seed<seed>.json."""
    run_label: str
    task_id: str
    seed: int
    timestamp_utc: str
    harness_version: str
    git_sha: str
    provider: ProviderConfig
    sampling: Sampling
    n_candidates: int
    task_meta: Dict[str, Any]
    primary_metric: str
    per_problem: List[BestOfNProblemResult]
    aggregate: Dict[str, Any]

    def to_json_dict(self) -> Dict[str, Any]:
        from .base import _to_json_dict

        return _to_json_dict(self)


@dataclass
class BestOfNSummary:
    """Aggregate across seeds for one task in the best-of-N arm. Written as
    <run_label>_<task_id>_bestofn_summary.json."""
    run_label: str
    task_id: str
    seeds: List[int]
    primary_metric: str
    n_candidates: int
    metrics: Dict[str, Dict[str, Any]]
    selection_stats: Dict[str, Any]
    cost: Dict[str, Any]

    def to_json_dict(self) -> Dict[str, Any]:
        from .base import _to_json_dict

        return _to_json_dict(self)


class BestOfNRunner:
    """Verifier-guided best-of-N runner.

    Per problem, samples `n_candidates` completions at the configured
    temperature/top_p, scores each via `task.score()`, and selects via:

        1. If any candidate's primary metric == 1.0, pick the lowest-index
           passing one. This matches the Track C spec ("return the first that
           passes").
        2. Otherwise, pick the candidate with the highest primary metric. Ties
           broken by lowest candidate index.
        3. If every candidate errored, pick nothing (picked_idx = -1); the
           problem contributes 0.0 to the seed-level mean.

    The seed values fed to the provider for the N candidates are derived from
    the per-seed base seed: base_seed * N + candidate_idx. That keeps every
    candidate deterministic and seed-distinct, and re-running with the same
    base seed reproduces the run byte-for-byte (assuming vLLM determinism).
    """

    def __init__(
        self,
        provider: LLMProvider,
        run_label: str,
        results_dir: Path | None = None,
        n_candidates: int = DEFAULT_BESTOFN_N,
        temperature: float = DEFAULT_BESTOFN_TEMPERATURE,
        top_p: float = DEFAULT_BESTOFN_TOP_P,
        max_tokens: int = 2048,
        n_bootstrap_resamples: int = 1000,
        git_sha: Optional[str] = None,
    ):
        if n_candidates < 1:
            raise ValueError("n_candidates must be >= 1")
        self.provider = provider
        self.run_label = run_label
        self.results_dir = Path(results_dir or DEFAULT_RESULTS_DIR)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.n_candidates = int(n_candidates)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.max_tokens = int(max_tokens)
        self.n_bootstrap_resamples = int(n_bootstrap_resamples)
        self._git_sha = git_sha or _detect_git_sha()

    # -----------------------------------------------------------------
    # Per-seed
    # -----------------------------------------------------------------

    def run_seed(self, task: EvalTask, seed: int) -> BestOfNSeedResult:
        primary = getattr(task, "primary_metric", "score")
        problems = list(task.load_problems())
        per_problem: List[BestOfNProblemResult] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        all_latencies: List[float] = []
        picked_reason_counts: Dict[str, int] = {
            PICKED_ORACLE_PASS: 0,
            PICKED_HIGHEST_SCORE: 0,
            PICKED_NO_VALID: 0,
        }

        for problem in problems:
            prompt = task.build_prompt(problem)
            candidates: List[CandidateResult] = []
            for k in range(self.n_candidates):
                cand_seed = seed * self.n_candidates + k
                sampling = Sampling(
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_tokens,
                    seed=cand_seed,
                )
                completion = ""
                err: Optional[str] = None
                ptok = 0
                ctok = 0
                latency = 0.0
                try:
                    resp = self.provider.complete(prompt, sampling)
                    completion = resp.text
                    ptok = resp.prompt_tokens
                    ctok = resp.completion_tokens
                    latency = resp.latency_s
                except ProviderError as e:
                    err = str(e)
                metrics = (
                    task.score(problem, completion) if err is None else {}
                )
                candidates.append(
                    CandidateResult(
                        candidate_idx=k,
                        completion=completion,
                        metrics=metrics,
                        prompt_tokens=ptok,
                        completion_tokens=ctok,
                        latency_s=latency,
                        error=err,
                    )
                )
                total_prompt_tokens += ptok
                total_completion_tokens += ctok
                all_latencies.append(latency)

            picked_idx, picked_reason, picked_value = _select_candidate(
                candidates, primary
            )
            picked_reason_counts[picked_reason] = (
                picked_reason_counts.get(picked_reason, 0) + 1
            )
            selected_metrics = (
                dict(candidates[picked_idx].metrics)
                if picked_idx >= 0
                else {primary: 0.0}
            )
            per_problem.append(
                BestOfNProblemResult(
                    problem_id=problem.problem_id,
                    candidates=candidates,
                    picked_idx=picked_idx,
                    picked_reason=picked_reason,
                    primary_metric_value=picked_value,
                    primary_metric_name=primary,
                    selected_metrics=selected_metrics,
                )
            )

        # Per-seed aggregate metrics: mean over problems of the selected
        # candidate's metric values. We compute a per-metric mean across all
        # metric names emitted by the task.
        metric_names: List[str] = sorted(
            {
                k
                for pp in per_problem
                for k in pp.selected_metrics.keys()
            }
        )
        if primary not in metric_names:
            metric_names.append(primary)
        seed_metrics: Dict[str, float] = {}
        n = max(1, len(per_problem))
        for name in metric_names:
            seed_metrics[name] = (
                sum(float(pp.selected_metrics.get(name, 0.0)) for pp in per_problem)
                / n
            )

        latencies_sorted = sorted(all_latencies)
        aggregate = {
            "primary_metric": primary,
            "primary_metric_value": seed_metrics.get(primary, 0.0),
            "metrics": seed_metrics,
            "n_problems": len(problems),
            "n_candidates_total": len(problems) * self.n_candidates,
            "tokens_prompt_total": total_prompt_tokens,
            "tokens_completion_total": total_completion_tokens,
            "latency_p50_s": percentile(latencies_sorted, 0.50),
            "latency_p95_s": percentile(latencies_sorted, 0.95),
            "picked_reason_counts": picked_reason_counts,
        }

        sampling = Sampling(
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            seed=seed,
        )
        result = BestOfNSeedResult(
            run_label=self.run_label,
            task_id=task.task_id,
            seed=seed,
            timestamp_utc=_now_iso(),
            harness_version=HARNESS_VERSION,
            git_sha=self._git_sha,
            provider=self.provider.config,
            sampling=sampling,
            n_candidates=self.n_candidates,
            task_meta=task.task_meta(),
            primary_metric=primary,
            per_problem=per_problem,
            aggregate=aggregate,
        )

        out_path = (
            self.results_dir
            / f"{self.run_label}_{task.task_id}_bestofn_seed{seed}.json"
        )
        write_json(str(out_path), result.to_json_dict())
        return result

    # -----------------------------------------------------------------
    # Aggregation across seeds
    # -----------------------------------------------------------------

    def run_task(
        self,
        task: EvalTask,
        seeds: Sequence[int],
        bootstrap_seed: int = 0,
    ) -> BestOfNSummary:
        per_seed: List[BestOfNSeedResult] = [
            self.run_seed(task, int(s)) for s in seeds
        ]
        primary = getattr(task, "primary_metric", "score")
        # Pull every emitted metric name from every seed so the summary covers
        # secondary metrics too.
        metric_names = sorted(
            {
                k
                for r in per_seed
                for k in r.aggregate["metrics"].keys()
            }
        )
        per_seed_metric_dicts = [r.aggregate["metrics"] for r in per_seed]
        agg = aggregate_seed_metrics(
            per_seed_metrics=per_seed_metric_dicts,
            metric_names=metric_names,
            n_resamples=self.n_bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )

        # Selection-mode aggregation: sum across seeds, then ratios.
        sel_totals: Dict[str, int] = {
            PICKED_ORACLE_PASS: 0,
            PICKED_HIGHEST_SCORE: 0,
            PICKED_NO_VALID: 0,
        }
        for r in per_seed:
            for k, v in r.aggregate["picked_reason_counts"].items():
                sel_totals[k] = sel_totals.get(k, 0) + int(v)
        total_picks = sum(sel_totals.values()) or 1
        selection_stats = {
            "totals": sel_totals,
            "fractions": {k: v / total_picks for k, v in sel_totals.items()},
        }

        # Cost: aggregate token totals and latency percentiles across seeds.
        tokens_prompt = sum(r.aggregate["tokens_prompt_total"] for r in per_seed)
        tokens_completion = sum(
            r.aggregate["tokens_completion_total"] for r in per_seed
        )
        all_lat = [r.aggregate["latency_p50_s"] for r in per_seed]
        all_lat_p95 = [r.aggregate["latency_p95_s"] for r in per_seed]
        cost = {
            "tokens_prompt_total": tokens_prompt,
            "tokens_completion_total": tokens_completion,
            "latency_p50_s_mean": mean(all_lat),
            "latency_p95_s_mean": mean(all_lat_p95),
            "n_candidates_per_problem": self.n_candidates,
        }

        summary = BestOfNSummary(
            run_label=self.run_label,
            task_id=task.task_id,
            seeds=[int(s) for s in seeds],
            primary_metric=primary,
            n_candidates=self.n_candidates,
            metrics=agg,
            selection_stats=selection_stats,
            cost=cost,
        )
        out_path = (
            self.results_dir
            / f"{self.run_label}_{task.task_id}_bestofn_summary.json"
        )
        write_json(str(out_path), summary.to_json_dict())
        return summary


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _select_candidate(
    candidates: Sequence[CandidateResult],
    primary_metric: str,
) -> Tuple[int, str, float]:
    """Apply the Track C selection rule. Returns (picked_idx, reason, value).

    Rule (sprint plan section 4):
        1. Lowest-index candidate whose primary metric == 1.0 wins.
        2. Else highest primary metric value, tie-broken by lowest index.
        3. Else (every candidate errored), picked_idx = -1, value = 0.0.

    `primary_metric == 1.0` is the right pass test because every wired task's
    primary metric (`valid_at_1`, `pass_at_1`) is 0/1 per problem. A future
    non-binary primary metric would need a different pass threshold; the
    selector would need a small policy change.
    """
    if not candidates:
        return -1, PICKED_NO_VALID, 0.0

    # Pass 1: oracle pass (primary metric == 1.0).
    for c in candidates:
        if c.error is not None:
            continue
        val = float(c.metrics.get(primary_metric, 0.0))
        if val >= 1.0:
            return c.candidate_idx, PICKED_ORACLE_PASS, val

    # Pass 2: highest primary metric.
    best_idx = -1
    best_val = -1.0
    for c in candidates:
        if c.error is not None:
            continue
        val = float(c.metrics.get(primary_metric, 0.0))
        if val > best_val:
            best_val = val
            best_idx = c.candidate_idx

    if best_idx >= 0:
        return best_idx, PICKED_HIGHEST_SCORE, max(0.0, best_val)

    return -1, PICKED_NO_VALID, 0.0
