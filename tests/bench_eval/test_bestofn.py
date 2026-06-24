"""Tests for Sprint 3d Card 6: verifier-guided best-of-N.

Every test runs offline against StubProvider so the suite has no dependence on
the cortex or on the network. The stubs cover:

    1. _select_candidate priority (oracle-pass beats highest-score beats empty)
    2. BestOfNRunner end-to-end shape on a wired task (code_pub)
    3. Determinism: same seed -> identical results
    4. Best-of-N >= baseline when the verifier is honest (lift can be positive)
    5. build_comparison + write_comparison_artifacts produce JSON + SVG that
       parse and contain the expected fields
    6. --best-of-n CLI flag end-to-end against the stub provider on a real task
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from bench.eval.base import Sampling, TaskSummary
from bench.eval.bestofn import (
    BestOfNRunner,
    BestOfNSummary,
    CandidateResult,
    DEFAULT_BESTOFN_N,
    PICKED_HIGHEST_SCORE,
    PICKED_NO_VALID,
    PICKED_ORACLE_PASS,
    _select_candidate,
)
from bench.eval.comparison import build_comparison, write_comparison_artifacts
from bench.eval.provider import StubProvider
from bench.eval.runner import BenchRunner
from bench.eval.tasks import get_task


# ---------------------------------------------------------------------------
# Selection rule
# ---------------------------------------------------------------------------


def _cand(idx: int, score: float, primary: str = "pass_at_1", err=None) -> CandidateResult:
    return CandidateResult(
        candidate_idx=idx,
        completion=f"c{idx}",
        metrics={primary: score},
        prompt_tokens=0,
        completion_tokens=0,
        latency_s=0.0,
        error=err,
    )


def test_select_oracle_pass_wins_lowest_index():
    cands = [_cand(0, 0.0), _cand(1, 1.0), _cand(2, 1.0)]
    idx, reason, val = _select_candidate(cands, "pass_at_1")
    assert idx == 1
    assert reason == PICKED_ORACLE_PASS
    assert val == 1.0


def test_select_highest_score_when_no_oracle_pass():
    cands = [_cand(0, 0.2), _cand(1, 0.7), _cand(2, 0.5)]
    idx, reason, val = _select_candidate(cands, "pass_at_1")
    assert idx == 1
    assert reason == PICKED_HIGHEST_SCORE
    assert val == pytest.approx(0.7)


def test_select_tie_broken_by_lowest_index():
    cands = [_cand(0, 0.5), _cand(1, 0.5)]
    idx, _reason, _ = _select_candidate(cands, "pass_at_1")
    assert idx == 0


def test_select_skips_errored_candidates():
    cands = [
        _cand(0, 1.0, err="provider_down"),
        _cand(1, 0.3),
        _cand(2, 0.8),
    ]
    idx, reason, val = _select_candidate(cands, "pass_at_1")
    # Errored candidate is skipped even though its metric dict says 1.0.
    assert idx == 2
    assert reason == PICKED_HIGHEST_SCORE
    assert val == pytest.approx(0.8)


def test_select_no_valid_when_all_error():
    cands = [_cand(0, 0.0, err="e"), _cand(1, 0.0, err="e")]
    idx, reason, val = _select_candidate(cands, "pass_at_1")
    assert idx == -1
    assert reason == PICKED_NO_VALID
    assert val == 0.0


def test_select_empty_returns_no_valid():
    idx, reason, val = _select_candidate([], "pass_at_1")
    assert idx == -1
    assert reason == PICKED_NO_VALID
    assert val == 0.0


# ---------------------------------------------------------------------------
# End-to-end on code_pub
# ---------------------------------------------------------------------------


def _code_pub_solution_for(prompt: str) -> str:
    """Return a correct fenced-python completion for a code_pub stub prompt.
    The prompt template wraps the problem.prompt (the function signature) so
    we look for the entry-point keyword inside the prompt string."""
    if "def add" in prompt:
        return "```python\ndef add(a, b):\n    return a + b\n```"
    if "def is_even" in prompt:
        return "```python\ndef is_even(n):\n    return n % 2 == 0\n```"
    if "def reverse_string" in prompt:
        return "```python\ndef reverse_string(s):\n    return s[::-1]\n```"
    return "```python\nraise NotImplementedError\n```"


def _bad_completion(prompt: str) -> str:
    """Return a clearly wrong completion (no fenced block)."""
    return "I'd love to help but I'm not sure how"


def test_bestofn_picks_correct_candidate_on_code_pub(tmp_results_dir):
    """Stub provider returns wrong outputs on candidate seeds 0,1 and a
    correct output on candidate seed 2+. Best-of-N must find a correct one
    and score pass_at_1 == 1.0 per problem."""

    def canned(prompt: str, sampling: Sampling) -> str:
        # First two candidates per problem are wrong; the rest are correct.
        # base_seed=0, n=4 -> candidate seeds 0,1,2,3. cand_idx = seed % n.
        cand_idx = sampling.seed % 4
        if cand_idx < 2:
            return _bad_completion(prompt)
        return _code_pub_solution_for(prompt)

    provider = StubProvider(canned_fn=canned)
    runner = BestOfNRunner(
        provider=provider,
        run_label="t",
        results_dir=tmp_results_dir,
        n_candidates=4,
        temperature=0.8,
        n_bootstrap_resamples=100,
    )
    task = get_task("code_pub")
    summary = runner.run_task(task, seeds=[0, 1, 2])

    # Summary file exists, primary metric is pass_at_1, mean is 1.0 (the
    # verifier always finds a correct candidate within N=4).
    summary_file = tmp_results_dir / "t_code_pub_bestofn_summary.json"
    assert summary_file.exists()
    block = summary.metrics["pass_at_1"]
    assert block["mean"] == pytest.approx(1.0)
    assert block["per_seed"] == [1.0, 1.0, 1.0]
    # Selection should be all-oracle-pass.
    assert summary.selection_stats["totals"][PICKED_ORACLE_PASS] > 0
    assert summary.selection_stats["totals"][PICKED_NO_VALID] == 0


def test_bestofn_zero_when_no_candidate_passes(tmp_results_dir):
    provider = StubProvider(canned="never going to pass")
    runner = BestOfNRunner(
        provider=provider,
        run_label="t",
        results_dir=tmp_results_dir,
        n_candidates=4,
        temperature=0.8,
        n_bootstrap_resamples=100,
    )
    task = get_task("code_pub")
    summary = runner.run_task(task, seeds=[0, 1])
    assert summary.metrics["pass_at_1"]["mean"] == pytest.approx(0.0)
    # No oracle pass; selector falls back to highest-score, but every score is
    # zero, so it picks index 0 with value 0.0 (PICKED_HIGHEST_SCORE on ties).
    assert summary.selection_stats["totals"][PICKED_HIGHEST_SCORE] > 0


def test_bestofn_seed_files_carry_full_candidate_audit_trail(tmp_results_dir):
    provider = StubProvider(canned="```python\ndef add(a,b): return a+b\n```")
    runner = BestOfNRunner(
        provider=provider,
        run_label="trail",
        results_dir=tmp_results_dir,
        n_candidates=3,
        n_bootstrap_resamples=50,
    )
    task = get_task("code_pub")
    runner.run_task(task, seeds=[0])

    seed_file = tmp_results_dir / "trail_code_pub_bestofn_seed0.json"
    assert seed_file.exists()
    body = json.loads(seed_file.read_text(encoding="utf-8"))
    # Per-problem records have all 3 candidates each.
    assert body["task_id"] == "code_pub"
    assert body["n_candidates"] == 3
    for pp in body["per_problem"]:
        assert len(pp["candidates"]) == 3
        for c in pp["candidates"]:
            assert "completion" in c
            assert "metrics" in c
        assert pp["picked_idx"] in (0, 1, 2)
        assert pp["picked_reason"] in (
            PICKED_ORACLE_PASS,
            PICKED_HIGHEST_SCORE,
            PICKED_NO_VALID,
        )
    # Aggregate carries cost-axis fields.
    assert "tokens_prompt_total" in body["aggregate"]
    assert "latency_p50_s" in body["aggregate"]
    assert body["aggregate"]["n_candidates_total"] == 3 * len(body["per_problem"])


def test_bestofn_is_deterministic(tmp_results_dir):
    def canned(prompt: str, sampling: Sampling) -> str:
        # Output depends on seed so different seeds give different completions.
        cand_idx = sampling.seed % 5
        if cand_idx == 3:
            return _code_pub_solution_for(prompt)
        return _bad_completion(prompt)

    provider = StubProvider(canned_fn=canned)

    def _go(label: str):
        return BestOfNRunner(
            provider=provider,
            run_label=label,
            results_dir=tmp_results_dir,
            n_candidates=5,
            n_bootstrap_resamples=200,
        ).run_task(get_task("code_pub"), seeds=[0, 1])

    a = _go("a")
    b = _go("b")
    assert a.metrics["pass_at_1"]["per_seed"] == b.metrics["pass_at_1"]["per_seed"]


# ---------------------------------------------------------------------------
# Comparison artifact
# ---------------------------------------------------------------------------


def _fake_baseline(task_id: str = "code_pub", mean: float = 0.4) -> TaskSummary:
    return TaskSummary(
        run_label="b",
        task_id=task_id,
        seeds=[0, 1, 2],
        metrics={
            "pass_at_1": {
                "per_seed": [mean, mean, mean],
                "mean": mean,
                "ci95": [mean, mean],
            }
        },
        primary_metric="pass_at_1",
        stub_placeholder=False,
        notes="",
    )


def _fake_bestofn(task_id: str = "code_pub", mean: float = 0.8, n: int = 8) -> BestOfNSummary:
    return BestOfNSummary(
        run_label="bo",
        task_id=task_id,
        seeds=[0, 1, 2],
        primary_metric="pass_at_1",
        n_candidates=n,
        metrics={
            "pass_at_1": {
                "per_seed": [mean, mean, mean],
                "mean": mean,
                "ci95": [mean, mean],
            }
        },
        selection_stats={
            "totals": {PICKED_ORACLE_PASS: 3, PICKED_HIGHEST_SCORE: 0, PICKED_NO_VALID: 0},
            "fractions": {PICKED_ORACLE_PASS: 1.0, PICKED_HIGHEST_SCORE: 0.0, PICKED_NO_VALID: 0.0},
        },
        cost={
            "tokens_prompt_total": 100,
            "tokens_completion_total": 200,
            "latency_p50_s_mean": 0.0,
            "latency_p95_s_mean": 0.0,
            "n_candidates_per_problem": n,
        },
    )


def test_build_comparison_math():
    comp = build_comparison(_fake_baseline(mean=0.4), _fake_bestofn(mean=0.8, n=8))
    assert comp.task_id == "code_pub"
    assert comp.primary_metric == "pass_at_1"
    assert comp.baseline_mean == pytest.approx(0.4)
    assert comp.bestofn_mean == pytest.approx(0.8)
    assert comp.lift_abs_pp == pytest.approx(40.0)
    assert comp.non_overlapping_ci is True
    assert comp.cost_multiplier == 8.0


def test_build_comparison_rejects_task_id_mismatch():
    with pytest.raises(ValueError, match="task_id"):
        build_comparison(_fake_baseline("a"), _fake_bestofn("b"))


def test_write_comparison_artifacts_emits_json_and_svg(tmp_results_dir):
    comp = build_comparison(_fake_baseline(mean=0.4), _fake_bestofn(mean=0.8, n=8))
    paths = write_comparison_artifacts(comp, tmp_results_dir)
    json_body = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert json_body["task_id"] == "code_pub"
    assert json_body["bestofn"]["n_candidates"] == 8
    assert json_body["lift_abs_pp"] == pytest.approx(40.0)
    svg = paths["svg"].read_text(encoding="utf-8")
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert "best-of-8" in svg
    assert "baseline" in svg
    # Lift annotation present (with the +40.0 pp formatting).
    assert "+40.0" in svg or "40.0 pp" in svg


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_runs_bestofn_arm_on_stub_provider(tmp_results_dir, monkeypatch):
    """--best-of-n N triggers both arms and emits the comparison files."""
    from bench.eval.cli import main as cli_main

    rc = cli_main(
        [
            "--task", "code_pub",
            "--seeds", "2",
            "--label", "cli_smoke",
            "--provider", "stub",
            "--results-dir", str(tmp_results_dir),
            "--best-of-n", "4",
            "--bootstrap-resamples", "100",
        ]
    )
    assert rc == 0
    # Both arms produced their summary files.
    assert (tmp_results_dir / "cli_smoke_code_pub_summary.json").exists()
    assert (tmp_results_dir / "cli_smoke_code_pub_bestofn_summary.json").exists()
    # Comparison files exist.
    assert (tmp_results_dir / "cli_smoke_code_pub_comparison.json").exists()
    assert (tmp_results_dir / "cli_smoke_code_pub_comparison.svg").exists()


def test_cli_skip_baseline_arm_only_runs_bestofn(tmp_results_dir):
    from bench.eval.cli import main as cli_main

    rc = cli_main(
        [
            "--task", "code_pub",
            "--seeds", "1",
            "--label", "cli_skip",
            "--provider", "stub",
            "--results-dir", str(tmp_results_dir),
            "--best-of-n", "2",
            "--skip-baseline-arm",
            "--bootstrap-resamples", "50",
        ]
    )
    assert rc == 0
    # Baseline summary should NOT be written.
    assert not (tmp_results_dir / "cli_skip_code_pub_summary.json").exists()
    # Best-of-N summary IS written.
    assert (tmp_results_dir / "cli_skip_code_pub_bestofn_summary.json").exists()
    # No comparison since there is no baseline arm to compare against.
    assert not (tmp_results_dir / "cli_skip_code_pub_comparison.json").exists()
