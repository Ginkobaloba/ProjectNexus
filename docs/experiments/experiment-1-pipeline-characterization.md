# Nexus Experiment 1: Fabric Implementation and Performance Characterization

**Status:** Design doc, draft v0.5
**Date:** 2026-05-13
**Author:** Drew Mattick (with assistance)
**Scope:** A systems paper in the shape of "we built this fabric and characterized it." Two-phase: Phase 0 builds the Minimum Viable Fabric (MVF) to a set of measurable acceptance criteria; Phase 1 runs the full characterization sweep on the completed MVF. Phase 1 also produces the gating decision for the downstream inference-quality experiment.
**Sequencing:** Phase 0 → rolling Phase 0 measurements → Phase 1 canonical characterization → gating decision → (gated) Experiment 2.

---

## 0. Ground Truth: What Nexus Actually Is Right Now

Before designing anything, a sober reading of the repo at `c:\dev\project-nexus`. The point is to design an experiment that fits the artifact in front of us, not the aspirational architecture in the paper drafts.

### What is implemented

1. **`nodes/brainstem_4070/`**: FastAPI service on port 5001. Two endpoints. `POST /embed` runs a SentenceTransformer (default `BAAI/bge-large-en-v1.5`, default device `cpu`) over a list of strings, writes each as a semantic memory to the NAS, and emits an episodic event. `POST /stm/write` validates, embeds, appends to an in-process deque (`STMBuffer`, default cap 1024). The directory is named `brainstem_4070`, but the code has no GPU pinning, no batching policy beyond `batch_size=16` hardcoded inside `embed_texts`, no routing logic, no cache layer, no DB read path, and no notion of a 4090 peer.

2. **`nodes/nas_memory/`**: FastAPI service on port 5002. Chroma persistent client for semantic vectors with cosine similarity. JSONL append-only file for episodic events. Synchronous HTTP endpoints, no batching, no async I/O.

3. **`core/nas_client.py`**: The 4070-side HTTP client. Plain `requests.post` per write. One POST per semantic item, one POST per episodic event. No connection pool tuning, no batching, no async, no retry/backoff, no fanout, no callback channel.

4. **`automation/`**: A separate n8n automation stack (Traefik + Cloudflared + n8n 2.8.3) with full env wiring for a planned 4090 Cortex (`CORTEX_LLM_URL=http://host.docker.internal:8001`, Qwen2.5-Coder-32B-AWQ in vLLM) and a planned 4070 Brainstem LLM (`BRAINSTEM_LLM_URL=http://<REDACTED_LAN_IP>:8000`, Qwen3-4B). The `automation/docs/cortex-design.md` is the sharpest design doc in the repo. It describes an Orchestrator/Builder pattern, a workflow registry, IoT ingest contract, and NAS memory model. It treats Cortex as an LLM endpoint with a request/response contract, not as a peer that calls back to the 4070.

5. **`core/`**: An MQTT heartbeat-and-registry scaffold (`paho-mqtt`) on `nexus/heartbeat`. Per the repo's own `inventory.md` it is architecturally orphan: nothing in the FastAPI services calls into it. Useful for liveness if revived, not on any data path today.

6. **`docker/docker-compose.yml`**: Builds only brainstem and NAS. No Cortex, no Jetson, no router.

### What is *not* there (relevant to the new framing)

- **No Jetson code.** `nodes/jetson_peripherals/__init__.py` is a one-line stub. No capture pipeline, no codec choice, no transport selection. The handoff doc states explicitly: "There is no finalized message contract between Jetsons and the 4070. Transport options on the table: MQTT, ZeroMQ, REST, gRPC. No decision yet." So the path choice the user wants to make an IV (Jetson → DB direct vs Jetson → 4070 → DB vs Jetson → 4070 with DB side-channel) is genuinely open.
- **No Cortex 4090 code in this repo.** `nodes/cortex_4090/__init__.py` is a one-line stub. There is a separate, untracked `Nexus-LLM-Runtime-4090/` directory holding a TRT-LLM compose (described as stale per the handoff, since the live stack is vLLM with Qwen3 30B-A3B). The Cortex runtime is alive but lives outside the Nexus repo proper and exposes an OpenAI-compatible HTTP endpoint.
- **No router or cache on the 4070.** No code that selects between hot/cold paths, no Redis or in-process LRU, no DB read aggregation, no batching of edge → DB writes. The brainstem currently behaves as a thin embed-and-forward shim.
- **No 4070↔4090 channel.** Nothing in the repo defines a callback channel or a queue between the two GPUs. The Cortex is currently addressed as a one-shot HTTP request from n8n workflows, not as a peer that can ask the 4070 follow-up questions. The bidirectional cooperation is research direction, not implementation.
- **No simulation environment, no Vector code, in the repo.** I searched. Out of tree.
- **Docs in `docs/` are stubs.** The real design lives in `automation/docs/cortex-design.md` and in the working-draft papers under `papers/`.
- **No load test exists.** `scripts/benchmark_inference.py` is zero bytes.

### Reading this honestly, and how it shapes the paper

The repo is in early bring-up. The handoff makes the current goal explicit: get the Jetsons returning data to the 4070 over Ethernet. NAS, consolidation, full topology, and Vector are downstream of that. Reframed as a fabric, what exists today is:

- A *write half* of the fabric, partially: edge stub → 4070 (text-only) → NAS, all synchronous HTTP.
- An *inference half* of the fabric, partially: an n8n-driven Cortex endpoint that workflows call directly, without going through the 4070 as a router.
- No closed loop between them.

Nexus started as an ad hoc ideal pulled together piecewise. The honest reframe is to treat it as an MVP build with measurement built into the build itself, not as a finished system waiting for a characterization run. That changes the paper's shape. The paper is now in the family of systems papers (think SoCC or EuroSys), with a section that describes the implementation as a contribution alongside the characterization. Phase 0 of this experiment IS that implementation, and is fully in scope.

This means Experiment 1 has two phases. Phase 0 builds the Minimum Viable Fabric to acceptance criteria stated quantitatively, and lights up per-component instrumentation as each component lands. Phase 1 is the canonical characterization sweep against the completed MVF, including the topology arms, IV sweeps, and pre-registered gating decision. Phase 0's rolling numbers are not a substitute for Phase 1; they are early-warning signal that lets us catch problems while we are still cheap to fix, rather than discovering them at the end of a multi-week sweep.

This is a systems-characterization paper. Not a "we beat X" paper. The deliverable is a reproducible envelope: under workload W on hardware H, the fabric sustains throughput T at p95 latency L, with stage utilizations and headroom values reported per stage, plus the implementation that produced it. That envelope and that implementation are the contribution.

### Open questions (do not guess, ask)

1. What is the canonical wire format(s) between Jetson and 4070, and between 4070 and NAS? Raw frames (H.264/H.265/MJPEG), feature tensors (NumPy/Arrow), already-embedded vectors, structured JSON events (per `cortex-design.md` IoT contract)? Each implies different payload sizes and latency floors.
2. What is the workload Vector or the next downstream inference experiment actually requires? Specifically: event rate, per-event payload size, target end-to-end latency budget *L*, target throughput *T*. We need this number to be real, not arbitrary.
3. Where does the simulation environment live? Repo path, separate project, or out-of-tree?
4. NTP vs PTP on the LAN. Per-hop latency at p99 needs sub-millisecond sync to be trustworthy. PTP-capable switch in the rack or not?
5. Is the 4070 expected to host its own LLM (Qwen3-4B per the automation env block) plus the embedding model plus the router plus the cache layer concurrently on 12 GB VRAM? If so, the VRAM split becomes part of the characterized envelope.
6. Are we allowed to implement the missing fabric pieces (router on 4070, callback channel) as part of Experiment 1? (Phase 0 of this design assumes yes. If the answer is no, Phase 0 collapses to instrumentation of what already exists, and Phase 1's topology-arm story drops to one arm.)
7. PCIe topology on the 4070 and 4090 hosts. Specifically: which PCIe generation and lane width each GPU is actually negotiating (Gen 3 x16 vs Gen 4 x16 vs Gen 4 x8 if a chipset lane fan-out is in play), and whether the two GPUs share a root complex or sit behind separate roots. The 4070↔4090 link's measured floor depends on this and we should not guess.

---

## 1. Phase 0: Minimum Viable Fabric

This section describes the implementation that has to exist for Phase 1 to be a meaningful characterization. It is framed as a system-implementation section, not a project punch list. Each component has an acceptance criterion stated as a measurable threshold, not a binary "it works." Each criterion is tied to what Phase 1 needs from the component, so a passing Phase 0 means a Phase 1 measurement against that component cannot be confounded by under-built infrastructure.

The MVF is the smallest set of components such that an end-to-end event can flow from an edge source through the 4070, into the DB, and that the 4090 can be invoked with a callback back to the 4070, all while every stage emits the probes Phase 1 will read. Phase 0 does not deliver every feature on the long-term roadmap; it delivers what is needed to make a single characterization arm trustworthy.

### 1.1 MVF components and acceptance criteria

**Component A: Jetson edge capture and push.** A real Jetson node running a minimal capture-and-push process. The capture stage produces synthetic or sensor-derived events at a configured rate and pushes them to the 4070 over the chosen wire format (TBD per §0 question 1). Each event carries a monotonically increasing sequence number and a high-resolution emit timestamp.

Acceptance: under a stable thermal envelope (junction temperature within 5 C of cold-start steady state), the Jetson sustains an offered rate of *R_jetson* events/s for 15 minutes with per-event push enqueue latency p95 ≤ *L_push* and zero unaccounted drops. *R_jetson* and *L_push* are anchored to whatever Phase 1's *T_offered* and *L* settle to in §3, with *R_jetson* equal to at least 1x *T_offered* per source. Phase 0's pass at 1x is the floor; Phase 1 pushes to 2x as part of the headroom criterion. Probes A1 (emit) and A2 (post-encode) are emitting structured records to the metric sink.

**Component B: 4070 router and stub cache.** A real router module on the 4070 (`nodes/brainstem_4070/router.py`) that inspects each incoming event, makes a routing decision, and dispatches. A cache layer (`nodes/brainstem_4070/cache.py`) is present and functional, even if it is a stub LRU with no hit-rate tuning yet. The router does not have to be smart, but it has to exist as a named code path with its own probes, so Phase 1 can measure routing decision latency and useful-work ratio against a real implementation rather than a guess.

Acceptance: at *T_offered* sustained for 15 minutes, the router's decision latency p95 is ≤ 5% of *L*; the cache returns hit-or-miss within p95 ≤ 1 ms; the 4070's overall ingress-to-dispatch p95 (probes 3 → 4 → 5 in §8) is ≤ 20% of *L*. The router is exercised across at least two route classes (e.g. "embed locally" vs "forward to 4090") so the routing code path is not vacuously trivial.

**Component C: 4090 inference stub with callback.** A real service on the 4090 (`nodes/cortex_4090/server.py`) that accepts requests over the agreed transport and can issue a callback to the 4070 for additional context. The stub does not have to host the production model; it can wrap a smaller test model or even return canned responses, as long as the callback handshake is real and timed.

Acceptance: the 4090 stub accepts requests at *T_offered* sustained for 15 minutes; round-trip p95 for a one-shot request is ≤ 30% of *L*; one-callback round-trip p95 is ≤ 50% of *L*; the callback returns reach the 4090 with link-level byte counts captured (probes 10, 11, 12 in §8).

**Component D: DB schema and ingestion.** The NAS-side schema and ingestion path are pinned. The semantic table accepts vectors of the agreed dimensionality with metadata fields used by the router; the episodic table accepts the metric event type defined in §8. Indexing decisions are recorded (cosine HNSW for semantic, plain append for episodic) and the schema is committed alongside Phase 0 code so future runs cannot drift.

Acceptance: at *T_offered* sustained for 15 minutes against an empty collection, NAS write p95 ≤ 15% of *L* and zero failed inserts. The same workload re-run against a 1M-vector preloaded collection shows write p95 within 2x of the empty-collection number. The schema document is in the repo, not in someone's head.

**Component E: Wire format decision.** The wire format on each leg (Jetson↔4070, 4070↔NAS, 4070↔4090) is chosen, documented, and frozen for Phase 1. Even if a later phase revisits the choice, Phase 0 commits to one configuration so the characterization is interpretable.

Acceptance: a one-page wire-format decision document exists in the repo, naming the format, the rationale, the rejected alternatives, and the conditions under which the choice would be revisited. No further criterion; this is a clarity gate, not a performance gate. The format is then enforced by code, not by convention.

**Component F: Clock sync.** NTP or PTP is configured across the Jetson, 4070, 4090, and NAS hosts. Skew is sampled every 30 seconds and recorded with every run.

Acceptance: 95% of skew samples across a 1 hour idle window show node-to-node skew ≤ 1 ms (NTP minimum) or ≤ 100 µs (if PTP is available). Maximum observed skew ≤ 5 ms. If this acceptance cannot be met, per-hop p99 in Phase 1 is reported with an explicit caveat and the conclusion validity section in §10 is updated accordingly.

**Component G: Metric harness.** The `bench/probes.py` + `bench/sinks.py` pair is implemented and lit up. Probes are deployed at every component boundary listed in §8. A run gets a UUID, a `runs.yaml` snapshot, and a structured per-run output directory.

Acceptance: a 5 minute idle-but-instrumented "null run" against a quiescent fabric produces a complete, valid metric log with zero ring-buffer overflows, sub-1% probe overhead measured against a probes-off control, and an `analyze.py` pass that emits the canonical paper figure set for an empty workload (the plots are mostly flat, but they are produced without error).

### 1.2 Out of scope for the MVF

Stated explicitly so we cannot scope-creep silently:

- *Topology arms B and C as separate implementations* are out of scope for Phase 0. The MVF implements one canonical arm (whichever Phase 0 commits to per §0 question 6). Arms A and C are Phase 1 *if and only if* the user wants the full comparison, and they get built as their own scoped follow-up.
- *Sim environment integration* is out of scope. Class B replays use pre-recorded sensor traces if available, or are deferred.
- *Vector-specific code* (drive control, building-map integration, safety supervisor) is out of scope.
- *Production-grade retry/backoff and circuit breaking* are out of scope; a single retry on transient failure is sufficient for Phase 0.
- *Consolidation / "sleep" node* is out of scope.
- *Memory schema versioning, decay, summarization* are out of scope.
- *Multi-camera or multi-Jetson scale-out* beyond 2 sources is out of scope for Phase 0; Phase 1 covers up to 8 concurrent sources as an IV sweep.
- *A learned compression or shorthand protocol on the 4070↔4090 link* is out of scope, per the rationale in §4.4: the link is bounded by PCIe characteristics and inter-host network, both physical floors.

Anything in this list that turns out to be load-bearing for measurement is promoted into the MVF with its own acceptance criterion, not added quietly.

### 1.3 Why these criteria and not others

Each MVF acceptance criterion is calibrated against what Phase 1 needs. Phase 1 measures end-to-end p95 ≤ *L* and per-stage headroom ≥ *K* × *T_offered* at every stage. For Phase 1 to interpret those numbers, each stage in Phase 0 has to clear a fraction of *L* at 1x *T_offered* and stay clean of obvious pathologies. The percentages chosen (5% of *L* for router decision, 15% for NAS write, 20% for 4070 ingress-to-dispatch, 30% for 4090 one-shot, 50% for 4090 one-callback) sum to roughly 1.2 *L*, which is over budget on purpose. Phase 1's job is to find which combination actually fits; Phase 0's job is to ensure no single stage is so far over budget that it dominates and tells us nothing about the rest. If a single Phase 0 stage cannot meet its budget, that stage is the first thing to fix; Phase 1 should not start until it does.

---

## 2. Rolling Characterization (Metrics Along the Way)

The user's preference, recorded explicitly so it shapes the implementation: he wants to watch numbers move as components land, not only at the end. This section describes how Phase 0 produces a time-series of fabric performance during the build, in a format that is comparable to Phase 1's eventual full sweep.

### 2.1 What lights up when

Each Phase 0 component, on the day its acceptance criterion passes, lights up a defined slice of the Phase 1 metric set. Specifically:

- **Component A passes** → Jetson push throughput, push enqueue latency, edge thermal, edge CPU. Probes A1, A2 emit. End-to-end latency at this point covers Jetson-only; the rest of the fabric is not in the loop yet.
- **Component B passes** → router decision latency, cache hit/miss, 4070 ingress-to-dispatch latency, 4070 CPU and GPU split by purpose (router vs other). End-to-end now covers Jetson → 4070-dispatch.
- **Component C passes** → 4090 one-shot and one-callback round-trip latency, link-level bytes-on-the-wire, round-trip counts, callback resolution latency. End-to-end now closes the loop: Jetson → 4070 → 4090 → back.
- **Component D passes** → NAS write latency, Chroma index size, episodic append latency, write degradation curve as collection grows. End-to-end covers the full write path.
- **Component E passes** → not a metric; a decision document. The format is then visible in the metric stream as a constant field on every event for the rest of the program.
- **Component F passes** → cross-node clock skew samples; per-hop latency becomes trustworthy at p99.
- **Component G passes** → the metric harness itself is the floor for everything else; this is the first component, and once it passes every later component's numbers are captured against the same format.

A small subset of the Phase 1 sweep (one topology arm, one offered rate, one payload size, one wire format, one run replicate) is re-run *every time a new component lands and passes its acceptance criterion*. This is the rolling characterization: a recurring micro-sweep that produces directly comparable numbers across the build. By the time Phase 0 is complete, the project has a time-series of fabric performance vs build state, which becomes a figure in the eventual paper showing how the envelope tightened as components landed.

The rolling micro-sweep is not Phase 1. It is a stripped-down version of the same measurement that lets us catch problems early. Phase 1 is still the canonical characterization and is still the gate.

### 2.2 Log format minimum

The rolling characterization is only useful if the numbers are comparable across builds. Minimum schema, deliberately not over-engineered:

A single JSON object per metric record, written to a per-run JSONL file. Stable required fields: `ts_monotonic_ns`, `ts_wall_iso`, `run_uuid`, `phase` (one of `"phase0"`, `"phase1"`), `build_state` (a short string identifying which MVF components are live, e.g. `"A+B+G"`), `topology_arm`, `wire_format`, `t_offered`, `event_seq`, `probe_id`, `stage`, `ingress_ns`, `egress_ns`, `payload_bytes`. Optional fields can carry resource snapshots and stage-specific extras. The schema is documented once in `bench/probes.py` and a `schema_version` field is included so future changes are detectable.

A per-run summary file (one JSON object per run) carries aggregate stats: p50/p95/p99 per stage, drop rate, throughput sustained, run duration, replicate index, pass/fail per acceptance criterion checked during that run, plus a copy of the `runs.yaml` configuration. This is what feeds the rolling time-series plot.

### 2.3 Dashboard, kept minimal

A static HTML report regenerated from the JSONL data after each run, no live dashboard required. Optional Prometheus + Grafana for someone who wants live monitoring during a long run, but the report-on-completion path is the floor. The point is to keep the instrumentation cost proportional to its value: enough to compare runs, not enough to become its own project.

---

## 3. Phase 1: Research Question and Hypothesis

### Research question

For the Nexus heterogeneous compute fabric, as built in Phase 0 (Jetsons as edge capture, 4070 as orchestrator-router-cache, NAS as memory substrate, 4090 as heavy inference, with bidirectional cooperation between 4070 and 4090), what is the performance envelope under defined workloads, and specifically, at the workload that Experiment 2 intends to run, does any stage saturate or does end-to-end latency exceed budget?

Plain version: how fast and how reliable is this fabric, where does it bend before it breaks, and at the load Experiment 2 needs, is anything in trouble.

### Hypothesis

**H1 (primary, falsifiable).** Under target workload *W* (offered event rate *T_offered*, payload distribution *P*, topology arm *A_canonical*), the completed MVF sustains throughput *T_offered* with end-to-end p95 latency ≤ *L* and no individual stage exceeds utilization *U_stage* over a 30 minute steady-state window. Per-stage headroom (max sustainable rate / target rate) is ≥ *K* on every stage.

**H0 (null, what we want to rule out).** Under workload *W*, at least one of the following is true at *T_offered*: (a) at least one stage saturates (utilization at or above *U_stage*), or (b) end-to-end p95 latency exceeds *L*, or (c) some stage's headroom multiplier is below *K*.

### Where the numbers come from

The numbers in H1 are placeholders until anchored to a real Experiment 2 workload. Defensible defaults until the user pins them down:

- *W* and *T_offered*: anchored to what Experiment 2 actually needs to run. If Vector demands a 30 fps perception loop on 2 cameras with feature-tensor payloads, *T_offered* is 60 events/s. Without that anchor, this number is parameterized across plausible values {15, 30, 60, 120, 240 events/s} and reported per-condition.
- *L*: latency budget. Same source of truth (the downstream task). Parameterized across {33 ms, 100 ms, 250 ms, 1000 ms} until Vector's actual budget is provided.
- *U_stage*: 80% per-core CPU sustained, 80% GPU SM-occupancy sustained, 80% NIC saturation. Standard headroom-engineering practice. A stage at 80% utilization at the target rate has detectable but not yet pathological queuing.
- *K* (headroom multiplier): proposed value 2.0. Justification: Experiment 2 will add model-side load on top of the workload we measure here. The 4090 in particular will see additional concurrent inference. 2x headroom means the fabric can absorb Experiment 2's marginal load without degrading p95 latency past *L*. 1.5 is too thin (no margin for thermal drift or warm-cache misses). 3.0 is defensible but expensive (requires testing at 3x target, which on the upper end of *T_offered* may saturate hardware and tell us nothing about Experiment 2's regime). 2.0 is the cheapest defensible choice. Open to revision once the Experiment 2 workload is concrete.

### Why this is the right hypothesis to test first

The standard mistake is measuring inference quality on a system you haven't characterized. Drops, queue stalls, and protocol thrash get blamed on the model. H1 names the three failure modes (saturation, latency violation, headroom violation) that would invalidate Experiment 2. Rejecting H0 by clearing all three is the gate. The hypothesis is system-shaped, narrow, and pre-registered.

H1 is also the only claim this paper makes. There is no comparison claim, no "better than" claim, no "punching above weight" claim. The contribution is the implementation (Phase 0) plus the reproducible envelope (Phase 1) plus the harness that produced it.

---

## 4. Independent Variables

Four blocks: topology, load, environment, link. Topology is the headline IV.

### 4.1 Topology arms

Compare at minimum three arms.

**Arm A: Edge-direct.** Jetson → DB direct write. 4070 reads from DB only when an inference request triggers it.

**Arm B: 4070-mediated.** Jetson → 4070 → DB. 4070 does ingest aggregation, batching, dedup, routing. DB downstream of 4070 on the write path.

**Arm C: Side-channel.** Jetson → 4070 for the hot path; DB updated as a side effect, asynchronously. Hot and cold paths decoupled.

The MVF in §1 implements one canonical arm. Arms outside the canonical require additional Phase 0 work, scoped separately. The canonical arm (today's nearest implementation match is a stripped-down Arm B) is the one Phase 1 sweeps in full; comparison arms are sampled if and only if the Phase 0 scope is extended to build them.

### 4.2 Load IVs

- Offered rate per edge source: {1, 5, 15, 30, 60} events/s.
- Concurrent edge sources: {1, 2, 4, 8}.
- Per-event payload size: small (~4 KB JSON event per the IoT contract), medium (~150 KB JPEG-ish), large (~1.5 MB raw VGA frame), huge (~6 MB raw HD frame).
- Wire format: {raw, JPEG q=85, H.264 keyframe-only, H.265 keyframe-only, feature tensor fp32, feature tensor int8}.
- 4070 batch size for embedding/router work: {1, 4, 16, 32, 64}.
- NAS contention: Chroma collection pre-populated to {empty, 10k, 1M, 10M} vectors.

### 4.3 Environment IVs

- Network: {clean LAN, +5 ms, +20 ms, 0.1% loss, 1% loss, jitter ±5 ms}, induced via `tc netem`.
- Concurrent background load on 4070: {none, 50% CPU pinned, GPU compute fraction 50%}.
- Concurrent background load on 4090: {none, secondary inference task}.

### 4.4 4070↔4090 link IVs (link is measured as-configured, not optimized)

A prior draft included a learned-compression or "shorthand protocol" sub-experiment on this link. That is dropped from Experiment 1. The rationale: data crossing the 4070↔4090 link is already tokenized at a level where further compression has negligible payoff. The dominant constraint is PCIe characteristics on each GPU's host plus the inter-host network, both of which are physical floors that software cannot move within the scope of this experiment. A learned-compression sweep would be measuring software effort fighting a hardware ceiling and would not produce a useful result. Tokens are treated as the transport unit. We measure the link as it is actually configured, rather than attempting to optimize it within Experiment 1.

What we still vary on the link:

- Round-trip pattern: {one-shot (no callback), one callback, multi-callback up to N=3}.

What we still report (descriptive, in §5.4): raw bytes-on-the-wire, round-trip count distributions, per-call latency. These are link characterization metrics, not protocol-comparison metrics.

### 4.5 Sweep design

Plackett-Burman or fractional factorial across the full set to identify which 4 to 5 variables drive most of the variance. Then full sweeps on those, holding the others at sensible defaults. Topology arm gets full sweeps in all configurations Phase 0 has actually built.

---

## 5. Dependent Variables and Metrics

Stratified by where they are measured.

### 5.1 End-to-end and per-stage timing (the core of H1)

- End-to-end latency p50/p95/p99/p99.9 (edge emit timestamp to "result available to downstream consumer" timestamp).
- Per-stage latency at every probe point (defined in §8).
- Queue dwell time and queue depth at every queue.

### 5.2 Throughput and reliability (the core of H1)

- Sustained events/second per arm.
- Maximum sustainable events/second before drop rate exceeds 0.1%.
- Per-stage headroom ratio (max sustainable / target).
- Drop rate, duplicate rate, out-of-order rate, reordering window.

### 5.3 4070 orchestration behavior (descriptive, supports characterization)

- *Routing decision latency*: time inside the 4070 spent on "which path / which model / which cache key" before any useful compute starts.
- *Cache hit/miss rates* and *cache lookup latency*.
- *DB lookup latency* contributed by routing-triggered reads.
- *Useful-work ratio*: per request, (time on embedding/inference/transcoding) divided by (total time inside the 4070). Reported. Not a pass/fail criterion in this paper.
- 4070 CPU and GPU utilization, broken out by purpose (router vs embedder vs cache vs LLM vs idle).

### 5.4 4070↔4090 link behavior (descriptive transport metrics, supports characterization)

- Raw bytes-on-the-wire per call and per query (link-layer counters, not just app-level payload).
- Tokens-per-decision (model tokens per actionable decision; useful as a workload descriptor, not as a compression-efficiency claim).
- Round-trips-per-query distribution.
- Callback resolution latency (4090 asks, 4070 fetches and replies).
- Convergence rate (fraction of queries resolving in ≤N callbacks for N in {0, 1, 2, 3}).
- Thrash signal (fraction of queries that exceed callback budget or oscillate).

These are transport characterization metrics. They describe the link under the as-configured token-passing scheme. They are not comparing protocol variants and they are not making a compression claim.

### 5.5 Resource pressure (cross-cutting)

Per-core CPU, per-GPU SM occupancy, VRAM used/free, RSS, disk I/O (Chroma writes, episodic appends, fsyncs), network bytes/s, retransmits, NIC ring drops, thermal junction temps, NVML power draw.

### 5.6 Cost-normalized performance (descriptive only)

Throughput-per-MSRP-dollar for the configured fabric is reported as a descriptive number alongside everything else. It is not a success criterion. It is not the paper's headline. It is included because future work may want to revisit it, and reporting it now costs nothing. We do not compare it to any external baseline in this paper; that comparison is left to future work where the workload definition can be controlled on both sides.

---

## 6. Stimulus / Workload Design

Three workload classes by fidelity, plus a callback-stressor class for characterizing the link.

**Class A: pure synthetic.** Generator script playing edge-source role. Configurable rate/size/codec. Sequence numbers and monotonic emit timestamps.

**Class B: recorded replay.** Pre-recorded sensor traces from a representative environment, replayed at controlled rates.

**Class C: live capture from a Jetson.** Once a Jetson is online (Phase 0 Component A), replayed against the same instrumentation.

**Class D: callback-stressor.** A workload that requires the 4090 to ask back for additional context multiple times per query. Designed to exercise the 4070↔4090 callback channel under load. Used to populate §5.4 metrics, not to prove any claim about whether the channel is "good."

**Stressor design per fabric element:**
- *Edge:* high rate, high resolution, low keyframe interval.
- *4070 router:* high cache miss rate, simultaneous embedding and routing load, VRAM contention.
- *4070↔4090 link:* large tensor payloads, high callback rate, deliberate bursts.
- *4090:* sustained inference at near-saturation, then with concurrent callback handling.
- *NAS:* pre-populated to 1M and 10M vectors; concurrent reads and writes.

**Reproducibility:** seeded synthetic generators, containerized runners with pinned hashes, run parameters in `runs.yaml` per run, output in `experiments/exp1/runs/<uuid>/`.

---

## 7. Controls and Confounders

**Warm-up.** First 60 seconds discarded. JIT, page cache, CUDA load, HNSW index warm-up happen there.

**Thermal steady state.** 5 minute hold before measurement. Confirm GPU temp flattened (<0.5 C drift over 60 s). Long-run thermal tests (30+ min) reported separately.

**Workload isolation.** No other interactive workloads on test nodes. Background services documented if they can't be stopped. Linux preferred over Windows where possible to reduce OS noise; document the platform per node.

**Clock sync.** NTP minimum, PTP preferred. Skew sampled every 30 s. Runs with skew > 1 ms rejected. Per-hop p99 caveated if PTP unavailable. (Calibrated against Phase 0 Component F.)

**Network determinism.** Pinned wired switch, jumbo frames consistent across nodes, `tc netem` applied at one well-defined point.

**Process pinning.** Brainstem, NAS, router containers pinned to cores. CPU frequency governor set to performance and documented.

**VRAM partitioning on the 4070.** The 4070 hosts embedder + small LLM + router + cache simultaneously per design. Document the VRAM split, pin it, treat over-subscription as a failure mode unless explicitly being tested.

**PCIe topology documented per run.** Record the negotiated PCIe generation and lane width for each GPU (`nvidia-smi -q -d PCI` gives current speed and width; `lspci -vvv` confirms the slot capability vs negotiated state), whether each GPU is on a CPU root complex or behind a chipset switch, and the inter-host network speed and switch model. These define the floor for the 4070↔4090 link and they must be reported alongside any link metric. A change in any of them invalidates the prior characterization.

**Deterministic callbacks.** When measuring the 4070↔4090 link under Class D, the callback pattern must be deterministic across runs (same prompts produce same callback graph) so configurations are comparable.

**Cross-validation recommendation.** Two places have genuine design ambiguity worth a second pass before code is written. First, the *useful-work ratio* categorization in §5.3 is partly definitional (when does cache lookup count as "useful"?), and a different reviewer will categorize differently. Pre-register the categorization. Second, the *headroom multiplier K=2.0* in §3 deserves sanity-checking against the Experiment 2 workload once that workload is concrete. Recommend running the design through a second analysis pass (different agent or different model) before any code goes in.

---

## 8. Measurement Plan

**Probe placement.** Every stage and queue boundary gets a probe. A probe records: probe ID, stage name, sequence number, ingress timestamp, egress timestamp, payload size in bytes, optional resource snapshot.

For the canonical arm:

1. Edge emit (Jetson or synthetic): on-emit timestamp.
2. Pre-transport encode.
3. Post-transport on 4070 ingress: HTTP request received.
4. 4070 router decision: pre-route, post-route.
5. 4070 cache lookup: pre, post, hit/miss flag.
6. 4070 DB read (if triggered): pre, post.
7. 4070 embedder: pre, post.
8. 4070 → NAS write: pre-call, post-response.
9. NAS ingress, post-Chroma-write, post-episodic-append.
10. 4070 → 4090 link: pre-send, post-send, payload size before and after codec.
11. 4090 model: pre-decode, post-decode, callback-triggered flag, per-callback timing.
12. 4090 → 4070 callback request: pre, post (both sides).
13. 4070 result available to consumer.

Comparison arms (when built) skip or add probes accordingly. The probe IDs and stage names are stable across arms so the metric schema in §2.2 carries everything.

The existing `core/nas_client.NASClient.log_event` can be repurposed: add a parallel `metric` event type with structured timing fields. NAS becomes the metrics sink, with a *separate* JSONL file from the live episodic log so the system under test isn't polluted.

**Sampling.** Full at low rates. 1-in-N at high rates (60 fps × 8 sources = 480 events/s → sample 1 in 10). Drops always counted in full.

**Logging.** JSONL, gzip on rotation, separate disk if possible.

**Observer effect.** Use `time.monotonic_ns()` or `clock_gettime(CLOCK_MONOTONIC_RAW)`. No string formatting in the hot path. Buffer-and-batch the JSONL writer. A "probes-off" control run measures probe overhead; report it.

**Concurrency.** Dedicated metrics thread per service, ring-buffered. Buffer overflow during a run invalidates that run.

**External tooling.** `nvidia-smi` logging per GPU. `pidstat` per service. `iftop`/`nethogs` on each node. Optional `node_exporter` + Prometheus + Grafana for live dashboards.

**Link-layer counters for §5.4.** Capture link-layer byte counts on the 4070↔4090 interface, not just app-level payload sizes. TCP overhead and framing matter for accurate transport reporting. Wireshark or `bpftrace` on the link is appropriate. Capture PCIe transfer counts on each GPU host as well (NVML `nvmlDeviceGetPcieThroughput`, or vendor counters via `nvidia-smi dmon`) so the GPU↔host legs are visible alongside the inter-host network.

---

## 9. Success Criteria

### 9.1 Phase 0 acceptance (precondition for Phase 1)

Every Phase 0 acceptance criterion in §1.1 must pass on three consecutive runs at the relevant Phase 0 workload before Phase 1 begins. Pass/fail is determined per-component, with the gating component being whichever criterion fails most recently. The rolling characterization in §2 produces a continuously updated dashboard of where the build stands relative to these criteria, so the team is not surprised at the end.

### 9.2 Phase 1 success (the gate to Experiment 2)

We claim the fabric clears the Experiment 2 gate if *all* of the following hold under target workload *W*, on the canonical topology arm, sustained over a 30 minute window, on Class A workload, replicated on Class B:

1. **No stage saturates.** At *T_offered*, every stage's utilization is < *U_stage* (default 80%) sustained.
2. **Latency holds.** End-to-end p95 ≤ *L* and p99 within 2x of p95.
3. **Headroom.** Every stage's max sustainable rate is ≥ *K* × *T_offered* (default *K* = 2.0).
4. **Reliability.** Drop ≤ 0.1%, out-of-order ≤ 0.5%, duplicates ≤ 0.01%.

If all four hold, three "warning" indicators do not fail the gate but flag risk for Experiment 2:
- Any queue dwell p99 > 20% of *L*.
- Any thermal throttle event during the 30 minute window.
- Per-core CPU > 80% sustained on the 4070 or 4090 (not the same as stage utilization; this is the OS-level cross-cutting view).

If a warning fires, Experiment 2 can proceed with the condition documented as a caveat.

Cost-normalized performance, 4070 orchestration behavior, and 4070↔4090 link behavior are all *reported* alongside the gate, but they do not gate Experiment 2. The gate is purely about whether the fabric can carry the load Experiment 2 will impose without itself being the bottleneck.

**Numeric headroom is non-negotiable.** A fabric that just barely meets latency at exactly the target rate falls over the moment Experiment 2 adds model-side load. The *K* = 2.0 multiplier is the firewall, and it is defended in §3.

---

## 10. Threats to Validity

**Internal validity** (does the experiment measure what it claims):
- *Observer effect from probes.* Mitigation: monotonic probes, probes-off control, reported overhead.
- *Clock skew.* Mitigation: NTP/PTP per Phase 0 Component F, skew sampling, reject runs above threshold.
- *Warm-up contamination.* Mitigation: 60 s discard, 5 min steady-state.
- *Confounding across the factorial sweep.* Mitigation: Plackett-Burman screening before full sweeps.
- *Comparing arms with different code paths.* Mitigation: shared instrumentation harness, same metric definitions, document arm-specific probes.
- *Phase 0 build-state confound on rolling characterization.* Mitigation: every rolling run carries an explicit `build_state` field (§2.2). The time-series is read as "envelope vs build state," not as a single envelope claim. The headline envelope is Phase 1's, against a fully built MVF.

**External validity** (does the result generalize):
- *Synthetic workload may not match real distributions.* Mitigation: Class B + Class C as cross-checks.
- *Single hardware configuration.* Mitigation: explicitly document the rig. Vector deployment on different kit needs its own characterization.
- *Bench network vs deployed network.* Mitigation: `tc netem` brackets the regime; report bands.
- *Target workload *W* may not match what Experiment 2 actually runs.* Mitigation: anchor *W* to Experiment 2's pre-committed workload definition. If *W* shifts, rerun Experiment 1.
- *PCIe topology and inter-host link define a hard floor on the 4070↔4090 leg.* Document for each GPU host: PCIe generation and negotiated lane width (the 4090 in a chipset slot can silently negotiate Gen 4 x8 rather than Gen 4 x16, and a 4070 in a non-CPU lane can do the same), whether the GPU sits on a CPU root complex or a chipset root, and the inter-host network speed and switch. Report Phase 1 link results in the context of this floor. A future change in either host's PCIe topology or in the inter-host network invalidates the numbers and requires a re-characterization.

**Construct validity** (do the metrics represent what we care about, and is the architecture novel enough that "this fabric is characterized" can be confused with "this specific implementation happens to behave this way on this specific workload"):
- *"Latency" can mean many things.* Be explicit: end-to-end means edge-emit to consumer-result. Other definitions reported separately.
- *"Drop" vs "delayed past timeout."* Explicit timeout policy, count delayed-but-arrived separately.
- *"Useful-work ratio" categorization is partly definitional.* Pre-register what counts as useful (router code = overhead; embedder code = useful; cache lookup = overhead unless hit produced avoided DB cost, in which case credit at hit rate × avoided cost). Document in the paper.
- *Architecture novelty risk.* The fabric framing is new enough that "the fabric is characterized" risks being confused with "this specific implementation works on this specific workload." Mitigation: explicitly scope the paper's claims to this implementation on this workload on this hardware. The pattern's generality is explicitly future work, not claimed here. Report enough implementation detail (Phase 0 is the implementation section) that someone else can reproduce or refute the envelope.
- *4070↔4090 link metrics are descriptive only.* The link is characterized as-configured. No protocol-comparison or compression claim is made. If readers attempt to infer such a claim from the descriptive numbers, the discussion section should explicitly disclaim it and point at the PCIe-and-network floor in the external-validity entry above.

**Conclusion validity** (are the statistical inferences sound):
- *Single-run variance.* Mitigation: ≥3 replicates per condition, bootstrap CIs.
- *Run order effects.* Mitigation: randomize within blocks, document block boundaries.
- *Multiple comparisons across the factorial.* Mitigation: Bonferroni or Benjamini-Hochberg corrections where the paper makes per-condition assertions.

---

## 11. Required Instrumentation and Code Changes

This is what would need to land in `project-nexus` to run the experiment. Most of it does not exist today. The list is organized by Phase 0 component so it maps onto the build plan in §1.

**Phase 0 Component G (metric harness, lands first):**
1. `bench/probes.py`. Probe helper. Monotonic timestamp wrappers, batched JSONL flush, stable schema per §2.2.
2. `bench/sinks.py`. Metric sinks (JSONL, optional Prometheus, optional NAS metric event).
3. `bench/runner.py`. Orchestrates a run: netem setup, service start, emitter, teardown, log collection.
4. `bench/analyze.py`. Post-run analysis. Computes per-stage stats and canonical paper figures, including the rolling-build time-series figure.

**Phase 0 Component A (Jetson edge):**
1. `nodes/jetson_peripherals/capture.py`. New. Capture loop with monotonic timestamps and seq numbers.
2. `nodes/jetson_peripherals/push.py`. New. Push to the 4070 over the chosen wire format (per Component E).

**Phase 0 Component B (4070 router and stub cache):**
1. `nodes/brainstem_4070/router.py`. New. The routing layer. Pluggable so additional topology arms can swap it if built later.
2. `nodes/brainstem_4070/cache.py`. New. In-process or Redis-backed cache layer.
3. `nodes/brainstem_4070/cortex_client.py`. New. 4070-side client to the 4090. Implements the callback-capable request/response over the as-configured token-passing transport. Not pluggable across protocol variants; we measure the link as-configured.
4. `nodes/brainstem_4070/server.py`. Modify: add probe hooks, add `/metrics` endpoint.

**Phase 0 Component C (4090 stub with callback):**
1. `nodes/cortex_4090/server.py`. New (the directory is empty today). Wraps a small test model or canned-response stub with the callback-capable contract.
2. `nodes/cortex_4090/callback.py`. New. The 4090-asks, 4070-answers handshake.

**Phase 0 Component D (DB schema):**
1. `nodes/nas_memory/server.py`. Probes at HTTP ingress, before/after Chroma `add`, before/after episodic append.
2. `nodes/nas_memory/schema.md`. New. Documented schema for semantic and episodic tables, including the metric event type.
3. `core/nas_client.py`. Add async/batched mode; the current per-write POST will bottleneck before anything else.
4. `nodes/brainstem_4070/embed.py`. Expose batch size and device as config; today they're hardcoded.

**Phase 0 Component E (wire format decision):**
1. `docs/wire-formats.md`. New. One-page decision document per Component E's acceptance criterion.

**Phase 0 Component F (clock sync):**
1. `infra/chrony.conf` or `infra/ptp.conf` plus host-specific service files. New.

**Workload generators (used by both rolling Phase 0 micro-sweeps and Phase 1):**
1. `bench/synthetic_emitter.py`. Class A workload generator.
2. `bench/replay.py`. Class B recorded-replay player.
3. `bench/callback_stress.py`. Class D, drives multi-callback queries against the 4070↔4090 link.

**Compose and tooling:**
1. `docker/docker-compose.yml`. Add metric volume mounts; add `cap_add: NET_ADMIN` if `tc netem` runs inside compose, else run bench host outside Docker.
2. `nvidia-smi` logger service per GPU node.
3. A dedicated bench host running the emitter and collecting results.

**Rough scope:** Phase 0 is 3 to 5 weeks of focused engineering for one person on the codebase, with rolling micro-sweep numbers landing every few days. Phase 1 is a further 2 to 4 weeks of run time and analysis on top of that, depending on how many topology arms are in scope.

---

## 12. Experiment 2 Sketch (Inference Quality, gated)

Only enough to show how Experiment 1's success criteria feed it.

**Goal.** Measure the inference quality of the model(s) on the fabric against ground-truth-labeled data, while the fabric runs at production-realistic load with the configuration validated in Experiment 1.

**Metrics.** Task-dependent. For object detection on building-management video: mAP@0.5 and mAP@0.5:0.95, per-class precision/recall, false positive rate per minute. For embedding quality on retrieval: recall@k, MRR on a held-out semantic set. For control closure if Vector is in scope: time-to-detect for safety events, end-to-end action latency, false-alarm rate.

**Ground truth.** Either a public benchmark replayed through the fabric (most defensible) or in-house labels on Vector-relevant data (more relevant, harder to audit). Ground-truth timestamps must live in the same clock domain as Experiment 1's probes so quality degradation correlates with concrete fabric events.

**Where the model lives.** Per current design: brainstem holds embedding model (BGE-large now, possibly a small vision model later) and a small LLM (Qwen3-4B planned). Cortex holds the heavy LLM (Qwen3 30B-A3B today, Qwen2.5-Coder-32B in the planning doc). A perception model proper for vision tasks does not yet live anywhere in the repo. Experiment 2's design depends on what model goes where.

**Critical dependence on Experiment 1.** If Phase 1's H1 is not cleared, Experiment 2's quality metrics will show degradation that has nothing to do with the model. The point of Experiment 1 is to make Experiment 2 interpretable.

---

## 13. The Gating Decision

There are now two gates: Phase 0 gates Phase 1, and Phase 1 gates Experiment 2.

### 13.1 Phase 0 gate (precondition for Phase 1)

**Proceed to Phase 1 if:** every Phase 0 acceptance criterion in §1.1 has passed on three consecutive runs at the relevant Phase 0 workload, and the rolling characterization in §2 shows no degradation trend in the most recent three builds.

**Hold Phase 1 if:** any Phase 0 acceptance criterion fails on more than one of three runs. The failing component is named, fixed, and re-tested before Phase 1 starts. The rolling characterization should have flagged this well before three consecutive failures, which is the point of running it continuously: we fix things in flight, not at the end of a Phase 1 sweep that would otherwise burn days on a misconfigured fabric.

### 13.2 Phase 1 gate (precondition for Experiment 2)

**Proceed to Experiment 2 if:** at the agreed *T_offered* and *L*, on the canonical topology arm, the fabric sustains a 30-minute Class A workload with: every stage utilization < *U_stage* sustained at *T_offered*; end-to-end p95 ≤ *L* and p99 within 2x of p95; every stage's max sustainable rate ≥ *K* × *T_offered* (*K* = 2.0); drop ≤ 0.1%, out-of-order ≤ 0.5%, duplicates ≤ 0.01%; conditions replicate within tolerance on Class B; ≥3 replicates of every condition pass with bootstrap 95% CIs not crossing thresholds; no more than one of the three warning indicators is active.

**Stop and fix the fabric if:** any one of: at least one stage saturates (utilization ≥ *U_stage*) at *T_offered*; p95 > *L*; some stage's headroom multiplier < *K*; drop > 0.1%; out-of-order > 0.5%. Failure on any condition on more than one of three replicates. Failure mode named (which arm, which IV combination, which stage, which probe) and fed back into a targeted fix before Phase 1 is rerun.

The middle case (some conditions pass, some don't) is fail. There is no soft pass. Pre-registering the criteria removes the temptation to rationalize a marginal result. If Phase 1 doesn't pass cleanly, Experiment 2 waits, and we publish Phase 0 + Phase 1 by itself as a systems-and-characterization paper.

---

## 14. Reasonable Next Step

Before any code: answer the open questions in §0. Priority order:

1. The downstream workload anchor: what does Experiment 2 (or Vector, or both) need? Specifically *T_offered*, payload distribution, *L*. Without these, all the placeholders in H1 and the Phase 0 acceptance criteria stay placeholders.
2. The wire format(s) between Jetson and 4070, between 4070 and NAS, and between 4070 and 4090.
3. Whether the missing fabric pieces (router, cache, callback channel) are in scope for Phase 0.
4. The NTP vs PTP situation on the LAN.
5. PCIe topology and inter-host network. Needed before any 4070↔4090 link numbers can be interpreted.

After those answers: a v0.6 that locks one *T_offered*, one *L*, one canonical wire format per leg, and the as-configured 4070↔4090 transport spec. Then Phase 0 starts, with Component G (the metric harness) first, because everything else's rolling numbers depend on it. Each later Phase 0 component lands, its acceptance criterion is checked, and the rolling micro-sweep re-runs. By the time the last Phase 0 component passes, the project has a continuous trace of "fabric performance vs build state" and is ready for Phase 1.

A second pass through this design by an independent agent or model before any code goes in is recommended, specifically on three points: (a) the *useful-work ratio* categorization in §5.3, where a second reviewer will categorize differently; (b) the headroom multiplier *K* = 2.0 once *T_offered* is concrete; (c) the per-stage *U_stage* threshold, which is a defensible default but worth a sanity check against the actual hardware's queuing behavior. These three are the places where one line of reasoning is most likely to drift, and the cost of cross-checking is low.

The paper this experiment produces is a systems-and-characterization paper. The contribution is the implementation (Phase 0), the reproducible envelope (Phase 1), and the harness that produced both. No comparison claims, no "better than" claims. A defensible map of how we built the fabric, where it performs, and where it bends.

For the canonical arm:

1. Edge emit (Jetson or synthetic): on-emit timestamp.
2. Pre-transport encode.
3. Post-transport on 4070 ingress: HTTP request received.
4. 4070 router decision: pre-route, post-route.
5.
