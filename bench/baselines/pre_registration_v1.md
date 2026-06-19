# Card 5 baseline_v1 pre-registration

**Pre-registered:** 2026-06-19, before any baseline_v1 run.
**Author:** Drew (greenlit), executed by Card 5 Baseline Runner.
**Branch:** `sprint-3d/card-5-baseline-v1`.
**Companion artifact (post-run):** `bench/baselines/baseline_v1.json`.

The point of pre-registration is to make the difference between a baseline and an excuse a written artifact. If we later change the success criteria or the dataset to make a result land where we wanted, the diff against this file calls it out.

## 1. Endpoint and model

- Provider: OpenAI-compatible chat completions, BYO-LLM.
- Endpoint: `http://localhost:8000/v1` on DREWSPC (the 4090 cortex), bound to the loopback inside Drew's LAN.
- Model id sent on the wire: `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` (vLLM-served AWQ 4-bit Qwen3-30B-A3B-Instruct-2507).
- Sampling: temperature 0.0, top_p 1.0, max_tokens 2048, seed varied per run.
- No FMD gov endpoint. No cloud provider. No fine-tuning or training in scope.

## 2. Tasks and datasets

We run two tasks for baseline_v1:

- **Task 1 Builder** (`builder`). Dataset: `bench/eval/datasets/builder_skeleton_v1.jsonl`, **5 examples**. Headline metric `valid_at_1`. Secondary `exec_success`.
- **Task 5 Code public** (`code_pub`). Dataset: `bench/eval/datasets/code_pub_skeleton_v1.jsonl`, **3 examples**. Headline metric `pass_at_1`.

Stubs Tasks 2, 3, 4, 6 (`routing`, `tool_use`, `rag_qa`, `guards`) carry `stub_placeholder=True` and emit zero metrics. They are reported as "not yet measured" rather than "scored zero" and do not contribute to baseline numbers.

### 2.1 Held-out set caveat (loud)

The 5-example Builder dataset is the placeholder shipped with the Card 4 skeleton. It is statistically thin: a single bad sample swings the mean by 20 percentage points, and the bootstrap CIs over 3 seeds will be wide. Drew has explicitly acknowledged this and is buying the rig + a baseline number now. Expanding the held-out set to the 50-example curated target is the n+1 follow-on (`Card 5b: expand Builder held-out to 50`), to be cut as a separate PR. Do not draw policy conclusions from this baseline beyond "the rig works and the model is in this neighborhood."

## 3. Seeds and CI

- Seeds: 3, integer-valued `[0, 1, 2]`.
- Bootstrap: 1000 resamples per metric on the per-seed scalars, 2.5/97.5 percentile cut for the 95% CI.
- Reproducibility: every per-seed JSON records `git_sha`, `harness_version`, `provider.config`, `sampling`, and `task_meta`. Card 5 readers can re-derive the run end-to-end.

## 4. Oracle for Builder `exec_success`

Decision 3 in Drew's brief: the n8n MCP `validate_workflow` is the canonical oracle and replaces the structural reachability simulator at `bench/eval/tasks/builder.py:_structural_exec_sim`. Contract is fixed by the n8n MCP source at `Nexus_N8N-MCP/src/mcp/tools.ts`:

- Tool name `validate_workflow`.
- Input: `{ workflow: <n8n JSON>, options: { validateNodes, validateConnections, validateExpressions, profile } }`. We will pass `profile: "runtime"`.
- Output: `{ valid: bool, summary: {...}, errors: [...], warnings: [...] }`. `exec_success = 1.0 iff response.valid is True`.
- Reachability check on the bench runner host: HTTP MCP at `http://localhost:3000` (per `Nexus_N8N-MCP/N8N_HTTP_STREAMABLE_SETUP.md`).

**State on 2026-06-19 at run time:** n8n MCP container not running on DREWSPC. Probe returned `Unable to connect to the remote server` on `:3000/health` and `:5678/`. Bench will therefore use the structural reachability simulator as the active oracle for this baseline. The n8n MCP wire-up ships in the same PR, gated by reachability probe at task construction; the next baseline (`baseline_v2`) will re-run with the MCP up and report the delta.

This is called out in the headline `baseline_v1.json` under `meta.oracle = "structural_sim"` and in the PR body.

## 5. Win condition / tolerance (the prediction)

Per Drew's locked decisions:

- Builder `valid_at_1`: a "win" against this baseline requires a **+10 absolute percentage points** lift, with non-overlapping 95% CIs over 3 seeds.
- Family 6 tolerance (the guards stub family): +3 absolute points once that task is wired. Not measured in baseline_v1.
- Code public `pass_at_1`: no formal tolerance pre-set; we report mean and CI as a cross-task sanity signal. A nontrivial >=10 pp regression vs baseline_v1 on a future change is a rollback trigger.

### 5.1 Commit prediction (pre-run, before seeing numbers)

This is the bet. Anchored on (a) Qwen3-30B-A3B-Instruct-2507's reported HumanEval+/MBPP performance, (b) the 5-example Builder set being narrow and well-specified, (c) the validator chain being deterministic and the prompt being explicit about the fence and the whitelist.

- Builder `valid_at_1`: **0.50 to 0.80** mean across seeds. Wide CI expected (>=0.20 wide) because n=5. Most-likely failure mode: model emits valid JSON but the wrong `type` enum (e.g. "httpRequest" instead of "http"), or omits a `required_node`.
- Builder `exec_success`: roughly equal to `valid_at_1` minus 0.0 to 0.2. The structural sim is permissive (single source, all reachable); validator already catches most structural junk.
- Code public `pass_at_1`: **0.33 to 1.00** mean across seeds (n=3 makes this nearly binary per seed).

If `valid_at_1` lands below 0.20, that is a signal the prompt or the dataset has a defect; investigate before claiming the baseline. If `valid_at_1` lands at 1.00 across all seeds, that is a signal the dataset is too easy; flag for the 50-example expansion.

## 6. Stopping rules

- Run the 3 seeds. Do not retry seeds that fail provider calls (the runner records per-problem `error` and counts as zero, which is the honest outcome).
- If the cortex returns nonzero error rate > 30% across all problems on any seed, abort the baseline and treat it as an infra failure; do not commit `baseline_v1.json`.
- No post-hoc seed selection. If we want to look at a 4th seed, that becomes `baseline_v1b` with its own pre-reg note.

## 7. What changes after baseline_v1 lands

- Card 5b: expand Builder held-out to 50 curated examples; re-run as `baseline_v2`.
- Card 6: Track C verifier-guided best-of-8 MVE measured against `baseline_v1` as the comparison anchor.
- Card 8: bench plan write-up, with this pre-registration as appendix.

## 8. Hash-lock note

This file is committed BEFORE any baseline_v1 result file. The PR diff timestamp shows pre-reg writes precede the result writes. Anyone reviewing the PR can verify in `git log` that `pre_registration_v1.md` is in an earlier commit than `baseline_v1.json`.
