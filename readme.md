# Project Nexus

A distributed cognitive architecture built across heterogeneous hardware: Jetson edge devices, a 4070 "brainstem" node, a NAS-backed long-term memory substrate, and a 4090 "cortex" reasoning engine.

Nexus models concepts from biological cognition (perception, filtering, memory consolidation, hierarchical reasoning) as a modular, containerized system. It is not a single model; it is an ecosystem of cooperating processes.

## What Nexus explores

- Distributed synthetic cognition across commodity GPUs and edge devices
- Persistent identity structures over long time horizons
- Long-term memory substrates for LLMs (semantic, episodic, schema-driven)
- Multi-node orchestration with low-latency cross-device inference
- Memory filtering, abstraction, and decay
- Safe agent behavior via layered gating and instinctual rules

## Architectural model

Biological intelligence is distributed. Nerves preprocess. The brainstem filters. Memory consolidates. The cortex reasons. Nexus recreates that division of labor in software.

### Components

1. **Jetson nodes (peripheral nervous system).** Capture raw video, audio, telemetry. Perform early filtering and compression. Push signals to the brainstem.
2. **4070 node (brainstem).** Validates incoming signals, generates embeddings, applies instinctual rules, buffers short-term memory, and decides what is important enough to consolidate. Since Sprint 5 it also serves as the **Nexus Hub**, the family-of-models orchestration layer: `GET /family` (roster + presence + queue depths), `GET /members/{id}` (spec summary, presence, model info), `POST /members/{id}/chat` (`200` for a live reply, `202` + `msg_id` when the message is queued, `503 member_loading` + `Retry-After` when the member is waking up), `POST /members/{id}/presence`, `GET /members/{id}/inbox/{msg_id}` (poll a queued message's reply), and `POST /members/{id}/memory/promote` (share a private memory to the household). See `docs/architecture_v2_family_of_models.md` for the full design.
3. **NAS (long-term memory).** Vector database for semantic memory, time-ordered episodic logs, knowledge graph structures, decay and deduplication. Synthetic hippocampus.
4. **4090 node (cortex).** Hosts large-scale LLM reasoning, executes high-level planning, integrates episodic and semantic recall, and orchestrates downstream agents.
5. **Model manager (4090 node, Sprint 5).** `nodes/model_manager_4090/` — owns weights placement and the `llama-server` lifecycle for whichever family member is resident. Tiers weights hot/warm/cold (NVMe Gen4 / NVMe Gen2 / HDD) via `ensure_hot()` staged, checksum-verified copies, since llama.cpp does not tier for us; loads/unloads `llama-server` per member and reports presence (`waking`/`awake`/etc.) back to the hub.
6. **Consolidation engine (sleep node).** Re-embeds old memories, clusters and abstracts concepts, summarizes logs into narratives, enforces schema consistency, runs "synthetic dreams".

## Research

Nexus is developed alongside three research works covering:

- Synthetic continuity and identity persistence
- Biologically-inspired distributed cognition
- Containerized intelligence and propagation patterns

Drafts live in `papers/`.

## Roadmap

**Phase 1: core bring-up.** Inter-node message bus, Jetson to 4070 to NAS pathway, vLLM / llama.cpp on the 4090, memory schemas and storage logic.

**Phase 2: multi-node coordination.** Real-time sensory processing, brainstem instinct engine, semantic and episodic write pipelines, cortex RAG integration.

**Phase 3: autonomous consolidation.** Replay cycles, schema enforcement, summarization, daily sleep routines.

**Phase 4: safety and alignment layer.** Rate limits, instinctual rules, safe-operation constraints, preference stability.

## Contributions

Nexus is an evolving research-grade architecture. Contributions, ideas, and code reviews are welcome as the system matures.

## Contact

- Author: Andrew "Drew" Mattick
- GitHub: [Ginkobaloba](https://github.com/Ginkobaloba)
- Marketing site: [projectnexuscode.org](https://projectnexuscode.org)

## License

See `LICENSE`.
