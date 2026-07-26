# Memory system

Status: Sprint 2 complete. Chunks A (embedder + write-on-turn), B (retrieve-before-generate + latency probes), and C (cross-session recall test) all shipped. Done-criterion verified: see `docs/handoffs/HANDOFF_2026-05-16_sprint-2-complete.md` for the test result and the latency numbers.

## Shape

Three services on the 4070, one on the 4090.

```
thin client  --X-Session-Id-->  brainstem_4070 (port 5001)
                                    |
                                    |--HTTP--> embedder_4070 (port 5003)
                                    |                |
                                    |                +--> chromadb (volume: chroma_data, path /chroma)
                                    |
                                    |--HTTP--> nas_memory (port 5002, legacy semantic store)
                                    |
                                    |--HTTP--> cortex_4090 (vLLM, LAN)
```

Brainstem no longer owns the embedding model. The embedder service does. Brainstem is the orchestrator and the metric harness owner.

## Why a separate embedder container

Cleaner lifecycle, swappable model, and clear separation of "the thing that turns text into vectors" from "the thing that routes traffic between nodes." The latency cost of one localhost HTTP hop is negligible at our request rates. Trade was made in Sprint 2 Chunk A.

## Embedder service

Model: `BAAI/bge-small-en-v1.5`. 384-dim, ~133MB, 512 max sequence tokens, CPU inference at single-user rates. Picked over bge-large because the latency win is large and the quality delta on conversational retrieval is small. Swappable behind the API; no caller depends on the dim count except Chroma, and the collection can be rebuilt.

Store: chromadb persistent client at `/chroma` inside the container, mounted to the docker named volume `chroma_data`. Single collection named `memory`. Cosine distance, which is the natural fit for normalized BGE vectors.

API:
- `GET /health` returns service status + chroma_count
- `POST /embed` returns `{embeddings, model, dim}` for a list of texts
- `POST /memory/write` with `X-Session-Id` header writes a completed turn
- `POST /memory/query` with `X-Session-Id` header returns top-k matches

`X-Session-Id` is required on write. It is read on query for traceability but is not used as a default retrieval filter, because the Sprint 2 done-criterion is cross-session recall.

## Chunking

The chunking unit is the whole turn: user text + assistant text concatenated as one document. Concatenation format:

```
### User
{user_text}

### Assistant
{assistant_text}
```

Markdown headings are natural break points for the recursive splitter and parse cleanly to BGE.

Long-turn handling: recursive splitting with markdown-aware separators, gated by a token-count threshold. Settings (Sprint 2 lock):
- threshold: 450 tokens (below this, no chunking; this is the common case for short turns)
- target chunk size: 400 tokens
- overlap: 50 tokens
- separator priority: `\n\`\`\``, `\n### `, `\n## `, `\n# `, `\n\n`, `\n`, `. `, ` `, `""`

Token counts come from the embedding model's own tokenizer so the math matches what the encoder will actually see.

Other strategies considered: fixed-size with overlap (rejected: splits mid-sentence and mid-code-fence), sentence-aware via spaCy/NLTK (rejected: adds an NLP dep for marginal gain on our mixed content), semantic chunking via embedding similarity drop (rejected: pays a per-turn embedding tax to find boundaries that rarely matter on single-topic user+assistant pairs).

## Chroma metadata schema

Every chunk gets:
- `session_id` (string)
- `turn_idx` (int, monotonic per session)
- `ts` (ISO 8601 UTC)
- `model_used` (Cortex model id for the turn)
- `user_token_count` (Cortex usage.prompt_tokens for the turn)
- `assistant_token_count` (Cortex usage.completion_tokens for the turn)
- `source_service` (e.g., `brainstem_4070`)
- `tool_calls_present` (bool, reserved for Sprint 4 callback work)
- `chunk_idx` (int, 0 if the turn was not chunked)
- `chunk_total` (int, 1 if the turn was not chunked)
- `parent_turn_id` (string, `{session_id}:{turn_idx}`)

Document id format: `{session_id}:{turn_idx}:{chunk_idx}`. Body is the chunk text (or the full turn document if not chunked).

## Brainstem write-on-turn

`/generate` reads `X-Session-Id` off the request (required), forwards the prompt to Cortex, and on a successful return calls `embedder.memory_write` synchronously before responding. Synchronous on purpose: the metric harness sees real end-to-end turn cost. We can flip to async if write-on-turn ever shows up in the turn p95.

Per-session turn index is held in a process-local dict on the brainstem (`_turn_idx_by_session`). Phase 0 single-process is fine. A service restart resets the counter; the thin client persists `X-Session-Id` across restarts, so post-restart turns start at 0 again, which the next session over the same `X-Session-Id` will see as a fresh turn series. Surfaced here so we remember; we will fix this in Stage 1 when the brainstem gets a real persistence layer (or trivially earlier by snapshotting `_turn_idx_by_session` to disk).

## Retrieval (Chunk B)

Top-k=5 against the `memory` collection at the start of every `/generate`, embedded with the same model the writes use. No default session filter, because the Sprint 2 done-criterion is cross-session recall.

Injection mechanism: the retrieved matches are formatted into a short block and merged into the `system` prompt sent to Cortex. If the caller already passed a `system` prompt, the retrieved block is appended after it so the caller's instruction stays on top. The user's prompt is never modified, so the model sees a clean user intent and the retrieved context as instruction-like background.

The block format:

```
You have access to prior turns from this user's memory. Use any that are actually relevant; ignore the rest.

--- prior turn 1 (session <short id>, turn <idx>, <ts>, distance=<d>) ---
<chunk text>

--- prior turn 2 ... ---
<chunk text>
```

Distance is included so we can debug retrieval quality by reading the metric log without a separate trace.

Failure mode: if the embedder service is unreachable for retrieval, the brainstem logs a warning and continues to Cortex with the caller's original system prompt. Generation does not fail because retrieval did.

## Metric harness (Chunks A + B)

The Phase 0 brainstem metric record gained five fields in Sprint 2:

- `embed_latency_ms` (Chunk A) - wall time for the post-Cortex `memory_write` call
- `retrieve_latency_ms` (Chunk B) - wall time for the pre-Cortex `memory_query` call
- `retrieved_count` (Chunk B) - number of matches returned by the embedder
- `retrieved_ids` (Chunk B) - the chunk ids returned, for offline analysis
- `session_id`, `turn_idx`, `memory_written` (Chunk A) - per-turn attribution

`brainstem_overhead_ms` is now computed as `total_ms - cortex_roundtrip_ms - embed_latency_ms - retrieve_latency_ms` so the decomposition is clean: total = cortex + embed + retrieve + brainstem-side overhead.

## Volumes

- `chroma_data` (docker named volume) -> mounted at `/chroma` in `embedder_4070`. This is the unit of backup and the unit of "wipe to start over."
- `../data/metrics` (host bind mount on the 4070) -> mounted at `/data/metrics` in `brainstem_4070`. JSONL metric records.
- `auth_data` (docker named volume, added Sprint 3b) -> mounted at `/data/auth` in `brainstem_4070`. Hashed bearer-token registry. Survives container restarts and rebuilds.

Chunk C confirmed the cross-session recall test against this stack. Sprint 3b layered bearer-token auth on top without altering the embedder or chroma paths; the recall behavior is unchanged by construction.

## Auth (Sprint 3b)

`/generate`, `/embed`, and `/stm/write` now require `Authorization: Bearer <token>`. Status endpoints (`/health`, `/cortex/health`, `/embedder/health`, `/fabric/status`, `/dashboard`, `/`) stay anonymous. Tokens are minted via `python scripts/create_token.py --name <client>` inside the brainstem container; the plaintext token is printed once and only the argon2id (or scrypt fallback) hash lives on disk. Per-request token attribution is logged and written to the metric record under `token_name`. See `docs/auth_middleware.md` for the full design and decision log.

## Sprint 5: scoped memory

Design of record: `docs/architecture_v2_family_of_models.md` (Sections 4 and 5), implemented per `docs/sprints/SPRINT_5_PLAN_2026-07-25.md` Card 3. Everything above this section describes the single-scope Sprint 2 store; this section describes how it became a multi-member store without a rewrite — the collection, chunker, and BGE model are all unchanged.

### Scopes

Every row now lives in exactly one of three scopes:

- **`private:<member_id>`** — 1-on-1 conversation turns between a person and that member. This is the default write target for every turn. Only that member's queries can read it.
- **`shared:household`** — the family's common ground: sensor events (Jetson classification, born shared) and conversation memories a person has explicitly promoted. Every member's queries can read it.
- **`experiential:<member_id>`** — reserved for Project Vector (a member's own sensor platform). No writers in V1; only that member's queries can read it.

`nodes/embedder_4070/scopes.py` is the single source of truth for these rules (pure functions, no Chroma dependency, so the privacy logic is unit-testable on its own).

### Provenance metadata

Every chunk's metadata gained four fields on top of the Sprint 2 schema (`session_id`, `turn_idx`, `ts`, `model_used`, etc. — all unchanged):

- `scope` — one of the three scopes above.
- `member_id` — the member the row belongs to (`"household"` for `shared:household` rows).
- `origin` — `conversation | sensor | promotion | vector_platform | delegated_task` (the last two are reserved for Project Vector and the V1.5 concierge; no writer produces them yet).
- `participants` — who was in the conversation, from `token_name` attribution. Chroma metadata values must be scalars, so this is stored **comma-joined** (e.g. `"drew"` or `"drew,vera"`), not as a list.

Promoted rows carry three additional fields: `promoted_from` (the source row id), `promoted_from_member` (which member's private scope it came from), and `promoted_by` (who confirmed the share).

### `/memory/write` requires scope + member_id

`POST /memory/write` on the embedder now takes mandatory `scope` and `member_id` fields (`origin` defaults to `"conversation"`, `participants` defaults to empty). The service validates before writing: a member may only write into its own `private:<member>` / `experiential:<member>` scopes or into `shared:household` — never into another member's scopes. A cross-member write attempt is rejected with `400` before anything touches Chroma. There is no longer a way to write an unscoped row.

### `/memory/query` is server-side scope-filtered — always

`POST /memory/query` now takes a mandatory `member_id`. The embedder builds the Chroma `where` clause from it unconditionally:

```
scope IN (private:<member_id>, shared:household, experiential:<member_id>)
```

Callers cannot widen this — there is no parameter that requests a different or broader scope set, and the filter is applied inside the embedder service, not trusted to the brainstem or the model. This **amends the Sprint 2 decision** documented above (Chunk B: "no default session filter, because the done-criterion is cross-session recall"). That done-criterion is preserved — a member still recalls every past session it has had — but it no longer means *every session of every member*. Cross-session recall within a member survives; cross-member recall is now structurally impossible through this API. `session_id_filter` and `exclude_parent_turn_id` remain available as optional refinements *inside* the member's visible scopes, not as ways around them.

### `/memory/promote` — copy, never move

`POST /memory/promote` (`member_id`, `memory_id`, `promoted_by`) shares a private memory with the household without touching the original:

- The shared copy gets a **deterministic id** — `{source_id}::promoted` — so promoting the same row twice is a no-op (`already_promoted: true` in the response) rather than a duplicate.
- The copy is written to `shared:household` with the full paper trail: `origin: "promotion"`, `promoted_from`, `promoted_from_member`, `promoted_by`. The private original's metadata and scope are untouched.
- The source row must actually be in `private:<member_id>` for that member — promoting a row that isn't yours (or isn't private) is rejected with `400`.
- At the hub, `POST /members/{id}/memory/promote` is the person's confirmation step; reaching that endpoint at all establishes consent (only people hold bearer tokens), per the offer-then-confirm rule in the V2 decision record — a member may *offer* to share in conversation, but the write only happens once the person calls this endpoint.

### Migration: `scripts/migrate_memory_scopes.py`

Pre-Sprint-5 rows have no `scope` metadata, which makes them invisible to the now-mandatory filter above. The migration script backfills exactly those rows:

- **Dry-run by default.** `python scripts/migrate_memory_scopes.py` only prints the reconciliation plan (`total` / `already_scoped` / `would update`); nothing is written until you pass `--apply`.
- **Grandfathers into member #1's private scope.** Unscoped rows get `scope=private:<member>` (default: the first entry in `family/registry.yaml`), `member_id=<member>`, `origin=conversation`, and `participants` from the (optional) `--participants` flag — pre-V2 rows never recorded who spoke, so this defaults to empty.
- **Idempotent.** Rows that already carry a `scope` are left untouched, so re-running the script (with or without `--apply`) is always safe.
- **Reconciles to the row.** The script tallies `already_scoped + updated` against the collection's total count and exits nonzero if anything is unaccounted for, rather than silently leaving rows behind.
- Runs inside the embedder container, since that's what owns the Chroma volume: `docker compose exec embedder python scripts/migrate_memory_scopes.py [--apply] [--member ID] [--participants a,b] [--persist-dir ...] [--collection ...]`.
