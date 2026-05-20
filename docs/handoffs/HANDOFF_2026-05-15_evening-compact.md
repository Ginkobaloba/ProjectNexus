# Handoff: 2026-05-15 evening compact

Short handoff after token burn forced a compact. Earlier docs in `docs/handoffs/` and `docs/experiments/` remain authoritative for deeper context; this doc captures what changed and what to do first.

## Status since last handoff

Sprint 3a done. The thin client is built and verified: `clients/` directory has a CLI client, a phone-first web client, and a same-origin proxy (`serve.py`) that handles browser CORS without touching the brainstem. Both clients verified end to end on LAN and Tailscale. Commit `173eb1c`, pushed.

Sprint 2 (persistent memory) still pending. Kept hitting the daily usage wall trying to run as one heavy task. Decision: split into 2-3 smaller chunks.

`/cards` skill research: full proposal produced, NOT YET COMMITTED. Lives in the research agent's session transcript, `session_id local_4327e98f-d6c0-4434-b0d6-f153008b98e9`. The first action of the next session should be to `read_transcript` that session and save the proposal to disk (suggested: `docs/proposals/cards-skill-proposal.md`, or a global skill folder if you have one).

Proposal headline: dual-axis tier model where model family tracks stakes and extended thinking tracks difficulty (a 3x2 grid that yields the user's 1,2,3,5,4,6 difficulty ordering and 1,2,3,4,5,6 accuracy ordering); `_cards` folder at the `C:\dev` level matching the existing `_meta` convention; atomic-move-as-claim for collision-safe parallel execution; honorable-versus-advisory execution paths so high-stakes cards refuse to run unpinned. Multi-agent planning, single-agent execution.

## Immediate next action: split Sprint 2

Run as three smaller tasks, each sized to fit one usage window:

1. Wire the Embedder into the brainstem; write-on-turn path; define the session-id scheme as an `X-Session-Id` header. The thin client already consumes this exact header.
2. Retrieve-before-generate, top-k=5, whole-turn chunking; extend the metric harness with embed and retrieve probes.
3. Confirm the metric log lives on a named volume; run the cross-session recall test (the Sprint 2 done-criterion: a fact from session A is retrieved and used in session B after a full service restart).

Each chunk commits and lands independently. See `docs/experiments/experiment-1-sprint-plan.md` for the full Sprint 2 definition; this is just the operational split.

## Roadmap pointers (unchanged from prior handoff)

Stage 0 remaining: Sprint 2 (split as above), Sprint 3b (auth middleware), Sprint 3c (endpoint exposure + Cortex-down handling), Sprint 3d (integration test), Sprint 4 (bidirectional callback), Sprint 5 (Phase 0 close).

Stage 1: `docs/experiments/experiment-1-stage1-roadmap.md`.

Top 5 experiment program: `docs/experiments/experiment-program-top5.md`. User-driven adjustments to that program: the routing experiment goes back in (with speed/energy/accuracy metrics), the consolidation-and-forgetting experiment goes back in as the reach (sequenced after the consolidation node exists), M4 and M5 fold in as alternates.

## Open decisions (carried forward)

See `HANDOFF_2026-05-15_stage-transition.md` for the full list. Most relevant near-term: branch merge to `main` (`foundation/consolidation` is well ahead, clean fast-forward, no conflicts), plaintext secret file rotation (already documented in `SECRETS.md`), the eval workload for Phase 1.

## Token discipline going forward

Cap research and planning agent outputs tightly at spawn time (state a word budget in the prompt). Run heavy build tasks as smaller chunks sized to one usage window. The `/cards` skill itself, once built, is the structural fix to this problem.
