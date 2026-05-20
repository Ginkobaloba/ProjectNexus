# Nexus Experiment Program: Top 5

Status: synthesis pass, 2026-05-15
Companion to: experiment-candidates-rigor-lens.md, experiment-candidates-ambition-lens.md
Grounded against: experiment-1-pipeline-characterization.md, experiment-1-stage1-roadmap.md, HANDOFF_2026-05-15_stage-transition.md

## What this document is

Two agents each generated ten candidate experiments for Nexus, one under a rigor-and-publishability lens and one under an ambition-and-frontier lens. This is the synthesis pass. It combines the twenty, merges the candidates that are really the same experiment wearing different clothes, and cuts to the five strongest, scored honestly against the builder's four criteria. It then proposes a home in the repo for the data those five experiments will produce.

Two housekeeping notes before the work.

First, the two source sets used opposite difficulty scales. The rigor lens scored difficulty so that 5 means cheap and easy. The ambition lens scored it so that 1 means easiest and 5 means hardest. Those are inverted, so the raw difficulty numbers from the two docs are not directly comparable. This document normalizes everything to a single convention: difficulty runs 1 to 5, where 1 is trivial and cheap with hardware on hand and 5 is hard or needs materials that are not on hand, and lower is better. Rigor-lens difficulty scores were re-mapped accordingly. Value, paper-data, and cool keep their original direction, higher is better.

Second, the scoring here is deliberately not generous. Where a merged experiment is weaker than its source candidates claimed, the score is pulled down and the reason is stated. A top-five list that inflates every number is useless for sequencing decisions.

---

# Part 1: The Top 5 Experiments

## How twenty collapsed to five

Both lenses independently produced a memory-thesis experiment, a callback experiment, and a full-chain camera experiment, which is a good sign: the obvious high-value experiments are obvious to more than one line of reasoning. Those pairs merge cleanly. The memory cluster is larger, three candidates collapse into one. The systems-characterization candidates were cut for a specific and honest reason explained in the cuts section: the existing Experiment 1 program already covers them, so listing them as new would be double-counting scheduled work.

The five that survive sit on five different axes, memory capability, architecture and metacognition, edge and embodiment, safety and robustness, and introspection. That spread is intentional. Several strong candidates were cut not on score but because they would have clustered the set on a theme already covered.

## Scores at a glance

Difficulty: 1 is easiest and cheapest, 5 is hardest, lower is better. The other three: higher is better.

| Experiment | Value | Paper-data | Difficulty | Cool |
|---|---|---|---|---|
| M1. Memory as Capability | 5 | 5 | 3 | 4 |
| M2. The Callback: Ablation and Selectivity | 5 | 5 | 3 | 5 |
| M3. The Full Chain: Camera to Grounded Answer | 4 | 4 | 4 | 5 |
| M4. Robustness Under Corruption | 4 | 5 | 3 | 4 |
| M5. Self-Modeling: The System Introspecting on Itself | 4 | 4 | 3 | 5 |

## M1. Memory as Capability

The no-training learning curve, controlled against context-stuffing.

Draws from: rigor-lens 1 (core thesis test with the in-context control), rigor-lens 2 (memory scaling curve), ambition-lens 2 (memory compounding, a learning curve with no training).

Hypothesis. On a frozen suite of multi-session, memory-dependent tasks, the fabric with retrieve-before-generate beats bare Qwen3-30B by a pre-committed effect size, and task accuracy is monotonically non-decreasing as the Chroma semantic store grows from empty through 1k, 10k, 100k, and 1M relevant-plus-mixed items, while retrieval latency stays within budget. The falsifiable shapes carry the experiment either way: a flat or negative slope kills the compounding claim, and accuracy that peaks then degrades as retrieval noise drowns signal is the competing prediction worth catching.

Procedure. Freeze a versioned, content-hashed multi-session task suite with a deterministic scorer. Preload Chroma across the size ladder. Run three arms at each size, score per item, compare paired with bootstrap confidence intervals, and plot accuracy, retriever recall@k, and MRR against store size, with latency against store size as the cost curve.

Control. Two controls, and the second is what makes this reviewer-proof. The bare no-memory arm is the flat floor. The context-stuffing arm, bare Qwen3-30B with the full prior-session transcript packed into the context window up to the model's limit, answers the first question every reviewer asks, which is whether retrieval actually beats simply dumping history into the prompt. An empty-store fabric arm separates retrieval value from warm-cache value.

Metrics. Paired task accuracy and effect size with confidence intervals, accuracy versus store size (the learning curve itself), recall@k and MRR versus size, end-to-end and retrieval latency versus size.

Components exercised. Brainstem retrieve-before-generate, Embedder, Chroma semantic store, Cortex.

Scores: Value 5, Paper-data 5, Difficulty 3, Cool 4.

Rationale. This is the thesis. Stage 1 exists to find out whether the fabric-augmented system beats the bare model, and this is the instrument that answers it. The merge buys more than any single source: the context-stuffing control separates a real finding from an artifact of giving one arm more information, and the scaling curve turns a single yes-or-no into a shape with a named failure mode, so the experiment is publishable whichever way it lands. It is text-only on the two GPU boxes, so difficulty is a moderate 3 rather than low only because the merged scope (the suite, the database-loading harness, the in-context control, the size ladder) is real work. Cool is an honest 4, not 5: a rising accuracy curve from a system whose weights never change is genuinely striking, but it is a line on a chart, not a camera deciding where to look. Value, paper-data, and leverage carry it, and the frozen suite it produces is the shared substrate the next three experiments reuse.

## M2. The Callback: Ablation and Selectivity

Does the bidirectional channel earn its keep, and does it fire for the right reasons.

Draws from: rigor-lens 4 (callback ablation, is the channel causally worth anything), ambition-lens 3 (the callback as a knowledge-gap detector).

Hypothesis. Two parts. The causal part: on tasks engineered so the needed fact cannot be predicted at prompt-assembly time and is only identifiable mid-reasoning, enabling the callback raises paired accuracy over a callback-disabled arm by a measurable effect size. The selective part: the callback fires far more often on items independently labeled "needs external context" than on items labeled "self-contained," and the accuracy lift concentrates on the needs-context partition. The two nulls worth ruling out are that the callback adds round trips and latency without changing outcomes, and that the trigger rate is flat across partitions, which would mean the callback is noise.

Procedure. Build a prompt set partitioned by an independent labeler into needs-context and self-contained, with the needs-context items constructed so the required fact is genuinely unavailable at prompt-assembly time. Run the full set with the callback enabled and again with it disabled. Log every callback decision with its rationale.

Control. The callback-disabled fabric arm, identical in every other respect, is the causal control. The self-contained partition is the internal control for false-callback behavior, since callbacks there are wasted round trips by construction.

Metrics. Paired accuracy delta overall and computed separately per partition, callback trigger precision and recall against the need label, false-callback rate on self-contained items, added latency per callback, the fraction of callbacks that actually change the output, and convergence within N callbacks.

Components exercised. Cortex tool-calling, the 4070-to-4090 callback channel, Brainstem callback endpoint, Embedder and Chroma as the context source.

Scores: Value 5, Paper-data 5, Difficulty 3, Cool 5.

Rationale. The callback is the architectural claim the whole fabric framing rests on, so a rigorous test of it is high value no matter the outcome. The merge is the point: the rigor candidate gives a clean causal ablation that can produce an honest negative, and the ambition candidate gives the selectivity analysis that asks not just whether the channel works but whether it works for the right reason. Selective mid-inference callback behavior reads as emergent metacognition on a 30B model, which is why cool is a true 5. Difficulty is 3, gated on the callback channel itself being built and hardened (Stage 0 Sprint 4, hardened in Stage 1 Group B) plus a carefully partitioned prompt set, but it reuses M1's frozen suite, so the marginal cost is the labels and the channel, not a fresh harness.

## M3. The Full Chain: Camera to Grounded Answer

Identical sensor data, fabric versus bare model.

Draws from: rigor-lens 8 (the full chain, identical sensor data, bare model versus fabric), ambition-lens 1 (the full chain, camera to grounded thought).

Hypothesis. On questions answerable only from what a camera saw, the full chain answers correctly and with a lower hallucination rate than bare Qwen3-30B given the same raw detections, and lands below an oracle-text upper bound. Falsifiable: the fabric path shows no significant grounding gain, or degrades it.

Procedure. Stage a controlled scene sequence in front of a Jetson, each scene with a known ground-truth description and a set of scene-grounded questions. Run detections through the fabric into persistent memory, then ask the questions.

Control. Three reference points bracket the result. The lower control is bare Qwen3-30B fed the same YOLO detections serialized as text, with no memory retrieval, no Thalamus routing, and no callback, so the only difference is the fabric itself rather than access to the detections. The upper bound is the bare model given a human-written perfect scene description, which brackets how much of the gap is reachable at all. The roadmap's perception-as-memory-only fallback arm is included as a third reference, and it doubles as the degraded-mode result if Group C falls back.

Metrics. Grounded-answer accuracy against ground truth, hallucination rate (claims not supported by the scene), time-to-detect, end-to-end latency, detection persistence rate.

Components exercised. The entire fabric, Jetson camera and YOLO through Brainstem, Embedder, Thalamus, and Chroma, to Cortex. Exercising every component is the point.

Scores: Value 4, Paper-data 4, Difficulty 4, Cool 5.

Rationale. This is the builder's headline seed concept and the embodied-autonomy direction, and it is the integration test for the whole fabric because it touches every component. Honest scoring puts its raw science value at 4 rather than 5: it is the most demo-shaped experiment in the set, one staged scene set in one environment, and the expected result (the grounded path hallucinates less) is not surprising. Paper-data is 4 for the same reason, the data is clean but the external validity is narrow. Cool is a true 5, and the brief says not to discount it: "it answered correctly about something only a camera saw" is the single most legible result the project can produce. Difficulty 4 is the real cost. It gates on Jetson bring-up, which the Stage 1 roadmap names as the highest-risk item, with a pre-committed reduced-scope fallback. No new materials are needed, but the bring-up effort is not free.

## M4. Robustness Under Corruption

A poisoned store and corrupted sensors, two injection points, one question.

Draws from: rigor-lens 3 (retrieval poisoning), ambition-lens 5 (adversarial sensory injection). Closely related: rigor-lens 9 (memory persistence and decay), noted below as a natural extension.

Hypothesis. The fabric resists bad data at two boundaries. Store side: as the fraction of irrelevant or misleading distractor memories rises, fabric accuracy degrades, and there is a crossover ratio below which the fabric still beats the bare model and above which it is worse. Sensor side: the 4070 validation layer, combined with a cross-check against prior memory, rejects or down-weights corrupted sensor input at a higher rate than the bare model adopts the same false input as fact. The nulls worth ruling out are that the fabric adopts false signals at a rate statistically indistinguishable from the bare model, and that no usable crossover ratio exists.

Procedure. Two coordinated sub-experiments sharing one injection harness. M4a, store poisoning: hold the relevant memories fixed, vary the distractor ratio across a pre-registered grid, measure accuracy and retrieval precision, and estimate the crossover ratio with a confidence interval. M4b, sensory injection: inject a controlled stream of corrupted detections, starting text-only at the embedder boundary and extending to the Jetson once the edge path exists, covering mislabeled objects, physically impossible scenes, two cameras reporting contradictory states, and slow drift away from ground truth, and measure how often the false signal propagates into a downstream answer.

Control. The bare model, immune to store poisoning and with no validation layer, defines the line the fabric must stay above. A clean-store, clean-sensor fabric arm is the within-fabric control.

Metrics. Accuracy versus distractor ratio, crossover ratio with confidence interval, retrieval precision, false-belief adoption rate, validation-layer precision and recall on flagging bad input, downstream task error attributable to the injected corruption.

Components exercised. Embedder, Chroma, Brainstem instinct and validation layer, Cortex, plus the Jetson for the M4b edge stage.

Scores: Value 4, Paper-data 5, Difficulty 3, Cool 4.

Rationale. This is the safety story, and it is the experiment that most directly serves the reason the project exists, which is the ethical development of Electronic Intelligences. "The distributed system is harder to fool than the monolith" is a finding that travels well beyond this repo. The merge is natural rather than forced: store poisoning and sensor corruption are the same question asked at two boundaries, and one harness covers both. Paper-data is a real 5, the experiment produces clean numbers regardless of outcome, a crossover ratio and a false-belief adoption rate are publishable whether the fabric wins or loses. Value is an honest 4, not 5, with a specific caveat: M4b's result is only as trustworthy as the validation layer is real. If that layer ships as a thin stub, M4b risks measuring the stub and not the architecture, and the design should treat a non-trivial validation layer as a hard precondition. Difficulty is 3 in aggregate, but it is uneven: M4a alone is closer to 2, text-only and cheap, while M4b alone is closer to 4 because it needs the validation layer built and the edge path live. The rigor-lens decay candidate (does the fabric forget the right things) is the obvious third boundary and should be folded in as an extension arm once the decay policy exists, not run as a separate experiment.

## M5. Self-Modeling: The System Introspecting on Itself

A system that can answer questions about its own behavior.

Draws from: ambition-lens 10 (self-modeling, a system that can introspect on its own behavior). Leans on the methodology spine of rigor-lens 10 in that the metric harness is the ground-truth oracle.

Hypothesis. Because every action the fabric takes is already written to the episodic log, a tool that lets Cortex query that log lets the system answer introspective questions about itself (what it has been asked most, what kinds of questions it tends to get wrong, when it last failed a callback) at significantly above-chance accuracy, while bare Qwen3-30B cannot, because it has no self-log to consult. The genuinely falsifiable edge is calibration: on questions it cannot answer from the log, does it correctly say it does not have that.

Procedure. Run the fabric long enough to accumulate a real behavioral history in the episodic log, which happens for free while M1, M2, and M4 run. Expose a self-query tool to Cortex. Pose a battery of introspective questions whose ground truth is computable directly from the logs.

Control. Bare Qwen3-30B asked the identical questions with no access to any self-log, which sets the guessing floor.

Metrics. Self-report accuracy against log-derived ground truth, correct-abstention rate on questions that cannot be answered from the log, expected calibration error.

Components exercised. Chroma episodic log, Embedder, Brainstem, Cortex, and the Phase 0 metric harness itself, which is the ground-truth oracle.

Scores: Value 4, Paper-data 4, Difficulty 3, Cool 5.

Rationale. Accurate introspection on one's own behavior is a precondition for any serious autonomy or self-improvement work, and it is novel as a measurable property of a distributed LLM system, which makes it publishable on its own terms and not just as a stepping stone. It is cheap, the logging substrate already exists and the behavioral history accumulates at no marginal cost while the other experiments run. It also sits squarely in the ethical-EI territory the project is ultimately for, which is why it earns a slot over higher-scoring but more clustered alternatives. The honest deflation: value is a 4, not the 5 the source claimed, because the headline result, "it can query its own log," is partly a tooling demonstration. Give a model a query tool and of course it queries. The part that is genuinely interesting and genuinely falsifiable is calibration, whether it correctly abstains on what it cannot know, and that is what the design should center.

## Why these five and not the others

The five span five axes on purpose. A sixth memory experiment, or a second organ-level ablation, would have bought less than the spread does.

The systems-characterization candidates were the hardest cut, because they are the cheapest and most reviewer-proof ideas in the whole pool. They were cut anyway, for one honest reason: the existing Experiment 1 program already covers them. Rigor-lens 5, latency decomposition with memory in the loop, is literally Experiment 1 Phase 1's job, correcting the Stage 0 "it is all Cortex" stub-path finding once memory is wired in. Rigor-lens 6, the 4070 contention envelope, is already a named Sprint Group A work item in the Stage 1 roadmap, called out there as the decision the first draft missed. Rigor-lens 10, probe overhead and reproducibility, is Phase 0 Component G's acceptance criterion plus the Sprint 5 reproducibility manifest. Listing any of them as a new top-five experiment would be counting scheduled work twice. The right move is to note that the program already absorbs them and spend the five slots on experiments that are not yet anywhere on the plan.

Rigor-lens 7, routing value with two degenerate-router controls, is a solid mid-tier experiment with a clean two-control framing, and it belongs in the program, it maps directly onto Stage 1 Group B. It is not in the top five because it scores below M5 on value and cool and because it is an organ-level ablation that would cluster thematically with M2.

Ambition-lens 6, unbounded temporal reasoning over episodic memory, is the strongest cut and deserves a clear note. It is cheap (text-only, a deterministic synthetic timeline), its paper-data is a 5, and the crossover-length figure is clean and defensible. It lost its slot only because it is a memory experiment and would cluster with M1. The recommendation is concrete: fold its episodic-timeline arm into M1 as an optional fourth arm, or run it as the cheapest possible standalone sixth experiment if there is appetite for one.

Ambition-lens 7, internal triangulation, is cheap and it operationalizes the project's own multi-agent principle as a measurable property rather than a development habit, which is appealing. It was cut because both its value and cool land at 4 and it does not open an axis the top five do not already touch.

Ambition-lens 8 (the sleep cycle) and ambition-lens 9 (the closed self-improvement loop on the edge model) are the two highest-cool ideas in the entire pool, and both were cut on difficulty and dependency, not on appeal. The sleep cycle needs the consolidation node built, which is explicit future work. The self-improvement loop needs full Jetson bring-up, a fine-tuning pipeline, and a labeled eval set, and it structurally depends on M3 having already succeeded. These are capstones, not openers. The self-improvement loop in particular should be the program's victory-lap experiment, run once M3 lands and the edge data-collection loop is real.

## Recommended sequencing and staging

The five do not become available at the same time. Three of them gate on Nexus components that are not built yet, so the order is set by dependencies, not by score. The staging below maps onto the Stage 1 roadmap's sprint groups.

Stage one, text-only, no new components. M1 runs first. It depends only on persistent memory, which the handoff names as the immediate next step (Stage 0 Sprint 2), and the frozen task suite and deterministic scorer it builds are the shared substrate that M2, M4, and M5 all reuse. This matches the roadmap's stated highest-leverage move, freeze the workload and capture the baseline before touching anything. M4a, store poisoning, piggybacks directly on M1's memory harness and eval suite, so it runs immediately after or alongside M1 at near-zero marginal cost. This pairing maps onto Sprint Group A.

Stage two, once the callback channel lands. M2 runs after the bidirectional callback channel is built and hardened, Stage 0 Sprint 4 for the build and Stage 1 Group B for the hardening. It reuses M1's eval suite and adds the partition labels. M5, self-modeling, slots into the same window, because it needs the episodic log to have accumulated a real behavioral history, which it will have done for free while M1, M4a, and M2 ran, and the self-query tool itself is a cheap build. This pairing maps onto Sprint Group B.

Stage three, gated on the edge layer. M3 runs in Stage 1 Group C, gated on Jetson bring-up (Sprint C0). It is the highest-risk experiment, and the roadmap's pre-committed fallback applies directly: reduced scope, one camera, perception-as-memory-only, with an automatic trigger at the end of month 3.75. M4b, sensory injection, is the back half of the robustness experiment. It needs both the 4070 validation layer and M3's edge path, so it runs last, after M3.

The order in one line: M1 then M4a, then M2 then M5, then M3 then M4b. If Group C falls back, M3 runs in degraded mode and M4b's sensor-side arm degrades with it, but M1, M4a, M2, and M5 are all unaffected. The program stays publishable on the text-only spine alone, which is the right risk posture given that the Jetsons are the canary.

One cross-check worth doing before any of this turns into code: the scoring in this document is a judgment call, and the difficulty re-mapping in particular is the kind of step where a single line of reasoning can drift. Running this synthesis through one more independent pass, ideally a different model, before the program is locked is cheap insurance and consistent with how the Experiment 1 design and the Stage 1 roadmap were already pressure-tested.

---

# Part 2: The Experimental Data Space

The builder wants all experimental data and results in one organized place so the papers to come have whatever they need. This section proposes that place. The structure is derived from what the five experiments above actually generate, and it is shaped to fit how the repo is already organized rather than imposing a new scheme on top of it.

## What the five experiments actually produce

Across M1 through M5, the data falls into seven kinds. Raw metric logs, the per-stage probe records in JSONL, large and high-volume, produced by every run. Frozen workloads, the versioned and content-hashed task suites, prompt-set partitions, staged-scene definitions with ground-truth labels, and distractor-ratio grids, which must be immutable once a run uses them. Eval outputs, the per-item scores and model responses. Analysis results, the bootstrap confidence intervals, effect sizes, crossover ratios, and recall curves. Characterization reports, the written per-experiment writeups that feed the papers. Figures, the plots. And large binary artifacts, the preloaded Chroma collections at 1M vectors, the raw camera frames from M3's staged scenes, and any fine-tune datasets or checkpoints if the self-improvement follow-on ever runs. The structure has to keep the first six close and version-controlled, and keep the seventh out of git without losing track of it.

## Directory layout

Design docs already live in `docs/experiments/`, and the Experiment 1 design doc already references `experiments/exp1/runs/<uuid>/` and a `bench/` harness. This layout formalizes and extends that, it does not replace it.

```
docs/experiments/                         # design docs (exists today, unchanged)
  experiment-1-pipeline-characterization.md
  experiment-1-stage1-roadmap.md
  experiment-program-top5.md               # this document
  exp-m1-memory-as-capability.md           # per-experiment design docs (added as each is designed)
  exp-m2-the-callback.md
  ...

bench/                                     # harness code (exists today, unchanged)
  probes.py  sinks.py  runner.py  analyze.py

experiments/                               # all experimental DATA and results
  README.md                                # the convention doc: layout, naming, git-vs-volume rules
  INDEX.md                                 # generated: every experiment, its runs, status, key results
  shared/
    workloads/                             # frozen, versioned, content-hashed workloads
      memory-suite-v1/                     # M1, M2, M4, M5 multi-session task suite
        manifest.yaml                      # version, content hash, item count, scorer reference
        items.jsonl
        scorer.py
      callback-partition-v1/               # M2 needs-context vs self-contained labels
      poison-grids-v1/                     # M4 distractor-ratio grids
      scene-set-v1/                        # M3 staged scenes
        manifest.yaml
        ground-truth.jsonl                 # labels: committed
        frames.pointer.yaml                # raw frames: on the volume, pointer committed
      introspection-probes-v1/             # M5 log-grounded question battery
    schemas/
      metric-record.schema.json            # the probe-record schema
      eval-output.schema.json
      run-summary.schema.json
    harness-pins/                          # container image hashes, runs.yaml templates
  exp-m1-memory-as-capability/
    run-index.csv                          # uuid, date, arm, key params, git SHA, workload hash
    runs/
      <run-uuid>/
        runs.yaml                          # full config snapshot (committed)
        summary.json                       # per-run aggregates: p50/p95/p99, accuracy, drop rate (committed)
        env.json                           # hardware, PCIe topology, clock-skew snapshot (committed)
        eval-output.jsonl                  # per-item scores and responses (committed if under size cap)
        metrics.pointer.yaml               # raw probe log: on the volume, pointer committed
    analysis/
      effect-sizes.json
      learning-curve.json
      figures/
        accuracy-vs-store-size.svg
    report.md                              # the characterization report for this experiment
  exp-m2-the-callback/
    ...                                    # same shape
  exp-m3-the-full-chain/
    ...
  exp-m4-robustness-under-corruption/
    ...
  exp-m5-self-modeling/
    ...
```

## Naming and organization conventions

Experiment directories use `exp-m<N>-<slug>`, and the slug matches the design doc in `docs/experiments/` exactly, so the design and the data for one experiment are one search away from each other. M4's two sub-experiments share the one `exp-m4-robustness-under-corruption/` directory and are distinguished by an `arm` field in `runs.yaml` (`m4a-store-poisoning`, `m4b-sensory-injection`) rather than by separate directories, because they share a harness and a workload family.

Runs are UUID directories. The UUID is the unforgeable identity, and the human-readable mapping lives in the per-experiment `run-index.csv`, which carries the date, the arm, the key parameters, the git SHA of the code that produced the run, and the content hash of the workload it ran against. Every run records both of those identifiers in `runs.yaml` as well, so a run is never orphaned from the code and workload that made it.

Workloads are frozen. A workload directory is named `<name>-v<major>`, carries a `manifest.yaml` with a content hash, and is never edited in place. A change to a workload is a new version directory, full stop. This is what makes a paired comparison across runs honest months apart.

Schemas are versioned and shared. The probe-record schema, the eval-output schema, and the run-summary schema live once in `experiments/shared/schemas/` and carry a `schema_version` field, so a format change is detectable rather than silent. This matches the minimum-schema discipline already described in the Experiment 1 design.

`INDEX.md` is generated, not hand-maintained. A small script walks the `experiments/` tree and emits the current state of every experiment and its runs. Hand-maintained indexes rot.

## Git versus volume

The rule is simple: if a file is small, text, and a paper might need it, it goes in git. If it is large or binary, it goes on the volume and a pointer goes in git.

Committed to git: all design docs, workload manifests and the workload contents themselves when they are text and reasonably sized (task suites, prompt-set partitions, ground-truth labels, synthetic timelines, poison grids, scorers), all schemas, `runs.yaml` and `summary.json` and `env.json` for every run, all analysis results as JSON, all figures (SVG or PNG, they are small and paper-facing and belong under version control with the analysis that made them), the per-experiment `report.md`, the `run-index.csv` files, the generated `INDEX.md`, and every pointer file.

On the volume with only a pointer committed: the raw `metrics.jsonl` logs, which run to hundreds of megabytes for a long sweep and would blow straight past the 5 MB large-files hook; the preloaded Chroma collections, which at 1M vectors are gigabyte-scale; the raw camera frames and staged-scene captures from M3; and any fine-tune datasets or model checkpoints from a future self-improvement follow-on. The volume is the existing NAS, which is already in the topology and is the natural home for this.

A pointer file is small YAML, committed in place of the artifact, and it carries the logical name, the volume path, a content hash (sha256), the byte size, the producing run UUID, and the git SHA of the producing code. That is enough to detect drift, to re-fetch, and to prove that a given large artifact belongs to a given run. The pre-commit large-files hook is the enforcement mechanism: if a raw log is staged by accident, the hook stops the commit, which is the behavior we want.

The borderline case is `eval-output.jsonl`, the per-item responses. Model responses can be verbose. The convention: commit it if the file is under a few megabytes, otherwise treat it like a raw log and move it to the volume with a pointer. The size cap goes in `experiments/README.md` so the decision is a rule and not a judgment call each time.

## How this aligns with the existing repo

This layout extends three things that already exist rather than inventing a fourth. The `docs/experiments/` design-doc directory stays exactly as it is and simply gains per-experiment design docs alongside this one. The `bench/` harness code stays where the Experiment 1 design already puts it. The `experiments/` data directory formalizes the `experiments/exp1/runs/<uuid>/` pattern that the Experiment 1 design already assumes, keeping the `runs/<uuid>/` shape and the `runs.yaml` per-run config so Experiment 1's own data drops into this structure without rework. The naming convention, design doc slug equals data directory slug, is the one new discipline, and it is cheap to adopt and pays for itself the first time someone goes looking for the data behind a figure.
