# Experiment 1: Sprint Plan to Phase 0 MVP

Status: v1.0, decisions locked 2026-05-14
Companion to: experiment-1-pipeline-characterization.md

## What this gets us to

Phase 0 of Experiment 1: the minimum viable Nexus fabric, which is also the MVP. A local AI assistant with persistent memory across sessions, reachable from any client device on the network, text-only. It validates the brain so Vector can plug in later. Out of scope for this MVP: edge sensing and the Jetson Nanos, any vision capability, Vector itself.

## Locked decisions

Settled with the user on 2026-05-14. Recorded here so the reasoning stays traceable.

Wire format between the brainstem (4070) and vLLM (4090): OpenAI-compatible HTTP/JSON. vLLM serves it natively, tool-calling for the callback is already defined in it, and it is trivial to instrument and debug. A custom binary protocol was considered and is parked as a future-work card (see Deferred), to revisit only if Phase 1 measurements show serialization is a real cost.

Clock sync between the two boxes: single-clock durations. Each stage is measured as a duration on one machine, so cross-machine clock disagreement never enters the math. Subtraction infers the network-plus-handoff figure, which is exactly the granularity the "is the pipeline the bottleneck" question needs. NTP on both boxes is optional hygiene as a sanity cross-check, not the measurement basis. Explicit offset measurement is available later if Phase 1 ever needs sub-millisecond cross-machine precision.

Bidirectional callback, where the 4090 calls back to the 4070 mid-inference for context: in scope for Phase 0. It is the architectural claim the paper rests on. Without it the fabric is just a pipeline and Experiment 1 has little to say.

## The five sprints

Sprint 1, round trip plus measurement skeleton. Finish the in-flight milestone: vLLM serving the AWQ model, brainstem up, the two wired, round trip confirmed. Same sprint, lock the wire format in code, set up single-clock duration logging, and build the minimal stable log schema with probes at the brainstem entry and the 4090 boundary. Done when a scripted request to the 4070 returns 4090-generated text and produces a complete log line with per-stage latency, verified over roughly 20 runs.

Sprint 2, persistent memory. Chroma on the 4070's SSD, Embedder wired in, write-on-turn and retrieve-before-generate in the brainstem. Extend the log with embedding and retrieval stages. Thalamus stays stubbed with direct forwarding. Done when a fact from session A is retrieved and used in session B after a full service restart.

Sprint 3, multi-node client access. The visible win. Expose the brainstem cleanly, a thin client that works from a phone browser, basic auth. Tailscale means it works on or off the home network. Done when laptop, phone, and CLI each complete a memory-augmented round trip.

Sprint 4, the bidirectional callback. The 4090 calls back to the 4070 mid-inference for more context via tool-calling. Extend the log to separate base inference time from callback time. Done when a prompt needing mid-inference context triggers a logged callback that measurably changes the output.

Sprint 5, Phase 0 close. Soak test across all paths, write the design-decision record, reproducibility manifest, tag the release. Done when a fresh checkout reproduces the running system and a 100-request soak produces a gap-free time-series.

## Deferred (future-work cards)

Custom binary protocol for the 4070-to-4090 wire. Considered for Sprint 1, parked. Revisit only if Phase 1 shows serialization cost is real. Likely not worth it: that link is bounded by network and physical latency, not message size.

Real Thalamus routing logic. Stubbed for the MVP with direct forwarding. The intelligent routing model gets wired up after Phase 0.

Cache layer on the 4070. Build once retrieval is measured to be a cost worth caching.

TensorRT-LLM on the 4090. Deferred to Phase 1 inference optimization. Big perf upside, but it is optimization, not foundation.

Explicit cross-machine clock-offset measurement. Add only if Phase 1 needs sub-millisecond cross-node precision.

Edge sensing and the Jetson Nanos. Out of the text-only MVP. Note: edge sensing is integral to Nexus itself, the fabric's perception layer, not a Vector-only concern. Vector is what makes that perception mobile. It is out of this MVP because the MVP is deliberately text-first, not because it belongs to a later project.

Vector. The embodied phase, after the Nexus brain is validated.

## Rough sizing

Roughly 8 to 12 working days of effort across the five sprints, with Sprint 4 the heaviest. Treat as optimistic.

## How this plan was produced

Drafted by two agents working in parallel with deliberately different lenses, one optimizing for measurement rigor and one for momentum to a visible demo. Their agreement formed the spine of this plan. Their one sharp disagreement, when to build the measurement harness, surfaced as the most consequential decision and was resolved toward the rigor position (minimal stable schema early, extended each sprint) because it matches the user's stated intent to measure along the way rather than retrofitting at the end.
