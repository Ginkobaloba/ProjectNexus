"""
bench.eval.runner: drives a task across >=3 seeds and writes deterministic
per-seed JSON + a per-task summary with bootstrap 95% CI.

Output layout under bench/results/:
    <run_label>_<task_id>_seed<N>.json    one per (task, seed)
    <run_label>_<task_id>_summary.json    one per task (aggregate across seeds)

Card 5 reads the summary files to build baseline_v1.json.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__ as HARNESS_VERSION
from .base import (
    EvalTask,
    Problem,
    ProblemResult,
    SeedResult,
    TaskSummary,
    Sampling,
    write_json,
)
from .provider import LLMProvider, ProviderError
from .scoring import aggregate_seed_metrics, percentile


DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


class BenchRunner:
    """Run one task across multiple seeds, then aggregate.

    The runner does not know task internals beyond the EvalTask protocol; it
    only:
        1. asks the task for problems
        2. builds prompts
        3. calls the provider
        4. asks the task to score
        5. writes per-seed JSON
        6. aggregates and writes a summary JSON
    """

    def __init__(
        self,
        provider: LLMProvider,
        run_label: str,
        results_dir: Path | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        top_p: float = 1.0,
        n_bootstrap_resamples: int = 1000,
        git_sha: Optional[str] = None,
    ):
        self.provider = provider
        self.run_label = run_label
        self.results_dir = Path(results_dir or DEFAULT_RESULTS_DIR)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.n_bootstrap_resamples = n_bootstrap_resamples
        self._git_sha = git_sha or _detect_git_sha()

    # -----------------------------------------------------------------
    # Per-seed
    # -----------------------------------------------------------------

    def run_seed(self, task: EvalTask, seed: int) -> SeedResult:
        """Run `task` at one seed, write the per-seed JSON, return the dataclass."""
        sampling = Sampling(
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            seed=seed,
        )
        problems = list(task.load_problems())
        per_problem: List[ProblemResult] = []
        metric_sums: Dict[str, float] = {}
        latencies: List[float] = []
        total_completion_tokens = 0
        total_prompt_tokens = 0

        for problem in problems:
            prompt = task.build_prompt(problem)
            err = None
            completion_text = ""
            completion_tokens = 0
            prompt_tokens = 0
            latency_s = 0.0
            try:
                resp = self.provider.complete(prompt, sampling)
                completion_text = resp.text
                completion_tokens = resp.completion_tokens
                prompt_tokens = resp.prompt_tokens
                latency_s = resp.latency_s
            except ProviderError as e:
                err = str(e)
            metrics = task.score(problem, completion_text) if err is None else {}
            for k, v in metrics.items():
                metric_sums[k] = metric_sums.get(k, 0.0) + float(v)
            per_problem.append(
                ProblemResult(
                    problem_id=problem.problem_id,
                    metrics=metrics,
                    completion=completion_text,
                    completion_tokens=completion_tokens,
                    prompt_tokens=prompt_tokens,
                    latency_s=latency_s,
                    error=err,
                )
            )
            latencies.append(latency_s)
            total_completion_tokens += completion_tokens
            total_prompt_tokens += prompt_tokens

        n = max(1, len(problems))
        metrics_mean = {k: v / n for k, v in metric_sums.items()}

        # For stubs that emit only zeros and have only one synthetic problem,
        # we still want the headline primary_metric in the dict so the summary
        # aggregation has something to bootstrap.
        primary = getattr(task, "primary_metric", "score")
        if primary not in metrics_mean:
            metrics_mean[primary] = 0.0

        latencies_sorted = sorted(latencies)
        aggregate = {
            "primary_metric": primary,
            "primary_metric_value": metrics_mean[primary],
            "tokens_prompt_total": total_prompt_tokens,
            "tokens_completion_total": total_completion_tokens,
            "latency_p50_s": percentile(latencies_sorted, 0.50),
            "latency_p95_s": percentile(latencies_sorted, 0.95),
            "n_problems": len(problems),
        }

        result = SeedResult(
            run_label=self.run_label,
            task_id=task.task_id,
            seed=seed,
            timestamp_utc=_now_iso(),
            harness_version=HARNESS_VERSION,
            git_sha=self._git_sha,
            provider=self.provider.config,
            sampling=sampling,
            task_meta=task.task_meta(),
            metrics=metrics_mean,
            per_problem=per_problem,
            aggregate=aggregate,
            stub_placeholder=getattr(task, "stub_placeholder", False),
        )

        out_path = self.results_dir / f"{self.run_label}_{task.task_id}_seed{seed}.json"
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
    ) -> TaskSummary:
        """Run `task` for every seed, then write a summary with bootstrap CIs."""
        per_seed_results: List[SeedResult] = []
        for s in seeds:
            per_seed_results.append(self.run_seed(task, int(s)))

        per_seed_metrics = [r.metrics for r in per_seed_results]
        metric_names = sorted(
            {k for d in per_seed_metrics for k in d.keys()}
        )
        agg = aggregate_seed_metrics(
            per_seed_metrics=per_seed_metrics,
            metric_names=metric_names,
            n_resamples=self.n_bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )
        primary_metric = getattr(task, "primary_metric", "score")
        summary = TaskSummary(
            run_label=self.run_label,
            task_id=task.task_id,
            seeds=[int(s) for s in seeds],
            metrics=agg,
            primary_metric=primary_metric,
            stub_placeholder=getattr(task, "stub_placeholder", False),
            notes="stub task; metrics are placeholders" if getattr(task, "stub_placeholder", False) else "",
        )
        out_path = self.results_dir / f"{self.run_label}_{task.task_id}_summary.json"
        write_json(str(out_path), summary.to_json_dict())
        return summary

    # -----------------------------------------------------------------
    # Multi-task aggregation
    # -----------------------------------------------------------------

    def aggregate_overall(self, summaries: Sequence[TaskSummary]) -> Dict[str, Any]:
        """Write a top-level overall summary across all tasks in this run.

        For each task, records the primary metric mean and CI. Stub tasks are
        included with stub_placeholder=True so consumers can filter them.
        """
        overall: Dict[str, Any] = {
            "run_label": self.run_label,
            "harness_version": HARNESS_VERSION,
            "git_sha": self._git_sha,
            "tasks": {},
            "timestamp_utc": _now_iso(),
        }
        for s in summaries:
            primary = s.primary_metric
            primary_block = s.metrics.get(primary, {})
            overall["tasks"][s.task_id] = {
                "primary_metric": primary,
                "mean": primary_block.get("mean", 0.0),
                "ci95": primary_block.get("ci95", [0.0, 0.0]),
                "stub_placeholder": s.stub_placeholder,
            }
        out_path = self.results_dir / f"{self.run_label}_overall.json"
        write_json(str(out_path), overall)
        return overall



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _detect_git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"
