# Memory system

Status: Sprint 2 in flight. Chunks A (embedder + write-on-turn) and B (retrieve-before-generate + latency probes) landed.

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

Chunk C will confirm the metric log is on a named volume and run the cross-session recall test against this stack.
