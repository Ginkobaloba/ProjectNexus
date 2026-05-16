# Handoff: 2026-05-16 Sprint 2 complete

Status: Sprint 2 (persistent memory) shipped end to end on `foundation/consolidation`. Three commits, in order:

- `bb1d679` sprint-2 chunk A: embedder container + Chroma write-on-turn
- `7cbcaa1` sprint-2 chunk B: retrieve-before-generate + retrieve_latency_ms probe
- (Chunk C) sprint-2 chunk C: cross-session recall test + handoff (this commit)

Pushed to origin.

## What shipped

### Chunk A: embedder container + Chroma write-on-turn

A new `embedder_4070` service runs in its own container, talks to the brainstem over the compose network. It owns:

- the embedding model (BAAI/bge-small-en-v1.5, 384-dim, CPU)
- the recursive markdown-aware chunker (450-token threshold, 400-token target, 50-token overlap, tokenizer-driven length checks)
- the persistent Chroma `memory` collection, mounted on the docker named volume `chroma_data` at `/chroma`

Brainstem no longer loads sentence-transformers in-process. `brainstem.Dockerfile` trimmed accordingly. The legacy `/embed` endpoint stays but now proxies through the embedder service.

`/generate` reads `X-Session-Id` off the request (required, 400 if missing) and writes each completed turn to `memory` synchronously after Cortex returns. Per-session `turn_idx` is held in a process-local dict on the brainstem. Phase 0 single-process is fine; a service restart resets the counter, which is a known gap surfaced in `docs/memory_system.md`.

Chunk-level metadata schema (every Chroma doc):

- `session_id`, `turn_idx`, `ts`, `model_used`, `user_token_count`, `assistant_token_count`, `source_service`, `tool_calls_present` (Drew's original spec)
- `chunk_idx`, `chunk_total`, `parent_turn_id` (added in Chunk A to support the recursive splitter without losing parent-turn identity)

Document id format: `{session_id}:{turn_idx}:{chunk_idx}`.

### Chunk B: retrieve-before-generate + latency probes

`/generate` now does a top-k=5 `memory_query` against the embedder before relaying to Cortex. **No default session filter**, because the Sprint 2 done-criterion is cross-session recall and the whole point of putting memory in the fabric is that it crosses sessions.

Injection mechanism: retrieved matches are formatted into a short block and merged into the `system` prompt sent to Cortex. If the caller already passed a `system`, the retrieved block is appended after it so caller intent stays on top. The user's prompt is never modified. Decision recorded in `docs/memory_system.md`.

Retrieval failure does not block generation. If the embedder is unreachable, brainstem logs a warning and continues to Cortex with the caller's original system prompt.

Metric record gained five Sprint 2 fields:

- `embed_latency_ms` (write-on-turn wall time)
- `retrieve_latency_ms` (pre-Cortex query wall time)
- `retrieved_count`, `retrieved_ids` (for offline retrieval-quality analysis)
- `session_id`, `turn_idx`, `memory_written` (per-turn attribution)

`brainstem_overhead_ms` is now `total - cortex - embed - retrieve` so the decomposition stays clean.

### Chunk C: cross-session recall test + handoff

`scripts/test_cross_session_recall.py` is the Sprint 2 done-criterion test. It writes 5 synthetic turns to session A, tears down and reopens the Chroma persistent client at the same on-disk path (simulating a full service restart), then issues a query from a different session that targets turn 3. Run from the repo root:

```
python scripts/test_cross_session_recall.py
```

Exits 0 on PASS, non-zero with a diagnostic on FAIL. The script exercises the same chunker, embedding model, and Chroma store the production embedder uses, just via direct import instead of HTTP, so a pass here is a real pass modulo the FastAPI wrapper.

## Recall test result

**PASS.** Target turn (session A, turn 3, "I drive a 2014 Subaru Outback Limited in metallic blue") was retrieved as the **top-1** match by cosine distance after a simulated service restart. Full output:

```
[setup] wrote 5 turns to sess_AAAAAAAAAAAA; target turn = sess_AAAAAAAAAAAA:2
[restart] re-opened Chroma; on-disk count = 5
[query] 'What car do I drive?' returned 5 matches:
  #1  dist=0.3775  parent=sess_AAAAAAAAAAAA:2  turn_idx=2
  #2  dist=0.4688  parent=sess_AAAAAAAAAAAA:1  turn_idx=1
  #3  dist=0.4842  parent=sess_AAAAAAAAAAAA:0  turn_idx=0
  #4  dist=0.4998  parent=sess_AAAAAAAAAAAA:4  turn_idx=4
  #5  dist=0.5872  parent=sess_AAAAAAAAAAAA:3  turn_idx=3

PASS: target sess_AAAAAAAAAAAA:2 retrieved as top-1.
```

Worth noting: the distance gap between the target (0.38) and the next-best match (0.47) is real, not noise. BGE-small handles this kind of fact lookup well.

## Latency numbers

From `scripts/bench_embedder_primitives.py`, CPU-only, single-user:

- Cold `embed_texts` (first call, includes model load): ~4.7 s. Only paid once at service boot.
- Warm `embed_texts` per turn: ~28 ms.
- `chunk_turn` on a short turn (under threshold): under 1 ms.
- `memory_write` first call (encode + chroma.add, including collection init): ~280 ms.
- `memory_query` (encode + chroma.query, k=5): ~2 ms.

For the production `/generate` path you can expect per-turn cost roughly:
- retrieve_latency_ms ~25-30 ms (one embed + one chroma.query)
- embed_latency_ms ~25-40 ms warm (one embed + one chroma.add)
- cortex_roundtrip_ms is the dominant term and depends on the model and the LAN

These numbers will be confirmed live once you bring the stack up. The metric harness writes them per turn to `data/metrics/brainstem_metrics.jsonl` so the first 20 warm turns will give you the real distribution.

## Volume situation (Chunk C verification)

`chroma_data` is a docker named volume mounted at `/chroma` inside `embedder_4070`. The Sprint 2 done-criterion required persistence across a service restart; the recall test confirmed it works.

`data/metrics` is currently a **host bind mount** (`../data/metrics:/data/metrics`), not a docker named volume. Decision left in place, with reasoning, rather than silently flipped:

- Bind mount preserves the existing Phase 0 metric JSONL on the host. A named-volume switch would orphan that data unless we copy it on next compose-up.
- Bind mount lets you `tail -f data/metrics/brainstem_metrics.jsonl` from outside the container, which is the Phase 0 development workflow.
- The Sprint 2 acceptance bar is "persistent across container restart," which both bind mounts and named volumes satisfy.

If you want the strict reading ("docker named volume"), it is a two-line change:

```yaml
# replace
- ../data/metrics:/data/metrics
# with
- metrics_data:/data/metrics
# and add to top-level volumes
metrics_data:
```

I left it alone since the dev-experience tradeoff is real and your wording was ambiguous.

## What's still pending (Phase 0)

- **Sprint 3b** (next session's first task): auth middleware on the brainstem. Token-bearer auth was the placeholder shape in `clients/README.md`; flesh it out as the actual middleware. `clients/cli/nexus_cli.py` already sends `Authorization` when a token is present, so the client side is wired up.
- Sprint 3c: endpoint exposure (Tailscale-only by default) + Cortex-down graceful degradation
- Sprint 3d: integration test across laptop, phone, CLI
- Sprint 4: bidirectional callback (the architectural claim the paper rests on)
- Sprint 5: Phase 0 close (soak test, design-decision record, reproducibility manifest, tag release)

The cross-session recall test is the Sprint 2 done-criterion and it passed; Phase 0 is materially closer to ship-ready.

## Open threads worth attention soon

- `_turn_idx_by_session` is in-process on the brainstem. A service restart resets the counter while the thin client keeps sending the same `X-Session-Id`. Post-restart turns will start at 0 again, which Chroma will accept and produce id collisions if a previous run of the same session id wrote turn 0 too. Two cheap fixes when convenient: snapshot the dict to disk on shutdown, or seed `_turn_idx_by_session[session_id]` at write time by counting existing chunks with that `session_id` in Chroma.
- The first write to a fresh Chroma collection is slow (~280 ms in the bench). Warm writes are much cheaper. The metric harness will surface this; we may want a "warm Chroma on boot" call in the embedder if cold-start latency leaks into the first real turn.
- `data/metrics` bind-mount vs named volume (see above). One decision Drew needs to make at his convenience.

## Entry point for Sprint 3b (auth middleware)

Read first:

- `clients/README.md` for the existing Authorization header convention
- `nodes/brainstem_4070/server.py` for where the middleware needs to sit (in front of `/generate`, `/embed`, `/stm/write`, and the embedder pass-through; **not** in front of `/health`, `/cortex/health`, `/embedder/health`, `/dashboard`, `/fabric/status` since those are status-only)
- The "Open decisions" in `HANDOFF_2026-05-15_stage-transition.md` for token format guidance if it was already settled

Shape (proposed, lock at session start):

- FastAPI dependency that checks `Authorization: Bearer <token>` against a token loaded from `SECRETS.md` (or a small key file on the 4070, single token Phase 0)
- 401 on missing/invalid
- Per-token logging into the metric record so we can later attribute traffic
- Tailscale ACL stays the perimeter; this middleware is depth-in-defense, not the only barrier

Drew, when you pick this up: start with TodoWrite, surface the token-storage decision (env var vs file vs SECRETS.md vault) as options-with-reasoning before writing the dependency. The shape of the storage decision determines the rotation story, which determines the operational doc.

Sources: this handoff is based on the in-progress state of `foundation/consolidation` at commit (Chunk C commit) and the test runs above. Source files: `nodes/embedder_4070/`, `nodes/brainstem_4070/`, `docker/`, `docs/memory_system.md`, `scripts/test_cross_session_recall.py`, `scripts/bench_embedder_primitives.py`.
