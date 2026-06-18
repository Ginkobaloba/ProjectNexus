"""End-to-end runner: stub provider, real tasks, writes deterministic JSON,
aggregates per-task and overall correctly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.eval.provider import StubProvider
from bench.eval.runner import BenchRunner
from bench.eval.tasks import get_task


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_runner_writes_per_seed_and_summary(tmp_results_dir: Path):
    provider = StubProvider(canned="STUB")
    runner = BenchRunner(
        provider=provider,
        run_label="t",
        results_dir=tmp_results_dir,
        n_bootstrap_resamples=200,
    )
    task = get_task("routing")  # cheap stub
    summary = runner.run_task(task, seeds=[0, 1, 2])

    # 3 seed files + 1 summary file
    seed_files = sorted(tmp_results_dir.glob("t_routing_seed*.json"))
    assert len(seed_files) == 3
    summary_file = tmp_results_dir / "t_routing_summary.json"
    assert summary_file.exists()

    # Summary shape matches the schema
    body = _read_json(summary_file)
    assert body["task_id"] == "routing"
    assert body["seeds"] == [0, 1, 2]
    assert body["primary_metric"] == "routing_top1"
    assert body["stub_placeholder"] is True
    assert "routing_top1" in body["metrics"]
    block = body["metrics"]["routing_top1"]
    assert "per_seed" in block and "mean" in block and "ci95" in block


def test_runner_aggregate_overall_lists_every_task(tmp_results_dir: Path):
    provider = StubProvider(canned="STUB")
    runner = BenchRunner(
        provider=provider,
        run_label="ovr",
        results_dir=tmp_results_dir,
        n_bootstrap_resamples=100,
    )
    summaries = []
    for tid in ["builder", "routing"]:
        summaries.append(runner.run_task(get_task(tid), seeds=[0, 1, 2]))
    overall = runner.aggregate_overall(summaries)

    out_path = tmp_results_dir / "ovr_overall.json"
    assert out_path.exists()
    body = _read_json(out_path)
    assert set(body["tasks"].keys()) == {"builder", "routing"}
    assert body["tasks"]["builder"]["primary_metric"] == "valid_at_1"
    assert body["tasks"]["routing"]["primary_metric"] == "routing_top1"
    assert body["tasks"]["routing"]["stub_placeholder"] is True
    assert body["tasks"]["builder"]["stub_placeholder"] is False


def test_runner_records_provider_and_sampling_in_seed_result(tmp_results_dir: Path):
    provider = StubProvider(canned="anything", base_url="stub://x", model="m1")
    runner = BenchRunner(
        provider=provider,
        run_label="recs",
        results_dir=tmp_results_dir,
        temperature=0.7,
        top_p=0.9,
        max_tokens=512,
    )
    runner.run_task(get_task("routing"), seeds=[0])
    body = _read_json(tmp_results_dir / "recs_routing_seed0.json")
    assert body["provider"]["kind"] == "stub"
    assert body["provider"]["base_url"] == "stub://x"
    assert body["provider"]["model"] == "m1"
    assert body["sampling"]["temperature"] == 0.7
    assert body["sampling"]["top_p"] == 0.9
    assert body["sampling"]["max_tokens"] == 512
    assert body["sampling"]["seed"] == 0


def test_runner_handles_builder_with_canned_valid_completion(tmp_results_dir: Path):
    """If the provider always returns the same VALID workflow that satisfies
    one problem, the Builder task should give that problem score 1.0 and zero
    on the rest. End-to-end determinism check."""
    canned_wf = (
        "```json\n"
        '{"name": "x", "nodes": ['
        '{"name": "n1", "type": "webhook"},'
        '{"name": "n2", "type": "set"},'
        '{"name": "n3", "type": "http"}'
        '], "connections": {'
        '"n1": [{"node": "n2"}], "n2": [{"node": "n3"}]'
        "}}\n```"
    )
    provider = StubProvider(canned=canned_wf)
    runner = BenchRunner(
        provider=provider,
        run_label="canned",
        results_dir=tmp_results_dir,
        n_bootstrap_resamples=100,
    )
    summary = runner.run_task(get_task("builder"), seeds=[0])
    body = _read_json(tmp_results_dir / "canned_builder_seed0.json")
    # bld_001 wants webhook+set+http -> this completion satisfies it.
    per_problem_metrics = {
        r["problem_id"]: r["metrics"] for r in body["per_problem"]
    }
    assert per_problem_metrics["bld_001"]["valid_at_1"] == 1.0
    # bld_003 wants webhook+function+set; this completion does not include function
    assert per_problem_metrics["bld_003"]["valid_at_1"] == 0.0


def test_runner_records_provider_error_as_zero(tmp_results_dir: Path):
    """If the provider raises ProviderError, the runner must record the error,
    score the problem as zero on every metric, and NOT propagate the exception."""
    from bench.eval.base import Sampling
    from bench.eval.provider import CompletionResponse, ProviderError, ProviderConfig

    class BoomProvider:
        config = ProviderConfig(kind="boom", base_url="boom://", model="boom")

        def complete(self, prompt, sampling):
            raise ProviderError("synthetic failure")

    runner = BenchRunner(
        provider=BoomProvider(),
        run_label="boom",
        results_dir=tmp_results_dir,
        n_bootstrap_resamples=50,
    )
    runner.run_task(get_task("routing"), seeds=[0])
    body = _read_json(tmp_results_dir / "boom_routing_seed0.json")
    assert all(pr["error"] for pr in body["per_problem"])
    # the metric still aggregates as zero (no scores were emitted)
    assert body["metrics"].get("routing_top1", 0.0) == 0.0
