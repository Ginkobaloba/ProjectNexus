"""
bench.eval.cli: command-line entrypoint.

Usage:
    python -m bench.eval --task builder --seeds 3 --label baseline_v1
    python -m bench.eval --task code_pub --seeds 3 --label baseline_v1
    python -m bench.eval --task all --seeds 3 --label baseline_v1

Provider:
    Default reads NEXUS_BENCH_* env vars (see bench/eval/provider.py docstring).
    Override with --provider stub for a dry-run that exercises the wiring
    without hitting the cortex.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from .provider import OpenAICompatProvider, StubProvider, default_provider_from_env
from .runner import BenchRunner, DEFAULT_RESULTS_DIR
from .tasks import TASK_REGISTRY, all_task_ids, get_task


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m bench.eval")
    p.add_argument(
        "--task",
        default="all",
        help=f"task_id to run, or 'all'. registered: {','.join(all_task_ids())}",
    )
    p.add_argument(
        "--seeds",
        type=int,
        default=3,
        help="number of seeds (>=3 per the sprint plan)",
    )
    p.add_argument(
        "--seed-start",
        type=int,
        default=0,
        help="first seed value; seeds run as range(seed_start, seed_start+seeds)",
    )
    p.add_argument(
        "--label",
        required=True,
        help="run label (e.g. baseline_v1) used in result filenames",
    )
    p.add_argument(
        "--provider",
        choices=["openai_compat", "stub", "env"],
        default="env",
        help="provider kind. 'env' uses NEXUS_BENCH_* env vars (default)",
    )
    p.add_argument("--base-url", default=None, help="override provider base_url")
    p.add_argument("--model", default=None, help="override provider model id")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--top-p", type=float, default=1.0)
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=1000,
        help="bootstrap resamples for the 95%% CI on each metric",
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help=f"output directory (default {DEFAULT_RESULTS_DIR})",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Resolve provider.
    if args.provider == "stub":
        provider = StubProvider(canned="STUB_COMPLETION")
    elif args.provider == "openai_compat":
        base_url = args.base_url or "http://localhost:8000/v1"
        model = args.model or "cortex"
        provider = OpenAICompatProvider(base_url=base_url, model=model)
    else:
        provider = default_provider_from_env()
        if args.base_url:
            provider.base_url = args.base_url
            provider.config = provider.config.__class__(
                kind=provider.config.kind,
                base_url=args.base_url,
                model=provider.config.model,
                extra=provider.config.extra,
            )
        if args.model:
            provider.model = args.model

    # Resolve task list.
    if args.task == "all":
        task_ids = all_task_ids()
    else:
        if args.task not in TASK_REGISTRY:
            print(
                f"unknown task {args.task!r}; choose from {all_task_ids()}",
                file=sys.stderr,
            )
            return 2
        task_ids = [args.task]

    seeds = list(range(args.seed_start, args.seed_start + max(1, args.seeds)))
    runner = BenchRunner(
        provider=provider,
        run_label=args.label,
        results_dir=args.results_dir,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        n_bootstrap_resamples=args.bootstrap_resamples,
    )

    summaries = []
    for tid in task_ids:
        task = get_task(tid)
        print(
            f"[bench.eval] running task={tid} seeds={seeds} stub={getattr(task, 'stub_placeholder', False)}"
        )
        summary = runner.run_task(task, seeds=seeds)
        summaries.append(summary)
        primary = summary.primary_metric
        block = summary.metrics.get(primary, {})
        print(
            f"  primary={primary} mean={block.get('mean', 0.0):.4f} "
            f"ci95=[{block.get('ci95', [0,0])[0]:.4f}, {block.get('ci95', [0,0])[1]:.4f}]"
        )

    overall = runner.aggregate_overall(summaries)
    print(f"[bench.eval] overall summary written: {len(overall['tasks'])} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
