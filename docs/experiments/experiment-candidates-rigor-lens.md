# Experiment Candidates: Rigor Lens

Ten candidate experiments, generated under a rigor-and-publishability lens. Companion to experiment-candidates-ambition-lens.md. Both feed a synthesis pass that whittles the combined set to a top 5.

Rating convention: each axis 1 to 5, 5 is best. For difficulty, 5 means cheap and easy with what is on hand, 1 means hard or needs new materials.

## 1. Core thesis test: memory-dependent multi-session tasks, fabric versus bare model, with an in-context control

Hypothesis: on a pre-registered suite of multi-session, memory-dependent tasks, the fabric with retrieve-before-generate achieves higher paired task accuracy than bare Qwen3-30B, with effect size above a pre-committed threshold. Procedure: freeze a versioned task suite with a deterministic scorer, run three arms, score per item, compare paired with bootstrap CIs. The control that makes this reviewer-proof is not just bare-model-with-no-memory; it is a second control where the full prior-session transcript is stuffed into the context window up to the model's limit. That answers the question every reviewer asks first: whether retrieval beats simply dumping history into the prompt. Components: Brainstem, Embedder, Chroma NAS, Cortex. Why it matters: this is the thesis, and the in-context control separates a real finding from an artifact of giving one arm more information.
Value 5, Paper data 5, Difficulty 3, Cool 3.

## 2. Memory scaling curve: does performance actually improve as the database grows

Hypothesis: retrieval-augmented accuracy is monotonically non-decreasing as the semantic store grows from empty to N items of relevant prior context, while retrieval latency stays within budget. The falsifiable part is the shape: the competing prediction is that accuracy peaks then degrades as retrieval noise drowns signal. Procedure: preload Chroma to {empty, 1k, 10k, 100k, 1M} relevant-plus-mixed items, run the frozen suite at each size, plot accuracy and retriever recall@k and MRR against store size. Control: bare model is the flat no-memory line; the empty-store fabric arm isolates retrieval value from warm-cache value. Components: Embedder, Chroma NAS, Brainstem, Cortex. Why it matters: directly tests the builder's seed concept, and because it tests the failure mode too it produces a publishable result either way.
Value 4, Paper data 5, Difficulty 4, Cool 3.

## 3. Retrieval poisoning: does memory still help when the store is partly junk

Hypothesis: as the fraction of irrelevant or misleading distractor memories rises, fabric accuracy degrades, and there is a crossover ratio below which the fabric still beats the bare model and above which it is worse. Procedure: hold relevant memories fixed, vary the distractor ratio across a pre-registered grid, measure accuracy and retrieval precision, estimate the crossover ratio with a CI. Control: the bare model, immune to store poisoning, defines the line the fabric must stay above; plus a clean-store fabric arm. Components: Embedder, Chroma, Brainstem, Cortex. Why it matters: pre-empts the obvious skeptical question, characterizes the safe operating envelope of the memory substrate.
Value 4, Paper data 4, Difficulty 4, Cool 4.

## 4. Callback ablation: is the bidirectional 4070-to-4090 channel causally worth anything

Hypothesis: on tasks engineered to require context not in the initial prompt and only identifiable mid-reasoning, enabling the callback raises accuracy versus a callback-disabled arm, with a measurable effect size. The null to rule out: the callback adds round trips and latency without changing outcomes. Procedure: build a task set where the needed fact cannot be predicted at prompt-assembly time, run callback-on versus callback-off, measure paired accuracy delta, callback trigger rate, added latency per callback, and fraction of callbacks that actually change the output. Control: the callback-disabled fabric arm, identical in every other respect. Components: Brainstem callback endpoint, Cortex tool-calling, Embedder, Chroma. Why it matters: the callback is the architectural claim the paper rests on, so a rigorous test, including a clean negative, is high-value either way.
Value 5, Paper data 5, Difficulty 3, Cool 4.

## 5. Latency decomposition with memory in the loop: correcting the "it is all Cortex" finding

Hypothesis: once persistent memory is wired in, embed-plus-retrieve is no longer negligible, and the Stage 0 stub-path finding does not survive contact with the real pipeline. Falsifiably: embed-plus-retrieve contributes at least a pre-committed percentage of end-to-end p95. Procedure: instrument every stage boundary, run the memory path under a fixed workload, decompose p50/p95/p99 by stage, compare against the archived stub-path decomposition. Control: the Stage 0 stub-path numbers are the baseline. Components: Brainstem, Embedder, Chroma, Cortex. Why it matters: turns a "starting hypothesis" into a settled fact, nearly free because the harness exists.
Value 3, Paper data 4, Difficulty 5, Cool 2.

## 6. The 4070 contention envelope: three organs sharing 12 GB

Hypothesis: as concurrent load on the 4070 grows from one organ to all of them, end-to-end p95 holds within budget up to a load level X, beyond which one specific stage saturates first. Pre-register which stage you predict saturates first. Procedure: run a load matrix {Embedder only, plus Thalamus, plus Chroma, all three plus client traffic}, capture per-stage latency, VRAM, CPU at each cell. Control: each component measured in isolation as the uncontended baseline. Components: Embedder, Thalamus, Chroma, Brainstem. Why it matters: the Stage 1 roadmap calls 4070 contention the decision the first draft missed; characterizing the shared-box envelope is a clean systems contribution and de-risks the thesis test.
Value 3, Paper data 4, Difficulty 4, Cool 2.

## 7. Routing value: a real Thalamus against two degenerate-router controls

Hypothesis: a real Thalamus router lands within epsilon of the always-escalate quality ceiling while cutting mean compute or latency by a pre-committed margin. The null: it just adds a decision-latency tax and mis-routes enough to erase the savings. Procedure: run the frozen suite through three routers, score accuracy, mean and p95 latency, compute per query, routing decision latency, mis-route rate against a post-hoc oracle. Control: two degenerate routers bound the frontier, always-forward-to-Cortex and always-answer-cheap-on-the-4070; Thalamus must beat the line between them. Components: Thalamus, Brainstem, Embedder, Cortex. Why it matters: tests whether the routing organ earns its keep, with a precise two-control frontier framing.
Value 4, Paper data 4, Difficulty 3, Cool 3.

## 8. The full chain: identical sensor data, bare model versus fabric

Hypothesis: on questions answerable only from what a camera saw, the full chain answers correctly at a rate significantly above bare Qwen3-30B given the same raw input. Procedure: stage a controlled scene sequence in front of a Jetson, run detections through the fabric into persistent memory, then ask perception-grounded questions; measure QA accuracy, time-to-detect, end-to-end latency, detection persistence rate. Control: bare Qwen3-30B fed the same sensor data directly (frames if multimodal, or a fixed captioner's output), no persistent perception memory; plus the roadmap's perception-as-memory-only fallback arm. Components: the entire fabric, Jetson camera and YOLO through to Cortex. Why it matters: the embodied-autonomy direction and the builder's headline seed concept. Honest flag: needs the Jetsons brought up first, the highest-risk roadmap item. No new materials, but the bring-up cost is real.
Value 5, Paper data 4, Difficulty 2, Cool 5.

## 9. Memory persistence and decay: does the fabric remember, and forget the right things

Hypothesis, two parts: a fact written in session A is retrieved and correctly used in session B after a full service restart at a rate far above the bare model's chance level; and under a configured decay policy, importance-tagged facts survive while low-importance facts are pruned without measurably hurting task accuracy. Procedure: write tagged facts, restart all services, test recall and downstream use in fresh sessions; then run decay-on versus decay-off arms. Control: bare model defines the chance-level recall floor after restart; decay-off fabric is the control for the decay-on arm. Components: Embedder, Chroma NAS, episodic log, Brainstem. Why it matters: "forgetting as a feature" is currently pure assertion; this makes both halves falsifiable on cheap, Sprint-2-adjacent infrastructure.
Value 4, Paper data 4, Difficulty 4, Cool 3.

## 10. Probe overhead and reproducibility audit: the methodology spine

Hypothesis: the metric harness imposes under a pre-committed overhead threshold on end-to-end latency, probes-on versus probes-off, and a fresh checkout on the same hardware reproduces the published latency numbers within the run-to-run variance band. Procedure: run matched probes-on and probes-off sweeps, then have the system rebuilt from a clean checkout and re-measured; report the overhead delta, bootstrap variance, reproduction error, and minimum detectable effect size given the sample count. Control: the probes-off run is the control for overhead; the independent fresh-checkout run is the control for reproducibility. Components: the bench harness plus the whole stack. Why it matters: every other experiment inherits its credibility from this one, and it is the cheapest on the list.
Value 4, Paper data 3, Difficulty 5, Cool 2.

## Note for the synthesis pass

Ideas 1, 2, 3, 9 form a tight memory-quality cluster and could be partly merged or staged. 4 and 7 are organ-level ablations. 5, 6, 10 are pure systems characterization, the cheapest and most reviewer-proof. 8 is the only one needing the Jetsons, the most risk but the most reach. Natural trade with an ambition-lens set: keep 1, 4, 8 as the rigor anchors and let the ambition set push the frontier.
