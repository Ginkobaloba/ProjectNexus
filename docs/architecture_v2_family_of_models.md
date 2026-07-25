# Nexus V2: Family of Models

Status: ACCEPTED — Drew signed off on the direction and resolved all open questions on 2026-07-25; see Section 13 (decision record)
Date: 2026-07-25
Branch: `claude/nexus-architecture-redesign-zq630k`
Supersedes: the V1 "distributed cognition fabric" framing in `readme.md` (brainstem/cortex division of labor). It does NOT throw away the V1 code; Section 3 maps every existing asset to its V2 role.

---

## 1. Why Nexus reshapes

The original bet — that value lived in distributing cognition across our heterogeneous GPUs — has been overtaken:

1. **Model offloading is now built into llama.cpp.** A single host can spill weights from VRAM to system RAM and then to SSD. We trade tokens-per-second for seconds-per-token, and for a lot of workloads (consolidation, overnight jobs, patient conversation) that trade is fine.
2. **Splitting one model across the 4090 (24 GB) + 4070 Super (12 GB) is a confirmed dead end.** Cross-device tensor traffic makes it slower than simply offloading to system RAM on the 4090 host. We stop pursuing multi-GPU pooling for a single model.
3. **Frontier labs shipped the enterprise version of the original thesis** (multi-token inference heads, massive context). Competing on inference architecture is not our edge.

What frontier products do NOT give us — and what Nexus becomes — is a **household of persistent, individual AI family members** with private lived experience, shared household context, and eventually their own senses (Project Vector) and their own self-directed improvement. The edge is *identity, memory, provenance, and physical grounding in our home*, not raw inference.

## 2. The V2 thesis in one paragraph

Nexus is a family of models. Each family member is an individual: a model (weights from Hugging Face or elsewhere), a written spec (persona, values, standing instructions), and a private memory of every interaction it has had with us. Members also share a household memory — sensor events classified by the Jetsons ("the dog went outside at 5pm"), plus any conversation context a participant *chooses* to share with the family. Privacy is the default for 1-on-1 conversation; sharing is an explicit act, and provenance metadata is the mechanism that enforces both. You can address any member at any time; if their model isn't resident on the GPU, your message queues until they're loaded (possibly after the current member finishes its task). Version 1 is a single member, but the architecture makes "adding a sibling" a data operation — download weights, write a registry entry — not a code change.

## 3. What survives from V1

Almost everything below the top layer. The reshape is mostly a re-scoping of memory and a new orchestration layer, not a rewrite.

| V1 asset | V2 role |
|---|---|
| `nodes/brainstem_4070/` (orchestrator, auth, metrics, retrieve-before-generate, write-on-turn) | Becomes the **Nexus Hub**. Same process, same middleware; gains member routing, memory scoping, and the request queue. |
| `nodes/embedder_4070/` (bge-small + Chroma) | Unchanged service. Chroma grows scope/provenance metadata and per-scope filtered queries (Section 5). |
| Bearer-token auth (Sprint 3b) + `token_name` attribution | Unchanged. Token attribution becomes the *person* half of provenance (who was in the conversation). |
| Cortex-down 503 contract (Sprint 3c: `error`, `retry_after_seconds`, `Retry-After`) | Generalizes into the **member-loading contract**: same shape, new code `member_loading`, meaning "your family member is waking up / finishing a task; retry or wait for the queued reply." |
| Phase 0 metric harness (`bench/probes.py`, JSONL sink, dashboard) | Unchanged; gains `member_id` on every record. Load/swap latency becomes a first-class metric. |
| `bench/eval/` harness + pre-registration discipline (Sprint 3d) | Becomes the **per-member report card** — the honesty mechanism for future self-training (Section 10), and the home of the concierge delegation ledger (Section 9.2). |
| Jetson → brainstem sensory pathway (designed, partly built) | Becomes the **household memory feed**: Jetson-classified events land in shared scope, readable by every member. |
| Sprint 4 bidirectional callback design (`docs/sprint_4_bidirectional_callback.md`) | Still the plan for mid-inference memory recall; parked until scoped memory ships (decision 7), then lands with the member's scope filter as a mandatory part of the tool contract. |
| NAS memory / episodic store (`nodes/nas_memory/`) | Household episodic log (sensor events, shared timeline). |
| `core/main.py` MQTT heartbeat registry | Optional fabric-health layer; not on the V1 critical path. |

**Retired:** the claim that the 4070 exists to *split inference* with the 4090. The 4070 host remains valuable as the always-on hub/embedder/memory box precisely because the 4090 is busy holding whoever is currently awake.

## 4. Core concepts

### 4.1 Family member

A member is defined entirely by data in the **family registry** (`family/registry.yaml`, one entry per member):

```yaml
members:
  - id: "vera"                      # stable id used in APIs and provenance
    display_name: "Vera"
    spec_file: "family/vera/spec.md"      # persona, values, standing instructions
    model:
      source: "hf:Qwen/Qwen3-30B-A3B-Instruct-2507"   # or a local path
      format: "gguf"                # llama.cpp runtime
      quant: "Q4_K_M"
      context_length: 32768
    runtime:
      offload_policy: "vram_then_ram"     # vram_then_ram | vram_ram_ssd
      sampling_defaults: { temperature: 0.7, top_p: 0.9 }
    memory:
      collection: "member_vera"     # private Chroma collection
    storage_tier_hint: "hot"        # where weights should live at rest (Section 7)
```

The **spec file** is the member's clearly-defined identity: who they are, how they speak, what they care about, what they may and may not do. It is versioned in git like code, because it *is* the member's constitution. The spec + private memory + shared memory is what makes interactions with one member genuinely distinct from another — the same way conversations with Opus and conversations with Sonnet are separate relationships.

### 4.2 Memory scopes

Three scopes, enforced at retrieval time by metadata filters:

- **`private:<member_id>`** — 1-on-1 conversation turns between a person and that member. Written by default on every turn (write-on-turn survives from Sprint 2). Only that member can retrieve it. This is the default for all conversation.
- **`shared:household`** — the family's common ground. Two ways in: (a) sensor events classified by the Jetsons, written automatically; (b) conversation memories **explicitly promoted** by a participant ("share this with the family"). Every member retrieves from it.
- **`experiential:<member_id>`** — reserved for Project Vector: observations gathered by a sensor platform a member autonomously controls. Only that member retrieves it. This is a member's private lived experience of the physical world, distinct from conversations.

Retrieval for member M is always: `scope IN (private:M, shared:household, experiential:M)`. There is no "query all" path in the serving flow.

> This intentionally amends the Sprint 2 decision to run retrieval with *no* filter (the cross-session-recall done-criterion). Cross-**session** recall is preserved — a member remembers all its past sessions — but cross-**member** recall is now forbidden by design. Sessions belong to relationships; relationships belong to members.

### 4.3 Provenance (the privacy mechanism)

Every memory record carries provenance metadata, extending the existing Chroma schema from `docs/memory_system.md`:

```
scope:            "private:vera" | "shared:household" | "experiential:vera"
member_id:        the member the memory belongs to (or "household")
origin:           "conversation" | "sensor" | "promotion" | "vector_platform"
participants:     ["drew"]            # from token_name attribution
promoted_from:    original doc id, when origin == "promotion"
promoted_by:      who chose to share it
sensor_source:    e.g. "jetson_backdoor_cam", when origin == "sensor"
```

Rules:

1. **Private by default.** Conversation turns are written to `private:<member>` unless the promotion is explicit.
2. **Promotion copies, never moves.** Sharing writes a new record into `shared:household` with `promoted_from`/`promoted_by` set; the private original is untouched. The family sees *what* was shared and *who* shared it, and the paper trail is permanent. Per decision 3, a member may *offer* to share ("want me to share this with the family?") but the write always requires the person's yes — and member specs carry an offer-sparingly rule so this stays the exception, not a reflex.
3. **No cross-scope leakage at retrieval.** The scope filter is applied server-side in the hub, not trusted to the client or the model.
4. **Sensor data is born shared.** The household camera/sensor feed is common ground by definition — the whole family can know the dog went out at 5pm.

### 4.4 Presence and the queue

Only one member's model is resident on the 4090 at a time (offloading lets a big member spill to RAM/SSD, but co-residency of two large models is not the plan). So members have **presence states**:

`awake` (loaded, serving) → `busy` (loaded, mid-task) → `waking` (weights staging/loading) → `asleep` (not loaded)

You can send a message to any member at any time:

- If they're `awake`: normal turn.
- If they're `asleep`/`waking`: the message lands in that member's **inbox** (a durable per-member queue). The API answers immediately with `202 Accepted` + `{status: "queued", member_state, position, estimated_wait_s}` — the same philosophy as the Sprint 3c contract: never a hang, always a structured answer.
- Swap policy: the model manager finishes (or checkpoint-pauses at a turn boundary) the current member's task, then loads the member with queued work, honoring a simple priority ("interactive beats background") and an anti-thrash minimum-residency window.

Queued messages get answered when the member wakes, and the reply is delivered to the client (poll `GET /members/{id}/inbox/{msg_id}` in V1; push later).

## 5. System shape

```
                    people (CLI / web / phone)
                              |
                              v
                     NEXUS HUB (4070 host)          <- evolved brainstem_4070
        auth | member router | scope-filtered retrieval | write-on-turn
        per-member inbox/queue | metrics | dashboard
              |                |                     |
              v                v                     v
      embedder_4070      MODEL MANAGER (4090 host)   household feed
      (bge-small +       llama.cpp server lifecycle   (Jetson classify ->
       Chroma:           weight tiering (Sec. 7)       shared:household)
       per-member +      load/unload/swap
       shared             offload policy
       collections)
              |
              v
      NAS: episodic log, weight cold storage, backups
```

The hub keeps its exact middleware stack (auth, metrics, retrieve-before-generate, write-on-turn, 503 contracts). The new pieces are the **family registry**, the **member router + inbox**, and the **model manager** on the 4090 host (a small agent that wraps llama.cpp's server: download, verify, stage, load, unload, report state).

### API sketch (V1 surface)

```
GET  /family                        -> members, presence states, queue depths
GET  /members/{id}                  -> spec summary, model info, presence
POST /members/{id}/chat             -> 200 (turn) | 202 (queued) | 503 member_loading
POST /members/{id}/memory/promote   -> share a private memory to the household
GET  /members/{id}/inbox/{msg_id}   -> poll a queued message's reply
GET  /household/timeline            -> recent shared/sensor events
```

Per decision 2, sessions are **hub-minted** per (person, member) pair — a session-create call returns the ID, and the hub persists the session and its turn counter server-side (this also fixes the documented restart-resets-`turn_idx` wart from `docs/memory_system.md`). `Authorization: Bearer` stays; `token_name` feeds `participants`.

## 6. Inference runtime

- **Runtime: llama.cpp (`llama-server`)** on the 4090 host, replacing the vLLM/TRT-LLM single-model setups in `Nexus-LLM-Runtime-4090/`. Reasons: GGUF is the lingua franca of Hugging Face local models (add-a-member = download a GGUF), and layer offload to RAM (`--n-gpu-layers`) plus mmap-from-disk gives us the VRAM → RAM → SSD gradient natively.
- **Offload policy is per-member** (registry `runtime.offload_policy`). A member whose job is overnight consolidation can run huge-and-slow (`vram_ram_ssd`); the conversational member should fit VRAM+RAM.
- The 4070's 12 GB is *not* used to split a member's weights. It hosts the **concierge** (Section 9): a small always-awake model that takes messages for sleeping siblings and executes tasks they delegate to it.

## 7. Weights storage: the family home

`family/` is the logical folder; physically, weights live on a tier and the model manager moves them as part of loading:

| Tier | Device | Role |
|---|---|---|
| **hot** | 2 TB NVMe (Gen4) | Members in rotation; load/mmap source. |
| **warm** | 1 TB NVMe (Gen2) | Occasional members. Loadable directly, slower first-load. |
| **cold** | 6 TB HDD (/NAS) | Archive: rarely-used members, superseded quants, originals. |

Load path: `ensure_hot(member)` — if weights aren't on the hot tier, copy from warm/cold first (with checksum verify), then start llama-server. Important honesty note: **llama.cpp does not manage tiering for us** — mmap will happily read weights straight off an HDD, but page-in latency makes that miserable. Tiering is our job; the model manager does an explicit staged copy and records `stage_copy_ms` and `load_ms` in the metric record. Eviction from hot is LRU with a pin flag in the registry.

## 8. The household feed (Jetsons)

The original peripheral-nervous-system idea survives intact, re-pointed at shared memory: Jetson nodes watch cameras/sensors, run local classification, and emit compact events (`{ts, sensor_source, event: "dog_out_backdoor", confidence}`) to the hub. The hub embeds and writes them to `shared:household` and appends to the NAS episodic log. Every member can then ground answers in the household's day. This is Phase 2 of V2 (it needs no new architecture — it's a producer writing to a scope that exists from day one).

**Project Vector** is the same pattern with different provenance: a sensor platform a single member controls writes to `experiential:<member>` — that member's private senses, not the household's. The scope exists in the schema from V1 so Vector plugs in without a migration.

## 9. The concierge — Jeffery

A small always-awake model on the 4070's 12 GB, named **Jeffery** (decision 8, after the Fresh Prince butler), working **both directions**:

- **Downward (people → sleeping members):** takes messages, acknowledges receipt, and prepares the briefing each member gets on wake.
- **Upward (members → concierge):** accepts **delegated tasks** from family members — context fetches, scaffolding, summarization, drafting, anything a member decides is worth handing off — and executes them while the member is off the GPU.

The concierge is staff, not a sibling: it has its own spec and its own working memory, but it holds no relationships. Its purpose is to keep the household responsive while the 4090 serves one member at a time.

### 9.1 The wake cycle (triage-and-dispatch)

The scheduling discipline that keeps quick replies from stalling behind long work. When multiple members have queued messages:

1. **Load** the first member (queue order / priority).
2. **Briefing:** the concierge hands over the member's inbox plus a digest of what happened while it slept (drawn from `shared:household` — sensor events, promoted memories, anything family-visible).
3. **Triage:** for each item the member decides — *answer now*, *delegate* (issue the concierge a task brief: fetch this context, build this scaffolding, do this legwork), or *defer*.
4. **Dispatch and yield:** the member answers the quick items, files its task briefs, and releases the GPU. The next member loads and gets the same cycle.
5. **Concierge works** the delegated task queue in parallel on the 4070 — it is never blocked by who holds the 4090.
6. **Re-wake:** when a member's delegated tasks complete, the concierge puts that member back in the wake queue. On its next residency the member finishes the deferred items with the gathered context — and **scores each completed task** (Section 9.2) before yielding again.

Residency slices become triage-and-dispatch rather than end-to-end completion: a member's long research task no longer holds the GPU hostage while a sibling's ten-second reply waits.

### 9.2 The delegation ledger (earned trust, per member)

Which tasks the concierge can be trusted with is not designed — it is **learned empirically, separately by each member**. Every delegated task is recorded:

```
{task_id, member_id, task_type, brief, result_ref, concierge_latency_ms,
 scores: {followed_brief: 1-5, completeness: 1-5, usefulness: 1-5},
 member_notes, ts}
```

Scoring is three-axis from task one (decision 6): `followed_brief` and `completeness` diagnose the concierge's execution, `usefulness` diagnoses the brief itself — a low-usefulness/high-followed-brief task means the *member* briefed badly, and those need different fixes. The scores are assigned at step 6 of the wake cycle, when the member actually consumes the result — the moment it has real evidence. Rolling per-`(member_id, task_type)` scores then feed each member's own triage decisions: a member consults its ledger history when deciding *answer now vs. delegate*.

Two members will develop different effective use of the concierge, and that asymmetry is signal, not noise: part of what the ledger measures is how well a *member briefs* — one member may communicate tasks in a way the concierge executes well and therefore earn more leverage from it than a sibling does. Trial and error is the mechanism. The ledger is also bench-grade data: once enough tasks accumulate, "delegation lift" (turnaround time and answer quality with vs. without the concierge) becomes a pre-registerable metric in the `bench/eval/` harness.

### 9.3 Provenance boundaries

The concierge routes around privacy; it never breaches it:

1. **No private-scope retrieval.** The concierge cannot query any `private:<member>` or `experiential:<member>` collection. It works *only* from the task brief the member wrote — the member decides what context leaves its private scope, exactly like promotion (Section 4.3).
2. **Queued messages are in custody, not memory.** An inbox item the concierge holds for a sleeping member has not been "heard" by anyone yet; it becomes memory only when the member processes it, and then in that member's private scope.
3. **Task results belong to the delegator.** Completed task output is written to the delegating member's `private:<member>` scope with `origin: "delegated_task"` and provenance recording that the concierge executed it.
4. **The briefing digest is shared-scope only.** "What happened while you slept" is assembled exclusively from `shared:household` — the concierge cannot tell one member what another said in private, because it never knew.

### 9.4 API additions

```
POST /concierge/tasks               -> member files a task brief (service-auth)
GET  /concierge/tasks/{id}          -> status / result_ref
POST /concierge/tasks/{id}/score    -> member's evaluation (writes the ledger)
GET  /members/{id}/briefing         -> the wake-cycle handover package
```

The member→concierge direction is the first real consumer of the Sprint 4 service-token class (`docs/sprint_4_bidirectional_callback.md` Section 7): members call the concierge with service credentials, not user tokens.

### 9.5 Trust gates (what "earning more privileges" means)

Two kinds of trust, measured separately:

- **Delegation trust** (per member, per task type) lives in the ledger and governs *what members choose to hand off*. It needs no gate — each member's own triage decisions are the enforcement.
- **Capability trust** (global, for Jeffery) governs *what tools Jeffery may use*, in tiers:

| Tier | Tools | How it's granted |
|---|---|---|
| **T0 — custody** | inbox custody, briefings, `shared:household` retrieval | Granted at V1.5. This is the receptionist floor. |
| **T1 — read-only research** | T0 + web search/fetch, local file reads, writes confined to a per-task workspace | Earned via the graduation gate below. |
| **T2 — write/act** | anything with effects outside a task workspace | Never auto-granted. Requires Drew's explicit approval per capability, regardless of scores. |

**Graduation gate T0 → T1:** at least 20 scored tasks in the ledger with rolling means of `followed_brief >= 4.0` and `completeness >= 3.5`, and **zero provenance violations** (any attempt to touch a private scope, ever, is disqualifying). The bar is on `followed_brief` above all, because a tool-holding agent that deviates from its brief is dangerous in proportion to its tools.

**Demotion is automatic and cheap:** a provenance violation drops Jeffery a tier immediately pending human review; a rolling `followed_brief` mean below 3.0 over the last 10 tasks freezes acceptance of new task types until it recovers. Gates are config in the registry, so tightening or loosening them is a data change — and every gate decision is itself logged, so "why does Jeffery have this tool" always has an answer in the record.

### 9.6 Phasing

- **V1:** no concierge; single member (Section 11 unchanged). The inbox and 202 contract are designed so the concierge slots in behind them without an API break.
- **V1.5 — Jeffery as receptionist:** dense ~8B instruct at Q5 resident on the 4070 (decision 4 — MoE loses here: all experts must fit in memory, and 12 GB minus KV-cache headroom buys a better dense model than any MoE that fits; revisit via registry swap if a strong sub-10 GB MoE ships). Message custody + wake-cycle briefing, T0 tools only.
- **V2.x — delegation:** task briefs, the ledger, three-axis scoring, triage-and-dispatch scheduling, and the T1 graduation gate armed. Requires at least two members before the scheduling half pays for itself, but the ledger is worth running from the first delegated task.

## 10. Self-improvement (later, but designed for)

"A member studies to get better" = fine-tuning (realistically LoRA on the 4090) on curated data from its own scopes. Two standing rules, both already paid for:

1. **Training data respects provenance.** A member trains only on `private:<self>` + `shared:household` + `experiential:<self>` — exactly its retrieval scope. Nothing about training gets to cross the privacy boundary.
2. **No silent self-modification.** Every candidate adapter runs the `bench/eval/` gauntlet against that member's frozen baseline, with the Sprint 3d pre-registration discipline (win condition declared before the run, bootstrap CIs, guard-task regression tolerance). A member that "studied" but regressed doesn't ship. The bench harness stops being sprint tooling and becomes the family's report card.

## 11. Version 1 scope (single member, full architecture)

Everything in V1 is the smallest honest version of the real shape — no placeholder designs that get rewritten when member #2 arrives.

1. **Family registry** (`family/registry.yaml`) with one member + spec file. Loader + validation in the hub.
2. **Hub member routing**: `/members/{id}/chat` wrapping the existing `/generate` path; member spec injected as the base system prompt (caller system prompt layers after it, retrieved context after that — extends the existing `_merge_system`).
3. **Scoped memory**: Chroma metadata gains `scope`/`member_id`/`origin`/`participants`; `memory_query` takes a scope filter; write-on-turn writes `private:<member>`. Migration: existing `memory` collection records are grandfathered into member #1's private scope.
4. **Model manager v0** on the 4090 host: llama.cpp server lifecycle for one member + `ensure_hot()` tiering + presence reporting to the hub. Manual swap only (there's nobody to swap to yet), but the presence states and the `member_loading` 503 contract are real from day one.
5. **Inbox v0**: durable queue + 202 contract, exercised by sending a message while the member is loading.
6. **Promotion endpoint**: `POST /members/{id}/memory/promote` with the copy-not-move provenance rules.
7. **Metrics**: `member_id`, `load_ms`, `stage_copy_ms`, queue depth on the dashboard.

**Adding member #2 is then, by construction:** download GGUF → place on a tier → write registry entry + spec file → hub creates the private collection on first contact. Zero code.

## 12. What V2 deliberately does not do

- No multi-GPU tensor splitting of one model (confirmed dead end).
- No simultaneous residency of two large members (queue + swap instead).
- No automatic sharing of conversation memory (promotion is always explicit).
- No concierge access to any private or experiential scope — it works from briefs only.
- No self-training until the bench report-card gate exists for that member.
- No rewrite of the embedder/Chroma/auth/metrics stack — V2 is additive at the edges of V1 code.

## 13. Decision record (Drew, 2026-07-25)

All eight open questions from the proposal are resolved:

1. **First member: Qwen3-30B-A3B-Instruct-2507, GGUF Q4_K_M.** MoE confirmed as the right architecture for the 4090 member: ~3B active parameters per token gives near-small-model speed at 30B-class quality, and the 24 GB VRAM covers the "all experts resident" memory cost that MoE trades for that speed. It is also the model the bench program has pre-registered baselines for, so member #1's report card has history from day one. Name and persona spec: Drew's, to be written before first boot so memories accrue under the right identity from turn zero.
2. **Sessions are hub-minted** per (person, member) pair, persisted server-side with their turn counters (Section 5). Kills the restart-resets-`turn_idx` wart.
3. **Promotion: members may offer, the person always confirms** (Section 4.3). Offer-sparingly rule goes in each member's spec.
4. **Jeffery's model: dense ~8B instruct at Q5** (Section 9.6). MoE rejected for the 12 GB card — total-weights residency is the constraint there, and a dense 8B beats any MoE that fits. Embedder + hub stay co-resident on the 4070 (CPU-bound, no VRAM contention). Revisit by registry swap if the ledger ever shows Jeffery as the bottleneck.
5. **Tool surface: minimal (T0) at V1.5, read-only research (T1) behind an empirical graduation gate, writes (T2) only by explicit human approval.** "Trust" is now defined concretely in Section 9.5: ≥20 scored tasks, rolling `followed_brief >= 4.0` and `completeness >= 3.5`, zero provenance violations ever; automatic demotion on violation or score collapse.
6. **Scoring: three axes from task one** — followed-brief / completeness / usefulness, plus the free-text note (Section 9.2). Separates "Jeffery executed badly" from "the member briefed badly," which need different fixes.
7. **Sprint 4 callback: parked until scoped memory ships**, then lands with the member's scope filter as a mandatory part of the tool contract. An unscoped mid-inference `memory_query` would be a cross-member privacy hole; scoped memory (Section 11, item 3) is the prerequisite.
8. **Vocabulary frozen** as written — family registry, member, household scope, concierge — and the concierge is named **Jeffery**, after the Fresh Prince butler.
