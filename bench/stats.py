# bench/stats.py
"""
Shared percentile / summary statistics over latency samples.

Used by both the brainstem /fabric/status endpoint and bench/analyze.py
so the dashboard and the offline analysis report numbers the same way.
"""
from __future__ import annotations

import random
from typing import Dict, List, Sequence, Tuple


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile. `p` is a fraction in [0, 1].
    `sorted_vals` must already be sorted ascending."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def summarize(values: List[float]) -> Dict[str, float]:
    """count + min/mean/max + p50/p95/p99 for a list of samples.
    Returns zeros (not an error) for an empty list so callers and the
    dashboard do not have to special-case the cold-start state."""
    if not values:
        return {
            "count": 0, "min": 0.0, "mean": 0.0, "max": 0.0,
            "p50": 0.0, "p95": 0.0, "p99": 0.0,
        }
    s = sorted(values)
    return {
        "count": len(s),
        "min": round(s[0], 3),
        "mean": round(sum(s) / len(s), 3),
        "max": round(s[-1], 3),
        "p50": round(percentile(s, 0.50), 3),
        "p95": round(percentile(s, 0.95), 3),
        "p99": round(percentile(s, 0.99), 3),
    }


def bootstrap_ci(
    values: Sequence[float],
    *,
    iters: int = 10000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Tuple[float, float, float]:
    """Bootstrap point estimate + CI for the mean of `values`.

    Resamples the sample with replacement `iters` times and takes the percentile
    interval of the resampled means. The program design requires every score to
    report a bootstrap 95% CI rather than a bare point estimate, so a win is only
    a win when the candidate's CI does not overlap the baseline's. Seeded for
    reproducibility. Returns (mean, lo, hi); for an empty sample, (0, 0, 0).
    """
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return float(mean), float(values[0]), float(values[0])
    rng = random.Random(seed)
    vals = list(values)
    means = []
    for _ in range(iters):
        resample = (vals[rng.randrange(n)] for _ in range(n))
        means.append(sum(resample) / n)
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lo = percentile(means, tail)
    hi = percentile(means, 1.0 - tail)
    return round(mean, 4), round(lo, 4), round(hi, 4)
