# Sprint 3d: Plan of Record

Date: 2026-06-18
Author: Sprint 3d kickoff agent (Opus), under Drew's direction post-retro
Trigger: 2026-06-18 retro Move 4 ("decide project-nexus this sprint or formally pause"). Drew decided continue. This is the execution plan.
Source-of-truth branch: `sprint/3d-stabilize-2026-06-18` (5 commits ahead of main, contains the Sprint 3d test suite, manual test plan, 2026-05-17 handoff, Sprint 4 design, and the rigor+ambition experiment-candidate pair). Plus the standalone `track-c/builder-best-of-n-eval` branch (1 commit, the best-of-8 harness).

## 1. Sprint goal (one sentence)

Stand the Nexus fabric back up end-to-end (brainstem + NAS + embedder on the 4070, cortex on the 4090), close the Sprint 3d validation loop that has been open since 2026-05-17, and land a verifier-guided best-of-N first pass on the Builder eval so we have a pre-registered, reproducible bar to outperform.

This sprint is specifically NOT a Sprint 4 sprint. The bidirectional callback design (`docs/sprint_4_bidirectional_callback.md`) ships in this sprint as committed-and-reviewed design, with Chunk A and Chunk B queued as the next two cards that get dispatched once Drew greenlights. Treating Sprint 4 as in-scope here is how Sprint 3d stalled the first time.

## 2. Ground truth as of 2026-06-18 (live, not audited)

Verified at plan-write time:
- 4090 (DREWSPC) cortex: LIVE. vLLM serving `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`, OpenAI-compatible on :8000, `max_model_len=8192`, idle.
- 4070 (BROOKFIELD) host: LAN-reachable (192.168.1.251 pings). Tailscale: OFFLINE (100.89.210.52 does not respond). Brainstem + NAS + embedder containers: not running.
- main branch: contains all of Sprint 3a/3b/3c. `foundation/consolidation` is fully merged in. The 2026-06-16 state audit's "21 commits ahead" is stale.
- Sprint 3d work: committed on `sprint/3d-stabilize-2026-06-18` as of today, awaiting PR + merge.
- Track C best-of-8 harness: committed on `track-c/builder-best-of-n-eval` as `645e0c4`, 1 commit ahead of main, never run end-to-end.
- bench/eval/: does not exist. `scripts/benchmark_inference.py` is still zero bytes per NEXUS_PATH_TO_OUTPERFORM section 0.4.

## 3. Cards (the 5 to 8 work units that ship this sprint)

Each card carries: owner-model (which model class executes), dependencies (which other cards or external state must be true), acceptance criteria (how we know it landed), and conflict surface (a rough estimate of how many other in-flight things this card collides with on disk or in shared services). Hardware requirements are called out per card; only the cards explicitly tagged 4070 are blocked on the BROOKFIELD-Tailscale fix.

### Card 1: Land the Sprint 3d stabilization PR and the Track C best-of-8 PR

- Owner-model: Haiku or Sonnet for the PR mechanics; Drew reviews.
- Dependencies: none.
- Hardware: none (git ops).
- Acceptance: `sprint/3d-stabilize-2026-06-18` opened as PR against main, CI green, merged. Separately, `track-c/builder-best-of-n-eval` opened as its own PR against main, reviewed, and either merged or held with explicit reason.
- Conflict surface: minimal. Both branches are additive (new files only, no edits to existing source). Track-c rebases cleanly onto main since none of its content overlaps with the 5 stabilization commits.
- Why first: the rest of the sprint references files that should be on main, not on feature branches.

### Card 2: Bring the 4070 fabric back online (LAN path first, Tailscale path second)

- Owner-model: Sonnet for the docker-compose + .env + script work; Drew or a runner agent for the actual host-side bring-up since the 4070 is intermittently available.
- Dependencies: Card 1 merged so the docker config and refresh-tailscale-bind.ps1 are on main.
- Hardware: 4070 BROOKFIELD. LAN path requires only that the host is powered (verified). Tailscale path requires `tailscale up` on the 4070 host (currently failing per ping).
- Acceptance: `docker compose up -d` brings brainstem (:5001) + nas (:5002) + embedder online on the 4070. `/health` returns 200 on LAN. Separately, Tailscale reachability restored, `/health` returns 200 over Tailscale at `http://100.89.210.52:5001`. If the Tailscale half cannot be fixed this sprint, the LAN half still ships and the Tailscale piece becomes its own card.
- Conflict surface: low. Touches the 4070 only. The 4090 cortex is unaffected.

### Card 3: Run the Sprint 3d manual integration test plan against the live fabric

- Owner-model: Drew runs the human-checklist sections (A laptop, B phone, C CLI, F cross-device). A Sonnet agent runs the automated pytest piece and transcribes results.
- Dependencies: Card 2 (fabric up). Tailscale path needed for Section B phone and full Section F; LAN-only path is OK for A, C, D, E, G.
- Hardware: 4070 (fabric host) plus a laptop and a phone for the client-side sections.
- Acceptance: every checkbox in `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` Section "Manual test plan completion checklist" either ticked or marked intentionally-skipped with reason. `pytest tests/integration/` run from the 4070 host with the result transcribed into the handoff. Live-smoke subset run with `NEXUS_LIVE_URL` and `NEXUS_LIVE_TOKEN` set.
- Conflict surface: medium. The fabric is shared state; any other Nexus work in flight reads from or writes to the same brainstem and same Chroma store. Schedule serially with Card 5/6/7.

### Card 4: Build the bench/eval/ harness skeleton (tasks 1 and 5 first)

- Owner-model: Opus for the design, Sonnet for the wiring.
- Dependencies: Card 1 merged. Independent of Cards 2/3 (the harness can develop against a mocked cortex; live-fabric runs come later).
- Hardware: developer-machine only for skeleton work; 4090 needed only for the baseline run.
- Acceptance: `bench/eval/` exists with the structure NEXUS_PATH_TO_OUTPERFORM section 1.2 specifies. Task 1 (Builder workflow synthesis, `valid@1` and exec-success) is fully wired with a dataset stub, scorer, prompt template, and `runs.yaml`. Task 5 (HumanEval+/MBPP via lm-evaluation-harness) wired and runnable. Tasks 2/3/4/6 are stubbed with TODO and a one-sentence design note each. Bootstrap CI utility implemented and unit-tested.
- Conflict surface: low. New directory tree, new dependency on lm-eval-harness (pinned). No edits to existing brainstem or NAS code.

### Card 5: Run baseline_v1 on the 4090 base model and pre-register the win condition

- Owner-model: Opus for the pre-registration design, Sonnet for the run.
- Dependencies: Card 4 (harness exists), Card 2 (helpful but not required if the cortex is talked to directly on :8000; the brainstem is not in the baseline arm).
- Hardware: 4090 only for the actual run. Cortex is already live.
- Acceptance: `bench/eval/baseline_v1.json` committed, containing for tasks 1 and 5: p50 score, bootstrap 95% CI, vLLM serving config (including version SHA), sampling params (temp/top_p/seeds), prompt template hash, hardware (GPU, VRAM, RAM), and cost-axis numbers (tokens/sec, p50/p95 latency, peak VRAM). Separately, `bench/eval/pre_registration.md` committed and signed-off by Drew before any candidate is run, specifying the win-condition tolerance (proposed: candidate beats baseline_v1 with non-overlapping CIs on at least one of task families 1-4, ties-or-beats on the rest, regresses no more than 3 absolute points on task family 6 guards).
- Conflict surface: low. Read-only against the cortex. Writes only to `bench/eval/`.

### Card 6: Track C MVE: verifier-guided best-of-8 on 50-example held-out Builder set

- Owner-model: Sonnet for the run; Opus for the analysis.
- Dependencies: Cards 4 and 5. The harness needs to exist; the baseline needs to be locked first so we are measuring lift over a frozen bar, not a moving one.
- Hardware: 4090 only. Brainstem-independent.
- Acceptance: `bench/eval/runs/track_c_bo8_2026-06-XX/` committed with the 8 samples per spec, the verifier output per sample, the chosen sample per spec, the per-spec valid@1 of base-greedy vs best-of-8-verifier-picked, and the aggregate delta with bootstrap CI. A short writeup (`docs/experiments/results/track-c-mve.md`) reporting whether test-time compute alone clears the bar, and if so by how much. This number is the new bar Tracks A/B must beat.
- Conflict surface: low. The Track C harness commit (`645e0c4`) is already on the track-c branch; this card is "actually run it and write up the result," not "build it from scratch." If Card 1 merged the track-c PR, this card becomes a pure runtime exercise.

### Card 7: Sprint 4 Chunk A (brainstem-side /fabric/callback contract + unit tests)

- Owner-model: Sonnet for the implementation, Opus for review against the design doc.
- Dependencies: Drew explicit approval of `docs/sprint_4_bidirectional_callback.md` section 12 open questions (tool surface, callback budget default, service-token kind, endpoint name, memory write transcript visibility, benchmark scope, cross-validation provision). Without approval this card does not start.
- Hardware: developer-machine for build and test (in-process FakeCortex). 4070 not required for chunk A.
- Acceptance: `POST /fabric/callback` endpoint exists on brainstem with the Section 4.2 contract, service-token auth class enforced (user tokens get 403 wrong_token_kind), argument validation (Section 5 schema), budget enforcement (N=3, 2048-tok soft cap, 5s timeout), and the four error codes (callback_budget_exhausted, callback_invalid_arguments, embedder_unavailable, callback_timeout). Unit tests cover all four error paths plus the happy path, all green. The in-process tool-execution path wraps `embedder.memory_query` with the richer arguments per Section 5. No real vLLM in the loop yet; that is Chunk B.
- Conflict surface: medium. Adds a new endpoint to `nodes/brainstem_4070/server.py` plus changes to `auth_middleware.py` to add the kind field. Coordinate with Card 3 (manual test plan run) and Card 2 (fabric up) so the brainstem is in a known state when the new code drops.

### Card 8: Bench plan write-up plus the "outperform 4090 base model" methodology doc

- Owner-model: Opus.
- Dependencies: Cards 4, 5, 6 inform the writeup. Can draft in parallel and finalize after Card 6 produces the Track C number.
- Hardware: none.
- Acceptance: `docs/bench/BENCH_PLAN_2026-06-XX.md` committed, covering: how we measure "outperform" on the quality axis and the cost axis (per NEXUS_PATH_TO_OUTPERFORM section 1.1), the 6 task families (per section 1.2) with the headline signal called out (Builder `valid@1`), the pre-registration discipline (per section 2), the three tracks and their MVE order (C then B then A, per section 3.4), the 30-day decision-point cadence (per section 6), and the explicit Phase-0-vs-Phase-1 separation that lets the model-quality program run on a single 4090 without waiting for Sprint 4 or for 4070 Tailscale recovery. This is the document that turns "we will beat the base model" from a slogan into a falsifiable program.
- Conflict surface: low. Pure docs.

## 4. The Track C verifier-guided best-of-N first pass (one-paragraph rationale)

The Track C MVE per NEXUS_PATH_TO_OUTPERFORM section 3 is: sample N=8 candidate workflows from the base Qwen3-30B at temp=0.8, run each through the free programmatic verifier (parse, node whitelist, n8n `validate_workflow`), return the first that passes or the highest-scoring. Compared to base-greedy `valid@1` on a 50-example held-out Builder set, this converts the verifier the system already has into a quality multiplier with zero training. Expected lift is the cheapest, highest-probability win in the whole program. Cards 4 through 6 land it. The number it produces becomes the bar everything else (Track B adapters, Track A distillation) must clear, which is why we want it locked before any GPU-hour is spent on training.

## 5. Bench plan: how we measure "outperform 4090 base model"

Headline metric: Builder `valid@1` and exec-success on a 50-example held-out set. This is task family 1 in NEXUS_PATH_TO_OUTPERFORM section 1.2, chosen because it is the Cortex's self-extension capability, it has a free oracle verifier (no LLM-judge ambiguity), and it is precisely the narrow structured task where specialization plus verifier-guided sampling can plausibly beat a 30B-A3B MoE.

Methodology in one paragraph: freeze the base model and serving config, run the harness with >=3 seeds per stochastic task, record quality (with bootstrap 95% CI) and cost (tokens/sec, p50/p95 latency, peak VRAM) into `bench/eval/baseline_v1.json`, pre-register the win condition before running any candidate, then evaluate each candidate (Track C best-of-8, Track B routing adapter, Track A 4B specialist) against the locked baseline with the same harness. A candidate wins if its CI does not overlap the baseline's on at least one of task families 1 to 4, ties-or-beats on the rest, and regresses no more than the pre-registered tolerance on family 6 guards (MMLU-Pro, GPQA-diamond, IFEval, MT-Bench).

Bar in numbers (proposed, to be confirmed by Drew in Card 5):
- Track C win condition: best-of-8 verifier-picked `valid@1` exceeds base-greedy `valid@1` by at least 10 absolute percentage points with non-overlapping bootstrap CIs across 3 seeds.
- General-capability regression tolerance: no more than 3 absolute point drop on any of the four family-6 guards.

The cost axis matters separately: a candidate that matches base quality but cuts p95 latency by 4x and frees the 4090 is a win even at quality parity, because it moves the hot path off the dependable cortex. This is the practical win shape NEXUS_PATH_TO_OUTPERFORM section 1.1 spells out.

## 6. Hardware status and which cards need what

| Hardware | Status | Cards that require it |
|---|---|---|
| 4090 (DREWSPC) cortex on :8000 | LIVE, idle | 5, 6, 7 (Chunk B if/when it ships), 8 (read-only refs) |
| 4070 (BROOKFIELD) LAN (192.168.1.251) | LAN-reachable | 2, 3 (full automated suite and Sections A/C/D/E/G), 7 (none directly, but the Chunk B card following 7 will) |
| 4070 (BROOKFIELD) Tailscale (100.89.210.52) | OFFLINE | 3 Section B (phone over Tailscale), 3 Section F (cross-device), the off-LAN visible-win demo |
| Developer machine (any) | n/a | 1, 4 skeleton work, 7 unit tests, 8 |
| Phone, laptop | n/a | 3 Section B (phone needs Tailscale), Section A (laptop, LAN or Tailscale) |

The Tailscale fix on the 4070 is a hard prerequisite for the off-LAN visible-win demo, which is the Sprint 3d done-criterion the manual test plan was originally written around. If it cannot be fixed this sprint, Section B is the only piece that gets deferred; Sprint 3d still closes on the LAN-only acceptance with a documented Tailscale-recovery card carved out.

## 7. Sequencing (what unblocks what)

```
Card 1 (PRs land) ───┬─────► Card 4 (bench/eval/ skeleton)
                     │
                     ├─────► Card 2 (4070 fabric up) ───► Card 3 (manual test plan run)
                     │
                     └─────► (Card 5 can start once Card 4 lands)

Card 4 ──► Card 5 (baseline_v1 + pre-registration) ──► Card 6 (Track C MVE run + writeup)

Card 6 ──► Card 8 (bench plan doc finalized)

Card 7 (Sprint 4 Chunk A) is GATED on Drew approving the Section-12 open questions
        in docs/sprint_4_bidirectional_callback.md. Independent of Cards 2/3/4/5/6
        but must coordinate with Card 3's fabric state.
```

Critical path is 1 -> 4 -> 5 -> 6 -> 8 (the bench arc) plus the parallel 1 -> 2 -> 3 (the fabric-up arc). Card 7 is a side branch waiting on a decision.

## 8. Open questions for Drew (load-bearing decisions the agent cannot make)

1. **Approve the Sprint 4 design doc Section 12 open questions** (tool surface, callback budget default, service-token kind, endpoint name, memory write transcript visibility, benchmark scope, cross-validation provision). Card 7 cannot start without this. Read `docs/sprint_4_bidirectional_callback.md` Section 12 once it lands on main from the stabilization PR.
2. **Pre-register the win condition for Track C.** Proposed in Section 5 above: 10 absolute pp lift on Builder valid@1, non-overlapping CIs, 3 seeds. Drew can override the 10pp number, the seed count, or the family-6 tolerance before Card 5 commits the pre-registration.
3. **4070 Tailscale recovery: in scope this sprint or carved out?** If in scope, Card 2 expands to include the Tailscale fix. If carved out, Sprint 3d closes on LAN-only validation and a separate "restore 4070 Tailscale" card joins the queue.
4. **Track C PR (`track-c/builder-best-of-n-eval`): merge it as-is on top of main, or rebase first?** It is 1 commit ahead, 5 behind main since the stabilization PR will move main forward. Recommendation: rebase cleanly onto post-stabilization main, then merge.
5. **Card execution order vs parallelism.** The critical path is sequenced; Cards 4 and 2 can run in parallel after Card 1, and Card 7 can run in parallel with anything (after design approval). Drew picks how aggressive the parallel dispatch is.
6. **Vector consolidation freeze still binding?** CLAUDE.md says yes. No Nexus card touches project-vector. Flagging in case the situation changed.

## 9. What this sprint deliberately does NOT do

- Sprint 4 implementation (Chunks B, C, D). Chunk A is queued as Card 7 only because it is the smallest unit of forward progress that does not require live cortex tool-calling validation. The actual fabric-differentiator work waits.
- Track B (LoRA adapter) and Track A (4B distillation). Both are NEXUS_PATH_TO_OUTPERFORM Weeks 2 and 3; Sprint 3d is Week 1.
- Any LoRA training, full-parameter fine-tuning, or new model serving. The 4090 stays on the AWQ base, the 4070 stays on the brainstem + NAS + embedder set.
- Anything touching project-vector (CLAUDE.md consolidation freeze).
- Any cleanup of the broader C:\dev tree (the "polis" branch recovery on the five frontend repos, the agile-cards-board v2/v3 stalls, the on-disk archive cleanup) per the 2026-06-18 retro Moves 1, 2, 3. Those are separate sprints.

## 10. Definition of done

Sprint 3d closes when:
- Card 1 PRs are merged.
- Card 2 brainstem + NAS + embedder are LIVE on the 4070 (LAN at minimum; Tailscale if Card 3 expansion or open question 3 covers it).
- Card 3 manual test plan checklist is filled in (no boxes left unchecked-and-unmarked).
- Card 4 bench/eval/ harness exists with Tasks 1 and 5 wired.
- Card 5 baseline_v1.json + pre_registration.md are on main, signed off.
- Card 6 Track C MVE result is on main with the writeup.
- Card 8 bench plan doc is on main.
- Card 7 is OPTIONAL within this sprint and only counts toward done if Drew approves the Sprint 4 design and it ships clean.

Sprint review writeup goes in `docs/sprints/SPRINT_3d_REVIEW_2026-06-XX.md` on the closing day, mirroring the rigor of the 2026-05-17 handoff.

---

Sources: `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` (the original Sprint 3d intent), `docs/sprint_4_bidirectional_callback.md` (Sprint 4 design and open questions), `C:\dev\NEXUS_PATH_TO_OUTPERFORM_v0.1.md` (the inference-quality program), `C:\dev\NEXUS_STATE_AUDIT_2026-06-16.md` (state baseline, updated against live 2026-06-18 ground truth), `C:\dev\_retros\RETRO_2026-06-18.md` Move 4 (the trigger for this sprint), the two experiment-candidate docs now on `sprint/3d-stabilize-2026-06-18`.
