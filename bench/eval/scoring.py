"""
bench.eval.scoring: bootstrap CI + aggregation helpers.

Bootstrap 95% CI over per-seed scalars is the headline statistic for every
task. See NEXUS_PATH_TO_OUTPERFORM section 1.2 for the rationale.

Math is intentionally vanilla Python (no scipy) so the harness runs anywhere
the cortex client runs. Numerics are exercised by tests/test_eval_scoring.py.
"""
from __future__ import annotations

import random
from typing import List, Sequence, Tuple


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile. p in [0, 1]. sorted_vals must already
    be sorted ascending. Mirrors bench/stats.py.percentile so the dashboard
    and the eval bench report numbers the same way."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    if p <= 0.0:
        return float(sorted_vals[0])
    if p >= 1.0:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo]) * (1.0 - frac) + float(sorted_vals[hi]) * frac


def bootstrap_ci(
    values: Sequence[float],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Tuple[float, float]:
    """Bootstrap CI on the sample mean of `values`.

    Returns (lo, hi). For len(values) <= 1, returns the degenerate interval
    (values[0], values[0]) or (0.0, 0.0). The seed is recorded into the result
    so re-running with the same seed reproduces the interval byte-for-byte.

    Math: resample with replacement n_resamples times, take the mean of each
    resample, return the (1-confidence)/2 and 1-(1-confidence)/2 quantiles of
    the resample-mean distribution.

    n_resamples=1000 is the default per the sprint plan section 5; bench runs
    may override for tighter intervals at the cost of runtime.
    """
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        v = float(values[0])
        return (v, v)
    rng = random.Random(seed)
    n = len(values)
    means: List[float] = []
    vals = [float(v) for v in values]
    for _ in range(n_resamples):
        # Sample with replacement.
        s = 0.0
        for _ in range(n):
            s += vals[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = percentile(means, alpha)
    hi = percentile(means, 1.0 - alpha)
    return (lo, hi)


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def aggregate_seed_metrics(
    per_seed_metrics: List[dict],
    metric_names: Sequence[str],
    n_resamples: int = 1000,
    bootstrap_seed: int = 0,
) -> dict:
    """Build the `TaskSummary.metrics` map from a list of per-seed metric dicts.

    `per_seed_metrics[i]` is the `SeedResult.metrics` dict for seed i.
    `metric_names` is the list of metric keys to summarize (e.g.
    ["valid_at_1", "exec_success"]).

    Returns a dict shaped:
        {metric_name: {"per_seed": [...], "mean": float, "ci95": [lo, hi]}}
    """
    out: dict = {}
    for name in metric_names:
        per_seed = [float(d.get(name, 0.0)) for d in per_seed_metrics]
        lo, hi = bootstrap_ci(
            per_seed, n_resamples=n_resamples, seed=bootstrap_seed
        )
        out[name] = {
            "per_seed": per_seed,
            "mean": mean(per_seed),
            "ci95": [lo, hi],
        }
    return out
