# Sprint 5 — Family of Models V1 (implementation cards)

**Date:** 2026-07-25
**Design of record:** `docs/architecture_v2_family_of_models.md` (ACCEPTED — see its Section 13 decision record)
**Scope source:** V2 doc Section 11 (V1 scope). Nothing outside that list belongs in this sprint.

V1 ships a single family member (Qwen3-30B-A3B GGUF Q4_K_M on the 4090 via
llama.cpp) behind the Nexus Hub, with the registry, scoped memory, inbox, and
promotion machinery built so that adding member #2 is a registry entry + weights
download — zero code change. Jeffery is **not** in this sprint (V1.5 per the
phasing in V2 Section 9.6).

Cards are ordered by dependency. 1→2 and 3 can run in parallel; 4 unblocks the
end-to-end path; 5–7 finish the contract.

---

## Card 1 — Family registry + loader

**Goal:** `family/registry.yaml` is the single source of truth for who exists.

- Schema per V2 Section 4.1: `id`, `display_name`, `spec_file`, `model`
  (hf source, gguf filename, quant, context_length), `runtime`
  (offload_policy, sampling defaults), `memory_collection`, `storage_tier_hint`.
- Loader module in `core/` that validates on startup (unknown keys, missing
  spec file, duplicate ids → hard fail with a clear message).
- Seed with member #1 (`Qwen3-30B-A3B`, Q4_K_M) using real values.
- Member spec file (system prompt / personality) referenced, not inlined.

**Done when:** hub boots from the registry; a second yaml entry appears in
`GET /family` with no code change.

## Card 2 — Hub member routing + presence

**Goal:** brainstem_4070 server becomes the Nexus Hub speaking the member API.

- `GET /family` (roster + presence), `GET /members/{id}` (spec summary,
  presence, queue depth).
- `POST /members/{id}/chat` → `200` (awake, reply inline), `202` (queued,
  returns `msg_id`), `503 member_loading` with `Retry-After` (generalizes the
  Sprint 3c cortex-down contract).
- Presence states: `awake / busy / waking / asleep`, owned by the model
  manager (Card 4) but stubbed here so routing is testable first.
- Sessions are hub-minted per (person, member) pair and **persisted** with
  turn counters — this fixes the documented restart-resets-turn_idx wart in
  `core/session.py`.
- Existing bearer-token auth (argon2id) unchanged.

**Done when:** chat to an awake member round-trips; chat to an asleep member
returns 202 + msg_id; loading member returns 503 with Retry-After.

## Card 3 — Scoped memory + migration

**Goal:** every memory row carries a scope; retrieval is filtered server-side.

- Scopes: `private:<member>` (conversation default), `shared:household`,
  `experiential:<member>` (reserved, no writers in V1).
- Provenance metadata on every write: `scope`, `member_id`, `origin`
  (`conversation | sensor | promotion`), `participants` (from token_name).
- Retrieval filter is **always** `private:M + shared:household +
  experiential:M` for member M — applied in the embedder service, not the
  caller. This amends Sprint 2's deliberate no-filter design; cross-session
  recall *within* a member is preserved, cross-member recall is forbidden.
- One-shot migration script: existing `memory` Chroma collection →
  member #1's private scope (`origin: conversation`, backfilled participants).
  Dry-run mode, row-count reconciliation, no deletes until verified.

**Done when:** a query as member #1 never returns another scope's rows (test
with a planted decoy scope); migration reconciles to the row.

## Card 4 — Model manager v0

**Goal:** one process owns weights placement and llama.cpp lifecycle.

- `ensure_hot(member)`: staged copy cold (6TB HDD) → warm (1TB Gen2) → hot
  (2TB Gen4 NVMe) with checksum verify; llama.cpp does **not** tier for us —
  mmap off HDD is not acceptable.
- Launch/stop `llama-server` per registry `runtime` block (offload_policy,
  ctx, sampling defaults); health-poll → flip presence `waking → awake`.
- LRU eviction from hot tier with a `pin` flag; single-member V1 means
  eviction is exercised only by tests, but the code path ships now.
- Emits `stage_copy_ms` and `load_ms` per load.

**Done when:** cold-start of member #1 from HDD → serving, with both timings
in the metric log; kill/restart recovers presence correctly.

## Card 5 — Inbox v0 (queued messages)

**Goal:** talk to any member any time; delivery waits for wake.

- Durable per-member inbox (survives hub restart) behind the Card 2 `202`
  contract; `GET /members/{id}/inbox/{msg_id}` for status/result.
- On wake, queued messages drain in arrival order into the member's normal
  chat path (same session semantics as live chat).
- Queued messages are **custody, not memory**: nothing enters any memory
  scope until the member actually processes the turn.

**Done when:** message sent while asleep is answered after wake with correct
session continuity, and the answer is retrievable by msg_id.

## Card 6 — Promotion endpoint

**Goal:** private → shared is a person's explicit choice with a paper trail.

- `POST /members/{id}/memory/promote`: **copies, never moves** the row into
  `shared:household` with `origin: promotion`, `promoted_from`, `promoted_by`.
- Offer-then-confirm (V2 decision 3): a member may *offer* promotion in
  conversation, but the endpoint only executes on the person's confirmation;
  member specs carry the offer-sparingly rule.
- Original private row untouched; promotion is idempotent per source row.

**Done when:** promoted memory is retrievable by a hypothetical member #2's
filter (shared scope) while the private original remains invisible to it.

## Card 7 — Metrics + report card hooks

**Goal:** the existing JSONL harness understands members.

- Add `member_id` to every request record; add `stage_copy_ms`, `load_ms`,
  `queue_wait_ms` (inbox) record types.
- Bench discipline unchanged: pre-register the member #1 baseline run (same
  prompt set as Sprint 3d bench) **before** tuning offload_policy, so we have
  an honest llama.cpp-vs-vLLM comparison and a seed for the per-member report
  card (V2 Section 10).

**Done when:** one end-to-end conversation produces a metric trail covering
load → queue → chat with member attribution on every line.

---

## Explicitly out of scope (V1)

Jeffery/concierge (V1.5), delegation ledger and trust gates (V2.x), Project
Vector / experiential writers, self-training, household timeline endpoint
beyond stub, Sprint 4 bidirectional callback (parked until Card 3's scope
filter can be a mandatory part of that tool contract).
