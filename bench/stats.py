# bench/stats.py
"""
Shared percentile / summary statistics over latency samples.

Used by both the brainstem /fabric/status endpoint and bench/analyze.py
so the dashboard and the offline analysis report numbers the same way.
"""
from __future__ import annotations

from typing import Dict, List, Sequence


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
