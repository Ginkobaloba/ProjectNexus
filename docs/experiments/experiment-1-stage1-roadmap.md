# Experiment 1: Stage 1 Roadmap

Status: v1.0, 2026-05-15
Companion to: experiment-1-pipeline-characterization.md, experiment-1-sprint-plan.md (Stage 0)

## How this was produced

Two-Opus triangulation. A consultant Opus drafted the strategic 6-month roadmap. A second Opus pressure-tested that draft and added execution depth, catching several optimistic assumptions. This document is the execution-ready synthesis. The single most important catch from the pressure-test: Stage 0 is not yet complete. Sprints 2 through 5 of Stage 0 are still open, and they are hard dependencies for Stage 1. Stage 1 does not begin until Stage 0's release tag exists.

## Framing

Stage 0 proved the fabric exists. Stage 1 proves the fabric matters: that the fabric-augmented system demonstrably outperforms bare Qwen3-30B, or learns rigorously why it cannot. Roughly six months of sprint groups, scoped at the ambition level of what a competent 3-person team would have taken on over six months before AI agents existed. Sequencing philosophy: front-load the measurement and baseline regime, because without it every later capability claim is unfalsifiable.

Entry gate: Stage 1 does not start until Stage 0 Sprint 5 produces its release tag and reproducibility manifest. If Stage 0 slips, every Stage 1 date slips with it. Build the Stage 0 handoff so its release tag is the literal entry gate.

## Sprint Group A (months 1 to 1.5): Baseline and characterization

Stage 0 dependencies: the metric harness and live dashboard (Sprint 5), persistent memory operational (Sprint 2), the reproducibility manifest (Sprint 5). The Stage 0 finding that latency is essentially all Cortex inference round trip is the starting hypothesis, not a settled fact: it was measured on the stub path with no memory retrieval in the loop.

Work items. Stand up an eval runner that executes the frozen workload against any named topology arm and writes results into the same metric store the dashboard reads, so characterization data and live telemetry share a schema. Define topology arms as runnable configs: A0 bare Cortex single node, A1 two-node with memory retrieve-before-generate, A2 two-node with memory plus callback enabled, A1-cold with an empty memory store to separate retrieval value from warm-cache value. Run each arm with enough samples to get variance, not just a mean, because the thesis test in Group D lives or dies on effect sizes and the noise floor must be known now. Produce latency budgets broken down by stage (orchestration, embed, retrieve, Cortex round trip, callback) so the "it is all Cortex" claim is confirmed or corrected with memory in the loop. Add 4070 load profiling under combined load (see the decisions section).

Done-criteria. The benchmark workload is committed as a versioned, hashed artifact with a fixed prompt set and a deterministic scoring script. The bare-base-model quality baseline is recorded with per-item scores, not just an aggregate, so Group D can do paired comparisons. Variance is characterized: the minimum detectable effect size given the sample count can be stated.

## Sprint Group B (months 1.5 to 3): Thalamus becomes real, callback becomes a workhorse

Stage 0 dependencies: the callback from Sprint 4, Thalamus existing as a stub with direct-forwarding, Cortex-down behavior from the folded gap work.

Work items. Replace the direct-forwarding stub with a real routing decision. Define the decision policy as an explicit, versioned document before writing code: the input features Thalamus sees, the output actions (answer cheap, retrieve then answer, invoke callback, escalate), and the fallback when Thalamus itself is slow or wrong. Instrument every routing decision with a logged rationale. Harden the callback first: explicit timeouts, a defined Cortex-down path, a defined callback-failed path, and a soak test exercising all of them. Sequencing correction from the pressure-test: callback hardening must finish before Thalamus routing builds on top of it, because Thalamus's escalate action depends on a reliable callback. They are not independent parallel tracks.

Done-criteria. A/B numbers against the Stage 0 stub on both the frozen workload and the memory-dependent domain set from Group A. A documented decision policy with a version number. Callback reliability stated as a number (failure rate under soak, recovery time). A regression check: Thalamus must not make the general-eval arm slower than the stub beyond a stated threshold.

## Sprint Group C (months 3 to 4.5): Edge perception

This is the canary and the highest-risk group. Detail the pressure-test added: the Jetson Nanos are out of MVP scope, which means they are not fully provisioned, may not be networked into Tailscale, and have no software baseline. Week one of Group C is not YOLO integration, it is device bring-up: flashing, runtime versions, camera drivers, network join, a heat and power check under sustained load. Add an explicit Sprint C0, device bring-up, half a sprint, before any integration work. If C0 reveals the Nanos cannot sustain a YOLO-class model thermally, the fallback triggers immediately with no integration time lost.

Work items. Define the perception event schema first: how a detection becomes a structured fabric event, what fields it carries, how it is timestamped against the conversation timeline. Build the ingestion path Jetson to Brainstem with backpressure so a noisy stream cannot flood Chroma. Decide and document how perception events live in memory (raw detections, summarized scene state, or both). Extend Thalamus's input features to include recent perception context available. Model: YOLOv5n via TensorRT FP16 on the Nano (most-benchmarked on real Jetson Nano hardware, cleanest fine-tuning ecosystem, which matters for the Group E self-training seed). Normalization happens on the 4070, not the Nano: the Nano captures and runs YOLO and ships compact structured detections, the 4070 normalizes into the fabric schema. Raw camera frames never leave the Nano.

Done-criteria. Both Jetsons streaming, YOLO producing detections, detections entering the fabric as structured events, memory persisting them, the assistant answering a question informed by something a camera saw.

Fallback, pre-approved with a pre-committed trigger: one camera, batch not streaming, perception-as-memory-only with no Thalamus integration. The trigger is a date, not a judgment call: if C0 plus the first integration sprint do not produce a single detection persisted in memory by the end of month 3.75, the fallback is automatic.

## Sprint Group D (months 4.5 to 5.5): The thesis test

Dependencies: frozen workload and baseline from A, real routing from B, perception from C or its fallback.

Sequencing correction from the pressure-test: memory architecture deepening moves to the front of Group D as its own work item with its own mini-characterization against the Group A arms, and only then does the experiment run. Changing the memory architecture immediately before the experiment that depends on memory means testing an uncharacterized component. If memory deepening overruns, the experiment runs on the existing memory architecture rather than slipping.

Work items. Define arms: bare base, fabric with memory only, fabric with memory plus routing, full fabric with perception. Multiple runs per arm. Pre-register the analysis: state the hypothesis, the effect size threshold that counts as "matters," and the statistical test, before running. Score with the deterministic script from Group A.

Done-criteria. A report with arms, runs, effect sizes with confidence intervals, and a verdict (yes, no, or yes-under-conditions, all publishable if methodology is sound) that a skeptical reader cannot dismiss on methodology.

## Sprint Group E (months 5.5 to 6): Self-training seed and publishable artifact

Pressure-test catch: self-training a perception model depends entirely on Group C having succeeded with real streaming perception. If C fell back to reduced scope, there is no data collection loop to seed self-training from, and Group E's first half collapses. This is explicit: Group E self-training is conditional on Group C full scope. If C fell back, Group E becomes purely the artifact and writeup, which is still a complete and honest Stage 1 close.

Work items, full-scope path. Use fabric-collected detection data to curate or fine-tune a dataset for the Jetson YOLO model. Demonstrate the loop once end to end: data collected, dataset curated, model adjusted, improvement measured. Scoped as a seed, not a maintained loop.

Work items, artifact path, always runs. Stage 1 paper draft, extended reproducibility manifest covering Stage 1, design-decision record per the project's documentation standard, clean tagged release.

## Pressure-test: where the first draft was too optimistic

1. Stage 0 is not done. Four open Stage 0 sprints are hard Stage 1 dependencies. The "essentially done" framing hid roughly a month of work.
2. The Jetsons need bring-up before integration. Group C's timeline assumed integration starts on day one. It does not. Sprint C0 exists for this.
3. The general eval will probably show the fabric adding latency for no gain, because single-turn assistant questions do not need memory or perception. The memory-dependent domain set is not secondary, it is the actual thesis instrument.
4. Memory deepening immediately before the thesis test injects an uncharacterized variable into the most rigorous part of the project. It moves to the front of Group D.

## Decisions for the builder

The eval workload (Group A). Option one, a portfolio-legible general assistant eval (MT-Bench slice or similar), comparable to published work. Option two, a domain-specific workload, more honest about what the system is for but harder to benchmark. Recommendation: option one for the headline numbers, but the secondary set must be a multi-session, memory-dependent task suite, because that is what actually tests the thesis. It is not an afterthought.

How smart Thalamus is (Group B). Option one, a small fast classifier-style router, cheap and predictable. Option two, real reasoning headroom, slower but more capable decisions. Recommendation: option one first. A reasoning-class Thalamus competes with Embedder and Chroma for the 4070's resources, and predictability lets effects attribute cleanly. Leave option two as a documented future arm.

The Group C fallback. Recommendation: approve the reduced-scope fallback now and pre-commit the trigger date (end of month 3.75) so it is automatic, not a sunk-cost decision made under pressure later.

4070 resource contention (the decision the first draft missed entirely). Brainstem, Embedder, Thalamus, and Chroma all share one 12GB box, and Stage 1 makes three of them heavier. Options: profile the 4070 under combined load during Group A and treat its limits as a known budget; or move Chroma or Embedder to the 4090 box (but the 4090 is saturated with Cortex); or accept the risk and react when something falls over. Recommendation: profile it in Group A so contention is a known budget, not a Group D surprise.

## Honest risks

The thesis might fail. Qwen3-30B is already strong and orchestration overhead is real. A rigorous negative result is a genuine research contribution and a stronger portfolio piece than a vague positive one. Build the roadmap so a null result is still a win.

Scope. This is a 3-person, 6-month plan for one person with AI agents. The agent-leverage thesis is being tested at the project-management level, not just the engineering level. Sprint Group C is the canary: if it runs clean, the leverage thesis holds; if it spirals, that is the signal to compress D and E and let C's fallback stand.

The highest-leverage move remains the first one: freeze the workload and capture the baseline before touching anything.
