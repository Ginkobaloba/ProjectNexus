# Nexus Experiment Candidates: Ambition Lens

Status: ideation draft, 2026-05-15
Author: Drew Mattick (with assistance)
Purpose: Ten candidate experiments to validate Nexus or produce publishable findings about it. This set was generated under an explicit "ambition" lens: bias toward novel capability, the autonomy and emergence frontier, and cool factor, while still requiring a real control and a real metric for every idea. A second agent is generating a parallel set under a different lens. A synthesis pass will combine both and cut to five.

Rating convention: each idea is scored 1 to 5 on four criteria. Value to science, weighted heavily. Paper-data, the ability to gather data that supports a paper. Difficulty, where 1 is easiest and 5 is hardest and lower is better per the brief, and which folds in any cost of materials beyond what is already on hand. Cool factor, explicitly not discounted.

Hardware on hand: a 4090 box (Cortex, Qwen3-30B-A3B in vLLM, tool-calling enabled), a 4070 box (Brainstem orchestration, Embedder, Thalamus routing LLM), a Chroma vector DB with a semantic store and an episodic JSONL log, and roughly four Jetson Nanos of which two work and have cameras. Where an idea needs anything beyond this, it is flagged.

---

## 1. The full chain, camera to grounded thought

Thesis: an answer produced by routing real sensor data through the entire fabric (camera, Nano YOLO, 4070 Embedder and Thalamus, Chroma, 4090 Cortex) is more grounded and less hallucinated than the same base model handed the same detections with none of the fabric in the loop. Falsifiable: the fabric path shows no significant grounding gain, or degrades it.

Procedure: stage a set of controlled physical scenes in front of a Jetson camera, each with a known ground-truth description and a set of scene-grounded questions. Run questions through the full fabric. Control: bare Qwen3-30B on the 4090 given the raw YOLO detection stream serialized as text, with no memory retrieval, no Thalamus routing, and no callback, so the only difference is the fabric itself rather than access to the detections. Add an oracle-text upper bound (bare model given a human-written perfect scene description) to bracket the result. Metrics: grounded-answer accuracy against ground truth, hallucination rate (claims not supported by the scene), end-to-end latency. Components exercised: every one of them, which is the point. Why it matters: this is the spine of the systems paper and the single clearest "the fabric does something" claim. If it fails, the project learns that early and cheaply.

Ratings: Value 4 / Paper-data 5 / Difficulty 4 (needs both Jetsons provisioned, full stack live, a labeled scene set) / Cool 4.

## 2. Memory compounding, a learning curve with no training

Thesis: fabric task accuracy rises monotonically as the Chroma memory store grows, even though no model weights ever change. The system gets better by remembering, not by training. Falsifiable null: the slope of accuracy versus memory size is indistinguishable from zero or is negative.

Procedure: build a multi-session, memory-dependent task suite (questions whose answers depend on facts established in earlier sessions). Pre-populate Chroma to a sequence of sizes (empty, 10, 100, 1k, 10k, 100k relevant memories) and run the full suite at each size with multiple replicates. Control: bare Qwen3-30B run on the identical suite, which has no memory and therefore produces a flat line. Metrics: suite accuracy versus memory size, retrieval recall@k and MRR versus size, latency versus size (the cost side of the curve). Components: Embedder, Chroma semantic store, Brainstem retrieve-before-generate, Cortex. Why it matters: a clean rising curve from a system that is not being trained is a genuine and visually striking result, and it is the most direct test of the project's near-term thesis that the fabric-augmented system beats the bare base model.

Ratings: Value 5 / Paper-data 5 / Difficulty 2 (text-only, two GPU boxes, the work is the eval suite and the DB-loading harness) / Cool 4.

## 3. The callback as a knowledge-gap detector

Thesis: the 4090 triggers its mid-inference callback to the 4070 selectively, firing far more often on questions that genuinely need external context than on questions it can answer alone, and the accuracy lift from the callback concentrates exactly on the needs-context items. In short, the model knows what it does not know, mid-thought.

Procedure: build a prompt set partitioned by an independent labeler into "needs external context" and "self-contained." Run the full set with the callback channel enabled and log every callback decision. Control: the identical set run with the callback disabled (one-shot inference only). Metrics: callback trigger precision and recall against the need label, accuracy delta (callback on minus callback off) computed separately for each partition, and false-callback rate on self-contained items (wasted round trips). Components: Cortex tool-calling, the 4070 to 4090 callback channel, Thalamus and Embedder and Chroma as the context source. Why it matters: selective, well-targeted callback behavior is emergent metacognition on a 30B model, and it is the architectural claim the paper rests on. A flat trigger rate across partitions would mean the callback is noise, which is also worth knowing.

Ratings: Value 5 / Paper-data 4 / Difficulty 3 (needs the Sprint 4 callback channel built, plus a carefully labeled prompt set) / Cool 5.

## 4. Top-down attention, the brain steering its own eyes

Thesis: when the 4090 Cortex can issue a capture-control instruction back down through the 4070 to a Jetson mid-task (switch camera, change region of interest, change exposure, request a fresh frame), it solves sensing tasks that a passive, fixed-capture fabric cannot. Falsifiable: top-down control yields no task-success gain over passive capture.

Procedure: design "locate" and "monitor for" tasks whose answer is only obtainable if the system redirects its own sensing (the relevant detail is out of frame, underexposed, or on the other camera). Run them with the downward instruction path active. Control: the same fabric with capture parameters frozen and no top-down control, purely passive. Metrics: task success rate, number of target events detected, time-to-detect. Components: Cortex, callback channel, Brainstem instruction routing, Jetson capture. Hardware flag: this works with digital region-of-interest, exposure, and camera-switching on the two existing cameras and needs no new hardware. An optional pan-tilt servo mount would be a small purchase and would make the demo more vivid, but it is not required. Why it matters: a closed perception-action loop with no robot body yet is the cleanest possible preview of the embodied Vector phase, and "it decided to look somewhere else" is a strong result.

Ratings: Value 4 / Paper-data 4 / Difficulty 4 (needs both Jetsons, the callback channel, and a working downward instruction path) / Cool 5.

## 5. Adversarial sensory injection, hallucination rejection as a fabric property

Thesis: the fabric's instinct and validation layer on the 4070, combined with a cross-check against prior memory, rejects or down-weights corrupted and misleading sensor input at a higher rate than the bare model adopts the same false input as fact. Falsifiable: the fabric adopts false signals at a rate statistically indistinguishable from the bare model.

Procedure: inject a controlled stream of corrupted detections at the Jetson or the embedder boundary (mislabeled objects, physically impossible scenes, two cameras reporting contradictory states, slow drift away from ground truth). Measure how often the false signal propagates into a downstream answer. Control: bare Qwen3-30B handed the identical corrupted detections as text, with no validation layer and no memory cross-check. Metrics: false-belief adoption rate, validation-layer precision and recall on flagging bad input, downstream task error attributable to the injected corruption. Components: Jetson, Brainstem instinct and validation, Embedder, Chroma (the prior-memory cross-check), Cortex. Why it matters: this is the safety story, it is straight off the original paper's planned-experiments list, and "the distributed system is harder to fool than the monolith" is exactly the kind of finding that travels well and supports the ethical-EI framing the project is ultimately for.

Ratings: Value 5 / Paper-data 5 / Difficulty 3 (the injection harness can start text-only at the embedder before the Jetsons are fully in the loop) / Cool 4.

## 6. Unbounded temporal reasoning over episodic memory

Thesis: the fabric answers questions that require reasoning across a long timeline of episodic events (what changed, how often something happens, what happened just before something else) at roughly constant accuracy as the timeline grows, while the bare model's accuracy collapses once the timeline exceeds its context window. Falsifiable: the fabric degrades with timeline length at the same rate as the bare model.

Procedure: generate a long synthetic episodic timeline spanning simulated days and weeks, with a deterministic ground-truth event log. Pose temporal-reasoning questions at increasing timeline lengths. Run through the fabric, which retrieves from the episodic store rather than holding the whole timeline in context. Control: bare Qwen3-30B with as much of the timeline stuffed into its context window as will fit, which is the honest baseline for "just use a big context." Metrics: temporal-QA accuracy versus timeline length for both arms, and the crossover length where the fabric overtakes the baseline. Components: Chroma episodic store, Embedder, Brainstem retrieve, Cortex. Why it matters: "it can still answer accurately about something from three weeks of history" is a concrete capability the base model structurally cannot match, and the crossover point is a clean, defensible figure.

Ratings: Value 4 / Paper-data 5 / Difficulty 2 (text-only, deterministic synthetic timeline, the work is the temporal-QA set) / Cool 4.

## 7. Internal triangulation, the fabric arguing with itself

Thesis: on genuinely ambiguous or contested questions, a structured exchange between Cortex (the 30B reasoner) and Thalamus (the 4B router model) where each critiques the other before a final answer beats either model alone, and most importantly improves calibration, the system's sense of when it is actually unsure. Falsifiable: the exchange does not beat the stronger model alone on accuracy or on calibration.

Procedure: assemble a set of ambiguous and contested items with known answer distributions (questions with a defensible answer, questions that are genuinely underdetermined, questions with a common wrong intuition). Route each through a Cortex-Thalamus critique exchange. Controls: Cortex alone, Thalamus alone, and Cortex self-critique (one model doing two passes, which isolates the value of a genuinely separate second perspective from the value of just thinking twice). Metrics: accuracy on the ambiguous set, expected calibration error, and the rate at which the system correctly flags an item as genuinely uncertain. Components: Thalamus, Cortex, callback channel, Brainstem orchestration. Why it matters: it tests whether heterogeneity inside the fabric buys reasoning quality rather than just throughput, and it operationalizes the multi-agent triangulation principle as a measurable property of the architecture rather than a development practice.

Ratings: Value 4 / Paper-data 4 / Difficulty 2 (both models already run on the two boxes, the work is orchestration and the eval set) / Cool 4.

## 8. The sleep cycle, self-organizing memory

Thesis: a consolidation pass that runs during idle time (deduplicate near-identical vectors, summarize clusters of episodic events into semantic abstractions, re-embed with the current model) improves retrieval quality and downstream accuracy while shrinking the store. The system gets sharper by reorganizing what it knows, not by accumulating more. Falsifiable: post-consolidation retrieval and accuracy are unchanged or worse.

Procedure: run a fixed memory-dependent workload, snapshot the store, run the consolidation pass, then re-run the identical workload. Control: the same store and same workload with consolidation disabled, pure raw accumulation. Metrics: retrieval recall@k and MRR before versus after, downstream task accuracy before versus after, vector count and on-disk size, retrieval latency. Components: Chroma, Embedder, and a new consolidation process. Hardware flag: this needs the "future memory node" from the architecture paper to be built, but it needs no new hardware, the pass can run on the 4070 or 4090 during idle windows. Why it matters: a measurable "dream cycle" that demonstrably improves the system is one of the most distinctive ideas in the original Nexus paper, and showing it works (or does not) is a real contribution to the memory-augmented-systems literature.

Ratings: Value 5 / Paper-data 4 / Difficulty 4 (the consolidation node is explicitly future-work and must be built and characterized before this can run) / Cool 5.

## 9. The closed self-improvement loop on the edge model

Thesis: the fabric can improve its own perception without a human in the labeling loop. Detections collected during normal operation, with the 4090 Cortex acting as a teacher and hard-example miner over them, produce a curated set that fine-tunes the Jetson's YOLOv5n and yields a statistically significant accuracy gain on the deployment distribution. Falsifiable: one closed loop iteration produces no significant mAP gain over the stock model.

Procedure: run the fabric in normal operation so the Jetsons stream detections into Chroma. Use Cortex to auto-label and to surface hard or low-confidence examples. Curate a fine-tuning set from that, fine-tune YOLOv5n offline, redeploy to the Jetson. Control: the stock YOLOv5n with no fine-tune, evaluated on the same held-out set. Metrics: mAP@0.5 and mAP@0.5:0.95 on a held-out, deployment-distribution eval set, plus per-class precision and recall. Components: Jetson capture and YOLO, Brainstem ingest, Chroma detection store, Cortex as teacher, plus an offline fine-tune step. Hardware flag: needs both Jetsons fully provisioned (the Sprint C0 bring-up), and needs a held-out labeled eval set, which can be hand-labeled from the deployment scene or proxied with a public set. No new hardware. Why it matters: a single demonstrated end-to-end self-improvement loop is the clearest possible signal toward the autonomy frontier the whole project is aimed at, and "the system made its own eyes better" is the headline result of the set.

Ratings: Value 5 / Paper-data 4 / Difficulty 5 (depends on full Jetson bring-up, a fine-tuning pipeline, and a labeled eval set, the hardest idea here) / Cool 5.

## 10. Self-modeling, a system that can introspect on its own behavior

Thesis: because every action the fabric takes is already written to the episodic log, the system can be given a tool to query its own history, and it will then answer introspective questions about itself (what it has been asked most, what kinds of questions it tends to get wrong, when it last failed a callback) at significantly above-chance accuracy, while the bare model cannot, because it has no self-log to consult. Falsifiable: the fabric's self-report accuracy is no better than the bare model's guessing.

Procedure: run the fabric long enough to accumulate a real behavioral history in the episodic log. Expose a tool that lets Cortex query that log. Pose a battery of introspective questions whose ground truth is computable directly from the logs. Control: bare Qwen3-30B asked the identical questions with no access to any self-log. Metrics: self-report accuracy against log-derived ground truth, and calibration on questions it genuinely cannot answer (does it correctly say "I do not have that"). Components: Chroma episodic log, Embedder, Brainstem, Cortex, and the Phase 0 metric harness itself, which is the ground-truth oracle. Why it matters: accurate introspection on one's own behavior is a precondition for any serious autonomy or self-improvement work, it is novel as a measurable property of a distributed LLM system, and it sits squarely in the ethical-EI territory the project exists to explore. It is also cheap, the logging substrate already exists.

Ratings: Value 5 / Paper-data 4 / Difficulty 3 (text-only and the log substrate exists, the work is the self-query tool and a log-grounded eval set) / Cool 5.

---

## Quick read across the set

The cheapest strong starters are ideas 2, 6, and 7, all text-only on the two GPU boxes, all with clean controls, none waiting on the Jetsons. Ideas 3 and 10 are the metacognition pair and both become available once the callback channel and the memory loop land. Ideas 1, 4, 5, and 9 pull the edge layer in and rise in difficulty accordingly, with 9 the most ambitious and most dependent on Jetson bring-up. Idea 8 needs the consolidation node built first but pays back with one of the most distinctive findings in the set. If forced to name the two that best fit the ambition lens without overreaching on difficulty, they are idea 2 (a learning curve with no training, striking and cheap) and idea 3 (emergent mid-inference metacognition, the architectural claim made measurable).
