"""Bootstrap CI math + aggregation utility tests."""
from __future__ import annotations

import math

import pytest

from bench.eval.scoring import (
    aggregate_seed_metrics,
    bootstrap_ci,
    mean,
    percentile,
)


def test_percentile_edges():
    assert percentile([], 0.5) == 0.0
    assert percentile([1.0], 0.5) == 1.0
    assert percentile([0.0, 1.0], 0.0) == 0.0
    assert percentile([0.0, 1.0], 1.0) == 1.0


def test_percentile_linear_interp():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    # median should land exactly on 2.0
    assert percentile(vals, 0.5) == pytest.approx(2.0)
    # quarter way
    assert percentile(vals, 0.25) == pytest.approx(1.0)


def test_mean():
    assert mean([]) == 0.0
    assert mean([1.0, 2.0, 3.0]) == 2.0


def test_bootstrap_ci_degenerate_cases():
    assert bootstrap_ci([]) == (0.0, 0.0)
    assert bootstrap_ci([0.5]) == (0.5, 0.5)


def test_bootstrap_ci_is_deterministic_given_seed():
    vals = [0.4, 0.5, 0.6, 0.6, 0.7]
    lo1, hi1 = bootstrap_ci(vals, n_resamples=500, seed=42)
    lo2, hi2 = bootstrap_ci(vals, n_resamples=500, seed=42)
    assert lo1 == lo2
    assert hi1 == hi2
    # And the CI should bracket the sample mean.
    sample_mean = sum(vals) / len(vals)
    assert lo1 <= sample_mean <= hi1


def test_bootstrap_ci_narrows_with_more_samples():
    # CI on identical values should collapse to a point at the value.
    lo, hi = bootstrap_ci([0.5, 0.5, 0.5, 0.5], n_resamples=200, seed=0)
    assert lo == pytest.approx(0.5)
    assert hi == pytest.approx(0.5)


def test_bootstrap_ci_brackets_mean_for_spread_data():
    vals = [0.0, 0.5, 1.0]
    lo, hi = bootstrap_ci(vals, n_resamples=2000, seed=7)
    m = mean(vals)
    assert lo <= m <= hi
    # spread CI should be wider than zero
    assert hi - lo > 0.0


def test_aggregate_seed_metrics_shape():
    per_seed = [
        {"valid_at_1": 0.4, "exec_success": 0.2},
        {"valid_at_1": 0.6, "exec_success": 0.4},
        {"valid_at_1": 0.5, "exec_success": 0.3},
    ]
    agg = aggregate_seed_metrics(
        per_seed,
        metric_names=["valid_at_1", "exec_success"],
        n_resamples=300,
        bootstrap_seed=0,
    )
    assert set(agg.keys()) == {"valid_at_1", "exec_success"}
    for name, block in agg.items():
        assert set(block.keys()) == {"per_seed", "mean", "ci95"}
        assert len(block["per_seed"]) == 3
        assert isinstance(block["mean"], float)
        assert isinstance(block["ci95"], list)
        assert len(block["ci95"]) == 2
        lo, hi = block["ci95"]
        assert lo <= block["mean"] <= hi
