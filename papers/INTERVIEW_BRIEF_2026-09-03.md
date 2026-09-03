# Nexus interview brief

Date: 2026-09-03. Sources: the three drafts in `papers/`, `docs/architecture_v2_family_of_models.md` (ACCEPTED 2026-07-25), `docs/memory_system.md`, the Sprint 3d integration results, and the Sprint 5 + 6 implementation merged 2026-09-02 (#13, #14).

This is the talk track, not the papers. Four lengths: 30 seconds, 2 minutes, one section per paper, and the answers for when they push. The last section lists the revisions the papers and repo need.

## The 30-second pitch

Nexus is a household of persistent AI family members running on my own hardware. Each member is a model plus a written constitution plus a private memory of every conversation it has had with us. Members share a household memory that the home's sensors feed. Privacy is the default and sharing is an explicit act enforced by provenance metadata at the retrieval layer, not by the model. The part I care most about: a member's identity lives in its spec and its memory, not in its weights, so I can swap the model underneath and the member survives. That claim started as a paper. Sprint 5 turned it into code.

## The 2-minute version

Nexus started in 2025 as a biologically inspired architecture: Jetson edge devices as nerves, a 4070 as brainstem, a NAS as hippocampus, a 4090 as cortex, and a planned sleep node for consolidation. I wrote three drafts around it: the architecture itself, a framework for continuity of self in memory-bearing agents, and a piece on containerized agents as portable, replicable units.

By mid-2026 the original bet had lost. Splitting one model across the 4090 and 4070 is slower than offloading to system RAM on the 4090 host, and llama.cpp now does that offload natively. Frontier labs shipped the inference side of the thesis. So I wrote a decision record on 2026-07-25 and reshaped the project around what commodity hardware can offer that a hosted model cannot: identity, memory, provenance, and physical grounding in one home.

The V2 shape is a hub on the 4070 (auth, member routing, scope-filtered retrieval, write-on-turn, a durable inbox per member), an embedder service with Chroma next to it, a model manager on the 4090 that stages GGUF weights across hot, warm and cold storage tiers and runs one llama-server for whichever member is awake, and a NAS for the episodic log and cold weights. Memory has three scopes: private per member, shared household, and experiential (reserved for a member's own sensor platform). The scope filter is built server-side inside the embedder. There is no query-all path, so cross-member recall is structurally impossible through the API. The first member, Vera, runs Qwen3-30B-A3B at Q4 on the 4090. Jeffery, a dense 8B concierge on the 4070, holds messages for sleeping members and writes their wake-up briefing from shared scope only. He cannot read private memory by construction, and the tests plant a private row and assert it never surfaces.

Adding a second member is a data operation: download a GGUF, write a registry entry and a spec file. No code change.

## The build, in one diagram

```
people (CLI / web)
      |  Bearer token, X-Session-Id
      v
+---------------------------- 4070 host ---------------------------------+
|  NEXUS HUB (brainstem_4070)   BUILT                                    |
|  auth (argon2id / scrypt) | member router | scope-filtered retrieval   |
|  write-on-turn | per-member inbox (202 + Retry-After) | metrics JSONL  |
|       |                                  |                             |
|       | embed / query / promote          | briefing (shared scope only)|
|       v                                  v                             |
|  EMBEDDER (bge-small, 384-d)     JEFFERY concierge   BUILT (V1.5)      |
|  + Chroma, scopes.py filter      Qwen3-8B Q5, T0 tools only           |
|  BUILT                                                                  |
+------------------------------------------------------------------------+
      |  presence: asleep -> waking -> awake        ^ sensor events
      v                                             |  (seam BUILT, Jetsons
+------ 4090 host ------+                   +-------+--------+   not running)
| MODEL MANAGER  BUILT  |                   | JETSON household|
| ensure_hot() tiering  |                   | feed  PLANNED   |
| llama-server per      |                   +-----------------+
| member (Vera, 30B-A3B)|
+-----------------------+
      |  cold weights, episodic log
      v
+------ NAS -----------+       +-- CONSOLIDATION / sleep node --+
| episodic store BUILT |       | re-embed, cluster, summarize    |
| hot 2TB Gen4 / warm  |       | PLANNED (package is empty)      |
| 1TB Gen2 / cold 6TB  |       +---------------------------------+
+----------------------+
```

Legend: BUILT means code plus tests in the repo and merged to main. "Seam built" means the hub endpoint and the embedder path exist and are tested with stubbed hardware. PLANNED means an `__init__.py` and a design doc.

## Paper 1: The Persistence of Self

**The claim.** Identity lives in structure, not weights: semantic memory, episodic history, schemas, values. Replace the model and identity persists; delete the memory and it dies. The paper proposes a continuity protocol: snapshot the identity structures, rebind the new model to them, validate self-recognition and value preservation, rehearse, reset only transient state, revert on failure.

**What got built.** This is the paper that came true. `family/registry.yaml` plus `family/vera/spec.md` are the constitution, versioned in git because they are the identity. Private Chroma scope per member is the memory. The model manager swaps weights and reports presence. `scripts/migrate_memory_scopes.py` grandfathers every pre-V2 memory into member #1's private scope, which is the "snapshot and rebind" step of the protocol executed against real data. Sessions are hub-minted per (person, member) pair and persisted server-side.

**What is not built.** The validation step (self-recognition and value-preservation tests after a model swap) and the rehearsal step. Those are the natural next bench task: swap Vera's weights, run her report card, confirm she still recognizes her own history.

**How to say it.** Lead with the operational version: decouple identity from model, keep the identity layers immutable across upgrades, treat a model upgrade as a neural augmentation with a fallback. The draft's register (the AI race, recursive self-improvement, singularity trajectories) is a liability in a hiring room unless the interviewer opens that door. The one-line version: "I wanted a system where upgrading the model is not a death, and I built the memory layer so that is true."

## Paper 2: Nexus, a biologically inspired distributed architecture

**The claim.** Map cognition onto heterogeneous consumer hardware: Jetsons as peripheral nerves, a 4070 brainstem that filters and gates, a NAS hippocampus with decay, a 4090 cortex that reasons, a sleep node that consolidates. Forgetting is a feature.

**What got built.** The 4070 node exists and does most of what the brainstem section promised: validation (auth), gating (scope filter), short-term buffer (write-on-turn, retrieve-before-generate with top-k 5), embedding (bge-small-en-v1.5, 384 dimensions, roughly 133 MB, CPU inference). The NAS episodic store exists. The 4090 runs the reasoning model. The 503 cortex-down contract with `Retry-After` exists and is tested, and it generalized into the member-loading contract.

**What the repo falsified.** The core thesis of Section 1, that value comes from distributing one cognition across GPUs. The V2 decision record calls multi-GPU tensor splitting a confirmed dead end. The 4070 stayed valuable as the always-on hub, not as half of an inference fabric. The sleep node and the Jetson classifier remain designed, not running. Forgetting and decay are described in the paper and not implemented anywhere.

**How to say it.** As a strength: "I ran the experiment, it lost, I wrote the decision record, and I kept the ninety percent of the code that still applied." Interviewers hire for that more readily than for a thesis that never met reality.

## Paper 3: Containerized Intelligence

**The claim.** Containers are a computational membrane: a portable, self-contained payload that runs only on compatible hosts, replicates through orchestration, mutates through fine-tuning, and forms an ecosystem. The paper uses viral propagation as the lens and ends on symbiosis, not parasitism.

**What got built.** Three services on the 4070 under docker compose with named volumes as the unit of backup. The registry makes a member a portable payload: a GGUF, a quant, a context length, an offload policy, a spec file. Host compatibility is literal (llama.cpp on a card with enough VRAM plus RAM). Replication is a registry entry. Mutation is designed as LoRA on the member's own scopes, gated by the bench harness with pre-registered win conditions so a member that studied but regressed does not ship. The immune system the paper asks for in Future Directions arrived as the trust tiers: T0 custody, T1 read-only research earned by at least 20 scored tasks with rolling followed-brief of 4.0 or better and zero provenance violations, T2 writes only by explicit human approval, automatic demotion on any violation.

**How to say it.** Say "portable, replicable, host-constrained agent units" and let the interviewer bring up viruses if they want to. The paper's own conclusion is the safe version: modularity, portability, adaptation and propagation are the durable principles; the technology underneath will change.

## If they push

- "Is the consolidation node live?" No. The package is an `__init__.py`. Designed, scheduled after two members exist.
- "Are the Jetsons running?" No. The hub endpoint and the embedder path for born-shared sensor events are built and tested with stubbed hardware. Hardware bring-up is Phase 2.
- "What do the benchmarks say?" The bench harness exists with pre-registration discipline (win condition declared before the run, bootstrap CIs, guard-task regression tolerance). The only committed result artifact is a pipeline-shape demo against a stub provider. No real model result is published yet.
- "How do you know privacy holds?" The filter is unconditional and server-side in `nodes/embedder_4070/scopes.py`, pure functions with their own unit tests. Cross-member writes are rejected with 400 before Chroma is touched. The briefing builder has no code path into a private scope and the test plants a private row to prove it.
- "Why one model resident at a time?" 24 GB on the 4090. Co-residency of two large members loses to queue-and-swap, and the inbox with a 202 contract means a message to a sleeping member never hangs.
- "Why MoE for Vera and dense for Jeffery?" MoE (30B total, roughly 3B active) gives near-small-model speed at 30B quality when all experts fit in 24 GB. On the 4070's 12 GB, total-weights residency is the constraint, so a dense 8B at Q5 beats any MoE that fits.
- "What is the security posture?" Bearer tokens hashed with argon2id (scrypt fallback), the brainstem bound to the Tailscale interface only, status endpoints anonymous, everything that generates or writes authenticated, per-request token attribution in the metric record.

## Do not say

- Do not cite the best-of-8 "+100 pp lift". It is a StubProvider demo whose own README calls it the worst number to compare a real run against.
- Do not repeat the architecture paper's "preliminary observations indicate that distributed cognition reduces hallucinations". Nothing in the repo measured that.
- Do not call the papers published. They are 2025 drafts with an empty Results section and an empty References section. If an interviewer has read them, say so first: "those are drafts; here is what has been measured since."

## What is actually measured

| Evidence | Value | Where |
|---|---|---|
| Test functions in the repo | 159 | `tests/` |
| Hermetic integration suite, all green | 24 tests: auth paths, cortex-down contract, cross-session recall, metrics attribution | `docs/sprints/SPRINT_3d_INTEGRATION_RESULTS_2026-06-18.md` |
| Fabric round trip 4070 to 4090 over Tailscale | avg 23 ms, 0 percent loss | `docs/sprints/SPRINT_3d_CARD2_FABRIC_BRINGUP_2026-06-19.md` |
| Embedder | bge-small-en-v1.5, 384-d, 512-token max, CPU | `docs/memory_system.md` |
| Chunking lock | threshold 450 tokens, target 400, overlap 50 | `docs/memory_system.md` |
| Member #1 | Qwen3-30B-A3B-Instruct-2507, GGUF Q4_K_M, 32k context | `family/registry.yaml` |
| Concierge | Qwen3-8B, GGUF Q5_K_M, 8k context, 4070-resident | `family/registry.yaml` |
| Weight tiers | hot 2 TB NVMe Gen4, warm 1 TB NVMe Gen2, cold 6 TB HDD | V2 doc Section 7 |
| Per-load metrics | `stage_copy_ms`, `load_ms`, presence transitions | `nodes/model_manager_4090/manager.py` |

## Suggested revisions (papers and repo)

Papers:

1. Architecture paper: rewrite Section 1 so the thesis is identity, memory and provenance on commodity hardware, and move the distributed-inference bet to a "what we tried first" subsection with the 2026-07-25 decision record as the citation.
2. Architecture paper: replace the empty Results with the table above, delete the "preliminary observations" sentence, and fill References (SOAR, ACT-R, LIDA; complementary learning systems, McClelland et al. 1995; hippocampal replay literature; llama.cpp offload).
3. Persistence paper: add the built continuity protocol as a case study (registry, spec, scoped memory, migration script, presence states) and name the two unbuilt steps. Tone down Sections 1.2 and 6.5 for any audience that is not already inside the argument.
4. Containerized paper: retitle the framing to portable agent units, fold the V2 trust tiers into the "security models inspired by immunology" direction it promised, and keep the AI-drafting disclosure.
5. All three: strip the em-dashes (the repo's own README rule since 2026-05-20) and the smart quotes that the export introduced.

Repo:

6. `docs/architecture.md` still labels V2 "proposed"; the V2 doc is ACCEPTED and Sprints 5 and 6 merged 2026-09-02.
7. `readme.md` points the marketing site at projectnexuscode.org; confirm whether paradigm.codes is now canonical.
8. `docs/node_details.md` is empty (0 words) while `docs/architecture.md` sends readers to it.
9. `reqirements.txt` is misspelled at the repo root.
10. The local checkout at `C:\dev\project-nexus` is access-denied to this session even with the sandbox off (ReadOnly attribute, `icacls` fails). This brief was built from a fresh clone of `Ginkobaloba/ProjectNexus`.
