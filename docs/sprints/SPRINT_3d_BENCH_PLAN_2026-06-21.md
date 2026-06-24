# Sprint 3d Bench Plan: how `bench/eval/` measures "outperform 4090 base"

Date: 2026-06-21
Author: Sprint 3d Card 8 (Opus)
Scope: documentation only. Companion to `SPRINT_3d_PLAN_2026-06-18.md` (the sprint of record) and to `NEXUS_PATH_TO_OUTPERFORM_v0.1.md` (the inference-quality program).
Audience: any agent or human who needs to (a) read a bench result and know what it means, (b) re-run a baseline byte-for-byte, or (c) add a new task to the harness without breaking the existing comparison invariants.

## 1. Why this doc exists

`bench/eval/` is the falsifiable program behind the slogan "outperform the 4090 base model." Sprint 3d Cards 4, 5, and 6 shipped the harness skeleton, the locked baseline_v1, and the Track C verifier-guided best-of-8 first pass. Cards 1-5 made the comparisons possible. This doc makes the comparisons legible.

The standing tenet is simple: every win number we claim against the base Qwen3-30B-A3B-Instruct-2507-AWQ-4bit must reproduce from one command, on the same hardware, with the same provider config, against a frozen prompt and a frozen oracle. The bench is the contract.

## 2. Tasks in scope

The harness has six task slots, matching `NEXUS_PATH_TO_OUTPERFORM_v0.1.md` section 1.2. Sprint 3d ships two of them fully wired and four as symmetric stubs so the runner does not branch on per-task availability.

### 2.1 Wired tasks (real metrics)

| Task ID | Family | Primary metric | Oracle | Dataset | Status |
|---|---|---|---|---|---|
| `builder` | 1. Workflow synthesis | `valid_at_1` | Structural sim (default) or n8n MCP `validate_workflow` (when reachable) | `bench/eval/datasets/builder_skeleton_v1.jsonl` (5 problems, placeholder) | Wired in Card 4, oracle hardened in Card 5, best-of-N path added in Card 6 |
| `code_pub` | 5. HumanEval+/MBPP | `pass_at_1` | Subprocess unit-test runner (free oracle) | `bench/eval/datasets/code_pub_skeleton_v1.jsonl` (3 problems, placeholder); HF fetch path available via `NEXUS_BENCH_CODEPUB_SOURCE` | Wired in Card 4, best-of-N path added in Card 6 |

The Builder dataset is currently a 5-example placeholder. The "50-example held-out" target the sprint plan section 4 calls out is a Card 5b n+1 follow-on; the harness, the oracle, and the bootstrap CI machinery are all in place to absorb that expansion without code changes.

### 2.2 Stub tasks (placeholder shape, no real signal)

| Task ID | Family | Primary metric | Why a stub |
|---|---|---|---|
| `routing` | 2. Intent parse + routing | `routing_top1` | Awaiting an intent-labeled dataset; the harness reads stub problems and writes zero per-seed metrics |
| `tool_use` | 3. Agentic tool use | `task_success` | Awaiting a multi-step tool-use eval; same shape as wired tasks so the runner does not branch |
| `rag_qa` | 4. RAG over memory | `answer_correctness` | Awaiting NAS-grounded Q&A pairs; needs the 4070 fabric live (see Card 2/3) |
| `guards` | 6. General-capability regression guards | `guard_score` | Awaiting wiring of MMLU-Pro, GPQA-diamond, IFEval, MT-Bench via lm-evaluation-harness |

Every stub sets `stub_placeholder=True` in `task_meta()`. The runner records it on every `SeedResult` and every `TaskSummary`. Consumers (`baseline_v1.json`, the bench plan, any future dashboard) should render stub tasks as "not yet measured" rather than as "scored zero," because zero on a stub is not the same as zero on a real eval and conflating them was the original sin we are paid to avoid.

### 2.3 Adding a new task

Drop a module under `bench/eval/tasks/your_task.py`, expose `get_task() -> EvalTask`, register the task_id in `bench/eval/tasks/__init__.py::TASK_REGISTRY`. The runner picks it up without further wiring. See section 7 for the contract.

## 3. Methodology

### 3.1 Frozen-base-then-candidates discipline

The baseline arm is locked before any candidate runs. `bench/baselines/pre_registration_v1.md` records the win conditions (proposed: Track C best-of-8 beats baseline_v1 by at least 10 absolute percentage points on Builder `valid@1` with non-overlapping bootstrap 95% CIs across 3 seeds; no more than 3 absolute point drop on any family-6 guard). `bench/baselines/baseline_v1.json` records the actual baseline numbers with full provider snapshot, sampling config, harness version, git SHA, and oracle mode. Any candidate run that wants to claim a win against baseline_v1 must point at this exact JSON and use the same harness version. Re-baselining means a new `baseline_vN.json` and a new pre-registration doc, not an edit to baseline_v1.

### 3.2 Deterministic seeds

Every per-seed result records:

- `sampling.seed` (the integer passed to vLLM)
- `harness_version` (`bench/eval/__init__.py::__version__`)
- `git_sha` (from `git rev-parse HEAD` at run time, or `"unknown"` if the runner is not in a git checkout)
- `provider.kind`, `provider.base_url`, `provider.model`, `provider.extra` (the full ProviderConfig snapshot)
- `task_meta` (dataset id, primary metric, secondary metrics, prompt path, node whitelist for Builder, etc.)
- The full completion text for every problem, plus per-problem prompt and completion token counts and latency

That is what "reproducible" means in practice: any future agent can re-create the exact run from the JSON alone. At temperature 0.0, per-seed outputs are byte-identical given the same vLLM build and the same `seed`. At temperature greater than 0.0 (e.g. the temp 0.8 best-of-N arm), seeds 0, 1, 2 still give reproducible runs against the same vLLM build, but the per-seed metric values vary, which is the whole point of running multiple seeds.

### 3.3 Sample counts and CIs

Default seed count: 3 (per sprint plan section 5). The CLI accepts `--seeds N` for higher counts; the bootstrap CI calculation scales with the sample count. Bootstrap resamples default to 1000 (`--bootstrap-resamples`), which is what the CI numbers in baseline_v1 were computed with. The resampling is deterministic given `bootstrap_seed` (default 0), so two runs of the aggregator over the same per-seed metric lists produce byte-identical CIs.

The bootstrap is over the per-seed mean. When temperature is 0.0 and the per-seed metric values are identical (which is what happens for the deterministic baseline on the current Builder placeholder set), the bootstrap CI collapses to a point. That is honest: with zero variance across seeds, the CI is literally a point. Wider CIs require either a larger held-out dataset, nonzero temperature, or both. The baseline_v1 caveats section records this explicitly so no one reading the JSON later mistakes a degenerate CI for high precision.

### 3.4 Oracles

| Task | Oracle | Notes |
|---|---|---|
| `builder` | `_n8n_oracle.py` (`mcp` mode) or `_structural_exec_sim` (default) | The n8n MCP path is wired and unit-tested; flip via `NEXUS_BENCH_BUILDER_ORACLE=mcp` when the n8n MCP container is up on DREWSPC. baseline_v1 ran on `structural_sim` because the MCP container was offline; baseline_v2 should re-run on `mcp` once it is up |
| `code_pub` | `_run_unit_test` (subprocess, Python `-c`) | Wall-clock timeout per problem (default 8s); no network; the sandbox is not hardened, callers control inputs |
| Stubs | None | Stubs return zeros and set `stub_placeholder=True` |

Oracle choice is recorded in `task_meta` and surfaced in `baseline_v1.json::caveats.oracle`. Any cross-baseline comparison must use the same oracle, or document the swap.

### 3.5 Cost axis (the other half of "outperform")

Quality is one axis. Cost is the other, per `NEXUS_PATH_TO_OUTPERFORM` section 1.1. Every per-seed result carries `aggregate.tokens_prompt_total`, `aggregate.tokens_completion_total`, `aggregate.latency_p50_s`, `aggregate.latency_p95_s`. A candidate that ties on quality but cuts p95 latency by 4x is a win even at quality parity: it frees the 4090 cortex hot path. The baseline_v1 JSON records the headline cost numbers per task; comparison reports should always carry both axes.

## 4. Baseline vs Track C comparison framework

### 4.1 The two arms

| Arm | Sampling | Selection | Where it lives |
|---|---|---|---|
| Baseline (greedy) | temperature 0.0, n=1 | Score the single completion | `BenchRunner.run_task` in `bench/eval/runner.py` |
| Track C (best-of-N) | temperature 0.8, n=8 (configurable via `--best-of-n`) | Score every candidate with the task's free oracle; pick the first candidate with primary metric == 1.0, or the highest-scoring | `BestOfNRunner` in `bench/eval/bestofn.py` (added in Card 6) |

Both arms call the same task module (`bench/eval/tasks/builder.py` or `code_pub.py`). The task's `score()` method is the verifier. There is no separate verifier code path for best-of-N: the same function that scores the baseline scores each best-of-N candidate. That is intentional: it eliminates an entire class of "the best-of-N verifier scored differently than the baseline verifier" bugs.

### 4.2 The comparison artifact

Each Card 6 best-of-N run writes, alongside the standard per-seed and per-task JSONs:

- `<run_label>_<task_id>_bestofn.json` per seed: full per-candidate scores, the picked-candidate index, the per-candidate completion tokens and latency, the per-stage oracle failure breakdown
- `<run_label>_<task_id>_comparison.json` per task: baseline_arm vs bestofn_arm primary metric mean, bootstrap CI, lift in absolute percentage points, lift CI, cost multiplier
- `<run_label>_<task_id>_comparison.svg` per task: a 2-bar chart with CIs and the lift annotation. SVG so the diff is reviewable in a PR

The chart is the headline. The JSON is the audit trail. Both are committed under `bench/results/<run_label>/`. The naming convention is the same as the rest of the harness: run_label first, task_id second, artifact kind third.

### 4.3 Win condition (the bar Tracks A/B must clear)

Per `bench/baselines/pre_registration_v1.md`:

- Track C wins if best-of-8 verifier-picked `valid@1` exceeds base-greedy `valid@1` by at least 10 absolute percentage points with non-overlapping bootstrap 95% CIs over at least 3 seeds.
- No more than 3 absolute point drop on any family-6 guard (MMLU-Pro, GPQA-diamond, IFEval, MT-Bench). This is the regression tolerance; family-6 is currently stubbed but the tolerance is recorded so it bites the moment the guards land.
- A candidate that matches base quality but cuts p95 latency by 4x and frees the 4090 is also a win even at quality parity. The cost-axis bar is qualitative for now; quantifying it is a follow-on.

Drew is the sign-off on the win condition. The pre-registration is the contract; agents do not move the goalposts post hoc.

## 5. How to re-run baseline_v1

```powershell
# From C:\dev\project-nexus
$env:NEXUS_BENCH_BASE_URL = "http://localhost:8000/v1"
$env:NEXUS_BENCH_MODEL    = "cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit"
# Optional: flip the Builder oracle on once n8n MCP is up
# $env:NEXUS_BENCH_BUILDER_ORACLE = "mcp"

python -m bench.eval --task builder  --seeds 3 --label baseline_v1
python -m bench.eval --task code_pub --seeds 3 --label baseline_v1
python bench\baselines\build_baseline_v1.py  # aggregates the per-task summaries
```

Output lands under `bench/results/` (per-task) and `bench/baselines/baseline_v1.json` (aggregated). If the resulting JSON does not match the committed `bench/baselines/baseline_v1.json` byte-for-byte, the discrepancy is either a vLLM build difference, a model snapshot difference, or an oracle-mode difference. Diff the `provider` and `caveats` blocks first.

## 6. How to run the Track C best-of-8 arm

```powershell
cd C:\dev\project-nexus
$env:NEXUS_BENCH_BASE_URL = "http://localhost:8000/v1"
$env:NEXUS_BENCH_MODEL    = "cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit"

python -m bench.eval `
  --task code_pub `
  --seeds 3 `
  --best-of-n 8 `
  --bestofn-temperature 0.8 `
  --label trackc_bo8_v1

python -m bench.eval `
  --task builder `
  --seeds 3 `
  --best-of-n 8 `
  --bestofn-temperature 0.8 `
  --label trackc_bo8_v1
```

The CLI runs both arms in one invocation (baseline then best-of-N) and writes the comparison artifact at the end. To skip the baseline arm and only run best-of-N (for example, when you already have a frozen baseline_v1 and just want to add a new candidate), pass `--skip-baseline-arm`.

## 7. Extending the harness

### 7.1 Add a new task family

1. Implement the task module under `bench/eval/tasks/your_task.py` as a subclass of `bench.eval.base.EvalTaskBase`. Implement `load_problems`, `build_prompt`, `score`. Set `task_id`, `primary_metric`, `dataset_id`. If you are landing it as a stub, set `stub_placeholder = True` and return zero metrics; the runner handles the rest.
2. Drop a frozen dataset under `bench/eval/datasets/your_task_v1.jsonl`. JSONL is the rule; each line has `problem_id`, `prompt`, and a `reference` block whose schema is whatever your scorer needs.
3. Drop a frozen prompt template under `bench/eval/prompts/your_task.txt`. The template uses `{spec}` or `{prompt}` placeholders; the task module substitutes them.
4. Register the factory in `bench/eval/tasks/__init__.py::TASK_REGISTRY`.
5. Write `tests/bench_eval/test_task_your_task.py` using `StubProvider`. The suite enforces: scorer is deterministic given a fixed problem and completion; the task aggregates to the documented primary metric; the runner can drive it end-to-end with the stub provider.

### 7.2 Add a new oracle

If the task needs an oracle that talks to an external service (n8n MCP, a sandbox runtime, a docker container), add a `_your_oracle.py` module alongside the task and a `NEXUS_BENCH_<TASK>_ORACLE` env var so the choice is runtime-selectable and recorded in `task_meta`. Always ship a structural fallback that runs in the offline test suite. The `_n8n_oracle.py` module is the worked example.

### 7.3 Add a new provider

Subclass `bench.eval.provider.LLMProvider`, implement `complete()`, register it in `PROVIDER_REGISTRY` at the bottom of `provider.py`. The CLI picks it up via `--provider <kind>`. The runner does not care; it only ever calls `complete(prompt, sampling)`. Adding a non-OpenAI-shape provider (Anthropic, Cohere, vLLM-native) is a 50-line addition.

### 7.4 Add a new comparison arm

Best-of-N is the first non-baseline arm. Future arms (Track B routing adapter, Track A 4B specialist) drop in alongside `BestOfNRunner` in `bench/eval/bestofn.py` or as siblings under `bench/eval/`. The invariant is: each arm consumes the same `EvalTask` interface and writes a `<run_label>_<task_id>_<arm>.json` whose `primary_metric` is comparable to the baseline arm's. The comparison module reads any two arms and emits the chart.

## 8. What this doc does NOT cover

- Sprint 4 (the bidirectional callback fabric). The benchmark currently treats the cortex as a black box `/v1/chat/completions` endpoint. When Sprint 4 Chunk B lands, the brainstem-mediated arm becomes a fourth comparable arm; the harness already supports it via `--base-url`.
- LoRA training, full-parameter fine-tuning, distillation. Track B and Track A produce new model snapshots; the bench runs against whichever model `--model` points at. Training pipelines live outside `bench/eval/`.
- The 4070 fabric bring-up. Cards 2 and 3 cover that. The bench can run against the 4090 cortex alone, which is what every Sprint 3d run did.
- The dataset expansion to 50 examples on Builder. Tracked as Card 5b. The harness, oracle, CIs, and the comparison artifact all scale to 50 without code changes; the work is dataset curation, not bench wiring.

## 9. Sources

- `docs/sprints/SPRINT_3d_PLAN_2026-06-18.md` (sprint of record)
- `NEXUS_PATH_TO_OUTPERFORM_v0.1.md` (the inference-quality program; the bench is its instrument)
- `bench/baselines/pre_registration_v1.md` (the locked win conditions, on `sprint-3d/card-5-baseline-v1`)
- `bench/baselines/baseline_v1.json` (the frozen baseline numbers, on `sprint-3d/card-5-baseline-v1`)
- `bench/eval/base.py` (the result schema)
- `bench/eval/runner.py` (the baseline arm)
- `bench/eval/bestofn.py` (the Track C arm, added in Card 6)
- `bench/eval/provider.py` (the BYO-LLM adapter)
- `bench/eval/tasks/` (one module per task family)
- `bench/eval/tasks/_n8n_oracle.py` (the worked-example oracle, on `sprint-3d/card-5-baseline-v1`)
