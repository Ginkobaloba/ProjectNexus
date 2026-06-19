# bench/

Model-quality eval harness for project-nexus. Lives in two halves:

- `bench/eval/` is the eval bench from Sprint 3d Card 4, the real home of the
  zero-byte `scripts/benchmark_inference.py`. Headline metric is Task 1
  (Builder) `valid@1` per `NEXUS_PATH_TO_OUTPERFORM` section 1.3.
- `bench/analyze.py`, `bench/latency_bench.py`, `bench/probes.py`,
  `bench/stats.py` are the systems bench from Sprints 3a to 3c. They measure
  fabric latency and throughput, not model quality. The eval bench reuses the
  `percentile` helper from `bench/stats.py` so dashboards and reports agree on
  the math.

This document describes the eval bench.

## Quick start

Run Task 1 (Builder) against the 4090 cortex with 3 seeds and label the run
`baseline_v1`:

```
python -m bench.eval --task builder --seeds 3 --label baseline_v1
```

Run all six tasks (Task 1 and Task 5 wired, Tasks 2/3/4/6 stubbed) end to end:

```
python -m bench.eval --task all --seeds 3 --label baseline_v1
```

Dry-run the wiring without hitting the cortex:

```
python -m bench.eval --task all --seeds 3 --label smoke --provider stub
```

The runner writes one file per `(task, seed)` plus a per-task summary and an
overall summary into `bench/results/`:

```
bench/results/baseline_v1_builder_seed0.json
bench/results/baseline_v1_builder_seed1.json
bench/results/baseline_v1_builder_seed2.json
bench/results/baseline_v1_builder_summary.json
...
bench/results/baseline_v1_overall.json
```

## Tasks

The 6 task families from `NEXUS_PATH_TO_OUTPERFORM` section 1.2 are mapped to
modules under `bench/eval/tasks/`:

| Task | Module | Status | Primary metric |
|---|---|---|---|
| 1: Workflow synthesis (Builder) | `tasks/builder.py` | wired | `valid_at_1`, `exec_success` |
| 2: Intent parse + routing | `tasks/routing.py` | stub | `routing_top1` |
| 3: Agentic tool use | `tasks/tool_use.py` | stub | `task_success` |
| 4: RAG Q&A over memory | `tasks/rag_qa.py` | stub | `answer_correctness` |
| 5: General coding (HumanEval+/MBPP) | `tasks/code_pub.py` | wired | `pass_at_1` |
| 6: General-capability guards | `tasks/guards.py` | stub | `guard_aggregate` |

Stub tasks return a fixed-zero score and set `stub_placeholder: true` in their
`task_meta` and `SeedResult` JSON. Card 5 baselines render stub tasks as
"not yet measured" rather than scoring them zero.

## Task interface

Every task implements the same shape (see `bench/eval/base.py` for the
protocol):

```python
class EvalTask:
    task_id: str
    primary_metric: str
    stub_placeholder: bool

    def task_meta(self) -> Dict[str, Any]: ...
    def load_problems(self) -> Sequence[Problem]: ...
    def build_prompt(self, problem: Problem) -> str: ...
    def score(self, problem: Problem, completion: str) -> Dict[str, float]: ...
```

The default base `EvalTaskBase` provides the boilerplate; concrete tasks
override only what differs.

## How to add Task N

1. Create `bench/eval/tasks/<task_id>.py` with a subclass of `EvalTaskBase`.
   Implement `load_problems`, `build_prompt`, and `score`. Set `task_id`,
   `primary_metric`, `dataset_id` as class attributes. Set
   `stub_placeholder = False` once the task is real (start as a stub if the
   wiring lands before the scorer).
2. Expose a `get_task() -> EvalTask` factory at module level.
3. Register the task_id in `bench/eval/tasks/__init__.py`'s `TASK_REGISTRY`.
4. Drop the frozen dataset under `bench/eval/datasets/<task_id>_<version>.jsonl`.
   Each record is a dict matching the shape `load_problems` expects.
5. Drop the frozen prompt template under `bench/eval/prompts/<task_id>.txt`.
6. Add a pytest module under `tests/bench_eval/test_task_<task_id>.py` with
   at least: extraction is correct, scorer is deterministic on a fixed
   completion, scorer returns zero on a known-bad completion.
7. Run `python -m bench.eval --task <task_id> --seeds 3 --label dev` to
   smoke-test end to end.

## Provider adapter (BYO-LLM)

The runner is provider-agnostic. Two providers ship in `bench/eval/provider.py`:

- `OpenAICompatProvider` is the default. Talks to any `/v1/chat/completions`
  endpoint. Default `base_url=http://localhost:8000/v1`, `model="cortex"`,
  matching `automation/scripts/setup-cortex-llm.sh` for the 4090 vLLM serving
  `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`.
- `StubProvider` returns a canned response. Used by the test suite and for
  dry runs.

### Swap to a different provider

Via env vars (the CLI default):

```
NEXUS_BENCH_BASE_URL=https://gov.example/v1
NEXUS_BENCH_MODEL=gpt-5.1
NEXUS_BENCH_API_KEY=sk-xxxxxx
NEXUS_BENCH_TIMEOUT_S=180
python -m bench.eval --task builder --seeds 3 --label gpt51_run
```

Via CLI flags (overrides env vars):

```
python -m bench.eval --task builder --seeds 3 --label gpt51_run \
    --provider openai_compat \
    --base-url https://gov.example/v1 \
    --model gpt-5.1
```

### Adding a new provider kind

1. Subclass `LLMProvider` in `bench/eval/provider.py`, implement
   `complete(prompt, sampling) -> CompletionResponse`, and expose a
   `config: ProviderConfig`. The config snapshot is recorded into every
   `SeedResult` so any later re-run can validate it hit the same endpoint.
2. Register the kind in `PROVIDER_REGISTRY`.
3. Wire it into `cli.py` if it needs custom args.

## Result schema

Every per-seed file (`<run_label>_<task_id>_seed<N>.json`) contains:

| Field | Description |
|---|---|
| `run_label` | the `--label` argument |
| `task_id` | the task module's `task_id` |
| `seed` | the integer seed for sampling |
| `timestamp_utc` | when the seed run completed |
| `harness_version` | `bench.eval.__version__` |
| `git_sha` | `git rev-parse HEAD` at run time |
| `provider` | `{kind, base_url, model, extra}` |
| `sampling` | `{temperature, top_p, max_tokens, seed}` |
| `task_meta` | per-task metadata, includes `stub_placeholder` |
| `metrics` | `{metric_name: float}` mean across the task's problems |
| `per_problem` | list of `ProblemResult` records |
| `aggregate` | `{primary_metric, primary_metric_value, tokens_*_total, latency_p50_s, latency_p95_s, n_problems}` |
| `stub_placeholder` | bool, copied from `task_meta` for convenience |

Every per-task summary file (`<run_label>_<task_id>_summary.json`) contains:

```json
{
  "run_label": "baseline_v1",
  "task_id": "builder",
  "seeds": [0, 1, 2],
  "metrics": {
    "valid_at_1": {
      "per_seed": [0.4, 0.6, 0.5],
      "mean": 0.5,
      "ci95": [lo, hi]
    },
    "exec_success": { ... }
  },
  "primary_metric": "valid_at_1",
  "stub_placeholder": false,
  "notes": ""
}
```

The overall file (`<run_label>_overall.json`) lists every task with its primary
metric and CI:

```json
{
  "run_label": "baseline_v1",
  "harness_version": "0.1.0",
  "git_sha": "...",
  "timestamp_utc": "...",
  "tasks": {
    "builder": {"primary_metric": "valid_at_1", "mean": 0.5, "ci95": [lo, hi], "stub_placeholder": false},
    "routing": {"primary_metric": "routing_top1", "mean": 0.0, "ci95": [0.0, 0.0], "stub_placeholder": true},
    ...
  }
}
```

Card 5 reads the summary files to build `bench/eval/baseline_v1.json`.

## Builder exec-success oracle (Card 5)

Task 1 has two scorers:

- `valid_at_1` is the deterministic validator chain in `tasks/builder.py`. It
  is pure and offline.
- `exec_success` is a separate "would this n8n actually run" check. There are
  two oracle paths, gated by reachability:
    - **n8n MCP `validate_workflow`** over HTTP Streamable. Canonical per Card
      5 Decision 3. Code lives in `bench/eval/tasks/_n8n_oracle.py`. The MCP
      contract is fixed by `Nexus_N8N-MCP/src/mcp/tools.ts`.
    - **Structural reachability simulator** (the original sim). Documented
      fallback when the MCP is unreachable. Permissive by design: a passing
      structural sim is necessary but not sufficient for true exec success.

The active path is chosen at task construction:

```
NEXUS_BENCH_BUILDER_ORACLE=auto         # default: probe MCP, fall back to sim
NEXUS_BENCH_BUILDER_ORACLE=mcp          # force MCP (errors on score if down)
NEXUS_BENCH_BUILDER_ORACLE=structural   # force the sim
```

MCP target overrides:

```
NEXUS_BENCH_N8N_MCP_URL=http://localhost:3000
NEXUS_BENCH_N8N_MCP_TOKEN=<bearer>
NEXUS_BENCH_N8N_MCP_TIMEOUT=30.0
NEXUS_BENCH_N8N_MCP_PROBE_TIMEOUT=2.0
```

Each `SeedResult.task_meta.oracle.mode` records which path scored that run,
so downstream readers can tell `structural_sim` runs from `mcp` runs. The
Card 5 `baseline_v1` shipped with `mode = "structural_sim"` because the n8n
MCP container was offline on DREWSPC at run time; `baseline_v2` will re-run
with the MCP up and report the delta.

## Bootstrap 95% CI

`bench/eval/scoring.py:bootstrap_ci` resamples per-seed values with
replacement (default 1000 resamples) and returns the 2.5th and 97.5th
percentiles of the resample-mean distribution. The bootstrap seed is recorded
so reruns reproduce the interval byte for byte. Defaults match the discipline
in `NEXUS_PATH_TO_OUTPERFORM` section 1.2: every score reports p50 and a
bootstrap 95% CI over at least 3 seeds.

## Datasets

See `bench/eval/datasets/README.md` for the per-dataset notes. Highlights:

- `builder_skeleton_v1.jsonl` is a 5-example placeholder. Card 5 swaps in the
  curated 50-example held-out set; the schema is identical.
- `code_pub_skeleton_v1.jsonl` is a 3-example local stand-in for HumanEval+ /
  MBPP. Set `NEXUS_BENCH_CODEPUB_SOURCE=humanevalplus` or `=mbpp` to fetch
  the real datasets via Hugging Face. License notes in `tasks/code_pub.py`.

## What is not in this skeleton

Card 4 is infrastructure only. Out of scope:

- Running the baseline. That is Card 5.
- Any training. That is Tracks A/B/C.
- Touching the cortex or brainstem serving infra. Bench is a client.

## Tests

```
python -m pytest tests/bench_eval/ -v
```

Coverage at Sprint 3d Card 4 close: 40 tests across scoring math, the Builder
validator chain, the Code task subprocess scorer, all four stub tasks, and
the end-to-end runner with mocked providers.
