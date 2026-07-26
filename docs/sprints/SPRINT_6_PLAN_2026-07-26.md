# Sprint 6 — Jeffery, receptionist phase (V1.5 implementation cards)

**Date:** 2026-07-26
**Design of record:** `docs/architecture_v2_family_of_models.md` Section 9,
phasing per 9.6; decisions 4, 5, 8 in the Section 13 decision record.
**Prereq:** Sprint 5 (V1) merged and deployed; member #1 live on the 4090.

V1.5 is Jeffery as **receptionist only**: he takes messages while the
siblings sleep (the durable inbox from Sprint 5 already does the
custody), and he prepares the wake-up briefing. **No delegation, no
tasks, no tools beyond T0** — the delegation ledger and trust gates
stay parked until V2.x per the decision record. Jeffery never reads any
private or experiential scope; the receptionist works entirely from
shared:household and inbox custody metadata.

Cards in dependency order. R1→R2 are hub-side and data-only; R3–R4
bring the model itself up on the 4070.

---

## Card R1 — Concierge block in the registry

`family/registry.yaml` gains a top-level `concierge:` block — Jeffery is
staff, not family: no private memory scope, no promotion rights, not
listed in `GET /family`.

- Fields: `id: "jeffery"`, `display_name`, `spec_file`
  (`family/jeffery/spec.md` — the receptionist constitution: T0 only,
  briefs from shared scope only, offer nothing, invent nothing),
  `model` (dense ~8B GGUF Q5 per decision 4 — exact pick recorded in
  the registry, not in code), `runtime` (4070, llama.cpp, small ctx).
- Loader: `core/family.py` parses + validates the block (optional —
  V1 registries without it stay valid).

**Done when:** hub boots with and without the block; Jeffery never
appears in the family roster.

## Card R2 — Briefing v0 (data-only digest)

`GET /members/{id}/briefing` (auth) assembles what a member needs on
wake, from exactly two sources: the member's own inbox custody and
shared:household.

- Shape: `{member_id, generated_at, queued_messages: [{msg_id, person,
  queued_at}], household_events: [...timeline rows since the member
  last went asleep, capped]}`.
- FamilyState records presence-transition timestamps (persisted with
  the inbox store) so "since you fell asleep" is real, not a guess.
- **Privacy invariant (test-enforced):** the briefing builder has no
  code path that touches a private or experiential scope — queued
  message *prompts* are not included, only custody metadata; the
  member reads its own mail itself when it drains.

**Done when:** a planted private row can never surface in any
member's briefing; events are correctly bounded by the sleep window.

## Card R3 — Jeffery's runtime on the 4070

The 4070 hosts hub + embedder and has ~12GB VRAM headroom for a dense
8B Q5 with modest context (the KV headroom reasoning from decision 4).

- Compose service (`docker/docker-compose.yml`) or native llama-server
  entry for Jeffery on a dedicated port; hub config gains
  `concierge_url`.
- Health surfaced on `/fabric/status` next to cortex/embedder/nas.
- No tiering needed — Jeffery's weights live on the 4070 SSD and are
  pinned (he is always on duty; that is the point of him).

**Done when:** `/fabric/status` shows Jeffery up; hub can round-trip a
prompt to him.

## Card R4 — Spoken briefing (Jeffery digests R2)

`GET /members/{id}/briefing?spoken=true` runs the R2 digest through
Jeffery with his spec as system prompt, producing the concierge's
morning-report prose ("While you slept: two messages from Drew, the
dog went out twice…").

- Input to Jeffery is the R2 JSON only — the same privacy boundary,
  now enforced by construction on the prompt side too.
- Falls back to the data-only digest if Jeffery is down (R2 is the
  contract, R4 is the voice).
- Metric: `briefing_build_ms`, `briefing_tokens`.

**Done when:** wake flow can hand a member a prose briefing whose every
fact traces to an R2 field.

## Card R5 — Wake-cycle integration

The Sprint 5 drain gains an optional pre-step: when a member flips
awake, the hub attaches the briefing (spoken if available) as system
context to the *first* drained turn, so the member triages with
context — the V2 Section 9.1 wake cycle, steps 1–3, receptionist
subset.

- Registry flag per member (`briefing_on_wake: true`) — a member can
  decline the service.
- Metrics: existing `queue_wait_ms` plus `briefing_attached` on drain
  records.

**Done when:** wake with queued messages produces first-turn context
containing the briefing; members with the flag off drain exactly as
Sprint 5 shipped.

---

## Explicitly out of scope (V1.5)

Delegation of any kind (tasks, ledger, scoring, trust gates — V2.x),
any Jeffery tool beyond reading R2 input, Jeffery memory of his own
(he is stateless between briefings in V1.5), Project Vector,
self-training. If a card seems to need one of these, the card is
wrong.
