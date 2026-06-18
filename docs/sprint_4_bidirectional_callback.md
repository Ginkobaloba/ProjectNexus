# Sprint 4: Bidirectional Callback (4090 -> 4070 mid-inference)

Status: design pass, surfaced for orchestrator review. Code has not been
cut yet. Approval gate per the Sprint 4 brief: do not start cutting
brainstem or Cortex code until this design is reviewed.

## 1. Why this sprint matters

Sprints 0 through 3d built a fabric that *looks* like a fabric from the
outside (brainstem orchestrates, Cortex infers, memory persists across
sessions) but is still a linear pipeline on the inside. Every turn pre-
loads what the brainstem thinks Cortex will need, then Cortex generates
in isolation. The base 4090 model has the same context budget either
way; the brainstem just chose what to spend it on up front.

The bidirectional callback inverts the inner loop. The brainstem
pre-loads a small set of high-precision context, and Cortex is given a
*tool* it can call mid-generation when it notices the prompt does not
contain the fact it needs. The brainstem then runs a richer lookup,
returns the result, and Cortex resumes with it. The fabric becomes the
working memory the model is reading from, not just the courier of a
pre-baked prompt.

This is the architectural claim the paper rests on. Sprint 4 is where
we first demonstrate it. The done-criterion (Section 11) is a
benchmark where the fabric beats the base model on the same hardware
because the base model alone cannot fit everything required up front.

## 2. The shape we are converging on (TL;DR)

- Protocol: OpenAI-style tool calling, served by vLLM's existing
  `--enable-auto-tool-choice --tool-call-parser hermes` flags. The 4090
  was already brought up with these in HANDOFF_2026-05-14, so the
  serving layer is ready and the model (Qwen3-30B-A3B-Instruct-2507-AWQ)
  is one of the tool-calling-capable Hermes-trained families.
- Callback transport: HTTP from the 4090 box back to the 4070's
  brainstem on a *new* internal endpoint, `POST /fabric/callback`,
  carrying a structured request and getting a structured response. The
  4090's vLLM is **not** the entity making this HTTP call. The brainstem
  is. The brainstem sees `finish_reason: "tool_calls"` on the Cortex
  response, parses the tool call, executes it locally, and re-issues
  the chat completion with the tool result appended to the message
  list. The "callback" is conceptually 4090 -> 4070; physically it is
  brainstem-driven on a tool-call boundary that vLLM hands back.
- Auth on the callback path: separate `service` token class, never the
  user's bearer token. Sprint 3b's bearer-token registry already supports
  named tokens; add a `kind: service` flag and a route-level allowlist.
- Failure mode: if the brainstem cannot service the callback (e.g.,
  embedder down for the lookup), return a structured `tool` message
  with `error: callback_failed` and let Cortex either retry, ignore,
  or apologize. Generation continues; this is a soft failure, not a
  hard one. The hard-stop case (callback budget exhausted) gets a
  distinct error code so Cortex knows not to try again this turn.
- Budget: per-turn callback budget of N=3 callbacks max, with a per-
  callback token-cost cap derived from the per-card cost cap the
  runner contract already enforces. Default proposal in Section 6.
- Benchmark: a long-context multi-hop fact-recall workload where the
  4090's 8k context limit is the binding constraint when everything is
  preloaded, but the fabric path succeeds by fetching only the chunks
  the model decides it needs. Section 11 specifies.

## 3. Protocol choice

vLLM does not natively support "pause generation, make HTTP call,
resume in the same token stream." We have three options and one of
them is obviously the right one once we look at what is already
deployed. Options-with-reasoning for the record:

### Option A: OpenAI tool calling, brainstem as tool host (recommended)

The 4090 is already serving with
`--enable-auto-tool-choice --tool-call-parser hermes`. When the model
emits a tool call, vLLM stops generation at the tool-call boundary and
returns a chat-completion response with `finish_reason: "tool_calls"`
and a structured `message.tool_calls` array. The brainstem reads this,
executes the tool locally (a richer memory query, in Sprint 4), appends
a `{role: "tool", tool_call_id: ..., content: ...}` message, and re-
POSTs `/v1/chat/completions` with the expanded history. Cortex picks
up where it left off, conditioned on the new tool message.

Pros:
- Zero new protocol invention. This is the path vLLM, OpenAI's API,
  and every model-side fine-tune has converged on.
- The 4090 was brought up with the right flags already. No serving
  config change needed.
- The model (Qwen3-30B-A3B-Instruct-2507) is in the family of Hermes-
  compatible tool-calling models. The tool-call parser is the right
  one.
- The brainstem stays the only entity that makes HTTP calls between
  the boxes; the LAN topology and the auth perimeter Sprint 3c locked
  do not have to change. The "callback" is logical, not a literal
  reverse HTTP call from 4090 to 4070.
- The tool-message round-trip is exactly the abstraction we want to
  bill, instrument, and bound.

Cons:
- Each callback is one extra full chat-completion round-trip. We pay
  prompt re-encoding on each round, which is a real cost for long
  contexts. Mitigated by vLLM's prefix caching: the unchanged prefix
  of the conversation is cached across the round-trip.
- The "I want X" decision is the model's, expressed as a tool call.
  Tool-calling accuracy is a real concern. We measure it as part of
  the M2 experiment (see Section 11).

### Option B: Streaming with sentinel tokens

Have the model emit a known token sequence (e.g., `<<CALLBACK>>...
<<END>>`) mid-stream, the brainstem watches the stream, intercepts the
sentinel, makes the lookup, and injects the response back into the
stream.

Pros:
- One inference call, no round-trip cost on the prompt side.
- Conceptually clean if you ignore implementation reality.

Cons:
- vLLM streaming is token-level; you cannot inject server-side tokens
  back into an active generation without forking vLLM internals.
- Sentinel-based protocols rot. Any prompt that mentions the sentinel
  string in a natural context breaks the parser.
- No existing tooling. We would be inventing protocol and integrating
  with vLLM's streaming-output path simultaneously. That is a Sprint
  4-sized task in itself, before we even get to the actual fabric
  logic.
- The model is not trained for this. We would either need to fine-
  tune or hope the base model emits the sentinel reliably, which is a
  worse version of tool-calling.

Rejected.

### Option C: Generation-boundary partial-output marker

Treat each callback as a generation boundary: Cortex produces partial
output, signals "I want X" in some structured trailer, the brainstem
fetches X, and Cortex is re-invoked with the partial output and X as
the new prefix.

Pros:
- Closer to "natural" partial generation than Option B.
- Could be built on top of Option A by treating the tool call as a
  generation boundary (which... is what Option A already does).

Cons:
- This is basically Option A with extra bookkeeping. If we accept the
  generation-boundary framing, vLLM's tool-call boundary is already
  the right one. There is nothing additional to gain.
- Streaming the partial output to the client while a callback is
  pending is a UX question we can answer later. Phase 0 returns the
  whole turn at once; partial-output streaming was always Stage 1.

Rejected as a distinct option; subsumed by A.

### Recommendation

Option A. We use vLLM's tool calling, the brainstem is the tool host,
and the "callback" is the brainstem-orchestrated tool-call round-trip
on a Cortex-emitted tool-call boundary.

The reason this is not a slam-dunk write-up despite reading like one
is that Option A has an honest cost (prompt re-encoding per callback)
that the alternatives would have avoided if they were buildable. They
are not buildable on the Sprint 4 timeline. The cost is bounded by
prefix caching and by the per-turn callback budget. We pay it.

## 4. Callback contract (HTTP)

### 4.1 Tool definition Cortex sees

The brainstem advertises one tool to Cortex in Sprint 4. Surface area
stays small on purpose; we can grow it once the loop works end to end.

```json
{
  "type": "function",
  "function": {
    "name": "memory_lookup",
    "description": "Search the user's persistent memory for prior turns or facts relevant to the current question. Use this when the visible context does not contain a fact you need to answer. Do not use it for content already present in the conversation.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Natural-language search query. Be specific about the fact or topic you are looking for."
        },
        "k": {
          "type": "integer",
          "description": "How many matches to return. Default 5, max 20.",
          "default": 5,
          "minimum": 1,
          "maximum": 20
        },
        "session_id_filter": {
          "type": "string",
          "description": "If set, restrict the search to this session id. Omit to search across all sessions."
        },
        "max_age_days": {
          "type": "integer",
          "description": "If set, only return matches whose ts is within this many days. Useful when you need recent context only."
        }
      },
      "required": ["query"]
    }
  }
}
```

This is strictly richer than the brainstem's pre-flight retrieval,
which today is hard-coded to k=5 and no session filter. The callback
adds optional `session_id_filter` and `max_age_days`, and lets Cortex
choose k.

### 4.2 Internal endpoint on the brainstem

`POST /fabric/callback` (internal; service-token only).

Request body:

```json
{
  "callback_id": "cb_<ulid>",
  "session_id": "<the user's X-Session-Id>",
  "turn_idx": 7,
  "parent_request_id": "<the /generate request id this callback serves>",
  "tool_name": "memory_lookup",
  "arguments": { ...the parsed function arguments... }
}
```

Response body (success):

```json
{
  "callback_id": "cb_<ulid>",
  "ok": true,
  "result": {
    "matches": [
      {
        "chunk_id": "<session>:<turn>:<chunk>",
        "parent_turn_id": "<session>:<turn>",
        "text": "<chunk text, truncated to fit budget>",
        "ts": "<iso8601>",
        "distance": 0.387,
        "session_id": "<session>",
        "turn_idx": 3
      }
    ],
    "returned_count": 4,
    "truncated_count": 1
  },
  "metadata": {
    "retrieve_latency_ms": 29,
    "token_estimate": 612,
    "budget_remaining": 2
  }
}
```

Response body (error):

```json
{
  "callback_id": "cb_<ulid>",
  "ok": false,
  "error": "callback_budget_exhausted" |
           "callback_invalid_arguments" |
           "embedder_unavailable" |
           "callback_timeout",
  "message": "<human-readable>",
  "metadata": { "budget_remaining": 0 }
}
```

The error codes mirror Sprint 3c's `cortex_unavailable` /
`cortex_timeout` pattern: machine-checkable code, human message,
structured metadata. This is the part of the contract clients and
Cortex both rely on.

### 4.3 Lifecycle inside a single turn

```
client -> brainstem POST /generate (Auth: user bearer)
brainstem -> embedder memory_query (pre-flight retrieve, k=5, no filter)
brainstem -> Cortex POST /v1/chat/completions
           with messages + tools=[memory_lookup]
Cortex returns finish_reason="tool_calls" + tool_calls=[...]
brainstem parses tool_call, validates arguments, checks budget
brainstem -> embedder memory_query (callback, with caller-supplied args)
brainstem builds tool message, appends to history
brainstem -> Cortex POST /v1/chat/completions (round 2)
Cortex returns finish_reason="stop" + assistant text
(or another tool_calls, up to N=3)
brainstem -> embedder memory_write (persist the turn, with
              tool_calls_present=true)
brainstem -> client (200 + assistant text + callback log in metric record)
```

The `/fabric/callback` HTTP endpoint exists but is not on the
critical path of this flow today. It exists for the future case where
Cortex (or a Cortex-side agent) literally calls the 4070 across the
network. We keep the endpoint shape in this design so the protocol is
forward-compatible; the Sprint 4 implementation routes the call
internally via the brainstem's tool-execution path.

The endpoint is therefore both a real HTTP surface (for the
forward-compatible case) and the contract that the in-process
tool-execution path conforms to. Same schema, two transports. Decision
locked: schema-first, transport-flexible.

## 5. Retrieval expansion

Today's pre-flight retrieval is `top-k=5`, no session filter, embedded
against the same BGE-small model write-on-turn uses. The callback adds:

- Caller-specified `k` (1 to 20).
- Optional `session_id_filter`. Use case: "tell me what we decided about
  X in the planning session yesterday."
- Optional `max_age_days`. Use case: "only stuff from the last 7 days."
- (Reserved for Sprint 5+: keyword filters, `model_used` filters,
  `tool_calls_present` filter for "find prior turns where the fabric
  did something nontrivial.")

The brainstem's tool-execution path applies the same de-duplication
rules retrieve-before-generate uses (collapse chunks back to parent
turns where possible, prefer higher-distance matches when chunk count
exceeds k). The pre-flight retrieved chunk ids are passed into the
callback handler as the "already shown to Cortex" exclude-set, so a
callback does not re-deliver chunks Cortex already has. This is a
small but real source of wasted callbacks otherwise.

## 6. Token cost model and budgets

Every callback adds two costs to a turn:

1. Embed + Chroma query (~30ms warm; same as pre-flight retrieve).
2. A second Cortex chat-completion call. Prompt re-encoding is the
   dominant cost. Prefix caching in vLLM makes the unchanged prefix
   cheap, so the marginal cost is the tool message + the model's
   second-round output. Empirically (we will measure), call this
   roughly 0.2x to 0.4x the cost of the original generation.

Budgets, proposed defaults (config-overridable):

- `BRAINSTEM_CALLBACK_BUDGET_PER_TURN = 3`. Hard cap on callbacks per
  turn. After 3, Cortex's next tool call gets back
  `callback_budget_exhausted` and Cortex is expected to finalize on
  what it has. We log the event in the metric record.
- `BRAINSTEM_CALLBACK_TOKEN_CAP = 2048`. Soft cap on tokens returned
  per single callback. The brainstem truncates the result and reports
  `truncated_count` so Cortex knows the response was clipped.
- `BRAINSTEM_CALLBACK_TIMEOUT_SECONDS = 5`. If the embedder takes
  longer than this, return `callback_timeout`. Bound the overall
  turn latency.
- The per-card cost cap from the runner contract still applies to
  the aggregate Cortex calls. The callback budget is a fraction of
  that, not a separate axis.

Metric record gains five fields in Sprint 4:

- `callback_count`
- `callback_total_ms` (sum of embedder query latencies during callbacks)
- `callback_token_in` (tool message tokens consumed)
- `callback_token_out` (model output produced after callbacks)
- `callback_outcomes` (list of `ok | budget_exhausted | timeout |
  embedder_unavailable | invalid_arguments`, one per call)

`brainstem_overhead_ms` decomposition becomes:

```
total = cortex_round_1 + sum(callback_embed) + cortex_round_n
       + embed_latency_ms + retrieve_latency_ms + brainstem_overhead
```

Clean enough; we keep the same pattern Sprint 2 locked.

## 7. Auth and security

The callback path is internal. We are not opening it to clients.

### 7.1 Token class

Sprint 3b's token registry already supports named tokens. We add a
`kind` field with values `user | service`. Existing tokens default to
`user`. Service tokens are minted via
`python scripts/create_token.py --name fabric-internal --kind service`.

The `require_token` dependency gains a `required_kinds` parameter.
`/generate`, `/embed`, `/stm/write` keep `required_kinds={"user"}`.
`/fabric/callback` gets `required_kinds={"service"}`.

A user token presented at `/fabric/callback` returns 403 with
`error: wrong_token_kind`. A service token presented at `/generate`
also returns 403; service credentials should not be usable as user
credentials by construction.

### 7.2 Where the service token lives

On the brainstem itself in Sprint 4 (because the brainstem is the one
making the tool-execution call). It is read from
`/data/auth/fabric_service_token` (mode 0600, the `auth_data` named
volume). The brainstem reads it once at boot and uses it for the
internal callback call.

Forward-looking: when Cortex literally calls back over HTTP in some
future sprint, the 4090 will need a copy of the token. We will solve
that by pushing it via the same PowerShell setup script Sprint 3c
introduced for the Tailscale bind, not by syncing through Git.
`SECRETS.md`-style instructions are good enough for Phase 0; a real
secret manager is a Stage 1 problem.

### 7.3 Reachability

`/fabric/callback` is bound to the same Tailscale-only interface as
the rest of the brainstem's public surface (Sprint 3c). Inside the
container it is reachable on `0.0.0.0:5001`, but the host bind keeps
external traffic out. Inside the compose network the brainstem talks
to itself over `127.0.0.1`. The 4090 host (when it eventually makes
literal callbacks) reaches the brainstem over Tailscale.

## 8. Failure modes

In rough order of likelihood:

| Mode | Brainstem behavior | Cortex sees | Turn outcome |
|------|--------------------|-------------|--------------|
| Embedder down during callback | Return `embedder_unavailable` | Tool message with error | Cortex continues w/o new context |
| Callback budget exhausted | Return `callback_budget_exhausted` | Tool message with error | Cortex finalizes on what it has |
| Callback timeout (>5s) | Return `callback_timeout` | Tool message with error | Cortex continues w/o new context |
| Invalid arguments from Cortex | Return `callback_invalid_arguments` with the validator output | Tool message with the validation error | Cortex can retry with fixed args (counts against budget) |
| Cortex down between round 1 and round 2 | Same 503 contract as Sprint 3c | n/a | Client gets `cortex_unavailable`, turn fails cleanly |
| Cortex returns malformed tool_calls | Treat as `finish_reason="stop"` with whatever text it produced; log and increment a metric counter | n/a | Turn finishes; we get a regression signal in the metric stream |
| Tool result exceeds token cap | Truncate, set `truncated_count > 0`, return | Tool message with the truncated content and the truncation note in metadata | Cortex sees the partial result and either lives with it or issues a narrower callback |

The pattern is: callbacks degrade soft, the overall turn degrades hard
only when Cortex itself becomes unavailable (Sprint 3c handles that).

## 9. Memory write semantics

Sprint 2's write-on-turn writes the user text + assistant text as one
parent-turn document. Sprint 4 changes the parent-turn document to
optionally include a callback transcript:

```
### User
<user_text>

### Callbacks
- memory_lookup(query="...", k=5) -> 4 matches (3 used)
- memory_lookup(query="...", k=10, session_id_filter="...") -> 8 matches

### Assistant
<assistant_text>
```

The metadata field `tool_calls_present` already reserved in Sprint 2
flips to `true` on these turns. The chunker treats the new section as
another markdown heading, so the splitter is unchanged.

This matters for retrieval: a future turn querying memory will surface
turns where a callback happened, with the callback summary visible to
the embedder. That is, callbacks become first-class artifacts of the
session record, not invisible plumbing.

## 10. Implementation chunks (proposed split)

Honest token estimate: this sprint is bigger than Sprint 2 (three
chunks) and probably matches or exceeds Sprint 3c (also three chunks
plus tests). Proposed Sprint 4 split:

- **Chunk A: brainstem-side callback execution path + contract.**
  New `/fabric/callback` endpoint, schema, validation, service-token
  auth class, the in-process tool-execution function that wraps
  `embedder.memory_query` with the richer arguments. Mocked Cortex
  side (a unit test that drives the tool-execution path directly via
  the brainstem's internal entrypoint, no real 4090 in the loop).
  Tests: argument validation, budget enforcement, timeout handling,
  service vs user token check.

- **Chunk B: end-to-end tool-call loop with real vLLM.**
  Wire the Cortex client to pass the `tools` array and the
  `tool_choice="auto"` directive, parse `finish_reason="tool_calls"`,
  execute the tool via the Chunk A path, append the tool message, and
  re-issue. Loop with the per-turn cap. Update the metric record with
  the five new fields. Update the memory-write path to emit the
  callback transcript and flip `tool_calls_present`. This is the
  largest chunk and probably the riskiest, because we will not know
  Qwen3-30B's tool-calling reliability until we measure it. Surface
  measurements in the chunk handoff.

- **Chunk C: benchmark + done-criterion demonstration.**
  Build the benchmark (Section 11). Run base-model arm and fabric arm.
  Score, summarize, write up. This chunk is more analysis than code.

- **Chunk D: regression suite + Sprint 4 handoff.**
  The unit-test suite from A plus a small integration test that
  exercises the loop against a mocked vLLM (record-replay style), plus
  the handoff doc. Sprint 5 entry point lives here.

If you want to run any of these in parallel, A and the benchmark
*scaffolding* of C (building the dataset and the scorer, not running
the arms) are the most independent. B blocks C's run phase.
Recommendation is sequential A -> B -> C -> D, since Chunk B's
findings (especially Qwen3 tool-calling reliability) materially
affect the benchmark framing. If Drew wants parallelism, A and the
C-dataset prep can go in parallel sessions.

## 11. Benchmark choice for the done-criterion

Per the brief, the benchmark should be one where the base 4090 model
*alone* with everything preloaded hits a ceiling, and the fabric path
beats it. Trivial "needle-in-haystack" benchmarks would be unfair to
the base model and not honest about the fabric's contribution.

Proposed benchmark: **multi-document factual recall with a context
budget that forces an information bottleneck.**

Construction:

- 40 synthetic "research notebooks," each ~3000 tokens, written about
  a fictional research project with named entities, dates, decisions,
  and dependencies. Stored in `memory` as if they were prior session
  turns.
- A 30-question evaluation set, each question requiring 1-3 facts
  drawn from a *specific subset* of the notebooks. The labeler annotates
  which notebooks each answer requires.
- Three arms, identical prompts:
  1. **Bare model, no memory.** Sanity floor; the model knows nothing
     about the fictional project. Expected accuracy: near zero.
  2. **Bare model, full context-stuffed.** All 40 notebooks concatenated
     into the prompt (120k tokens; well over the 8k limit). Truncated
     to fit. Expected behavior: degraded accuracy, attention drift,
     hallucination on facts in the truncated tail.
  3. **Fabric with callback.** Pre-flight retrieval gets top-5
     chunks; the callback fetches additional chunks when the model
     identifies a gap. Expected behavior: higher accuracy because
     the model can ask for the specific notebook(s) it needs without
     having to fit them all up front.
- Score: factual accuracy against the labeler's gold answers, a
  per-question rubric (1 if all required facts are correct, 0
  otherwise). Secondary metrics: callback count, callback precision
  (fraction of callbacks that fetched at least one chunk used in the
  final answer), per-turn latency, total token cost.

Why this benchmark and not, say, a coding task: factual recall is the
cleanest read on whether the fabric's lazy-fetch matters. Code tasks
are confounded by the model's training-data prior; recall tasks on
fictional content are not. We also already have most of the rigging
(the retrieval path, the metric harness) and the M2 experiment in
`experiments/experiment-program-top5.md` calls for almost exactly
this setup.

A "better" criterion: arm 3 beats arm 2 by at least 15 percentage
points on overall accuracy, with the gap concentrated on questions
whose required notebooks fell into the truncated tail of arm 2's
context. We are claiming the fabric beats the base model *because of*
the lazy-fetch, not by accident; the per-question breakdown is what
substantiates that claim.

If arm 3 does **not** beat arm 2, that is also a legitimate result
worth knowing before Sprint 5. Surface honestly in the chunk C
handoff.

Cross-validation: per the user's standing preference on disputed
results, the benchmark scoring should be cross-checked by a second
model (Opus on a separate session, or a different small local model)
on a 5-question subsample of disagreements. The goal is to catch
labeler-Claude scoring drift, not to rerun the whole eval.

## 12. Open questions for orchestrator review

These are the points where Drew or the orchestrator should explicitly
approve or push back before code is cut.

1. **Tool surface.** Sprint 4 ships exactly one tool: `memory_lookup`.
   Should `fact_lookup` (a structured key/value lookup over a smaller
   curated store) or `tool_invoke` (the eventual general-tool surface)
   ship as stubs even if not fully implemented, so the catalog shape
   is set? My recommendation: no, ship `memory_lookup` only and lock
   the catalog-extension shape in the design doc. Adding stubs invites
   half-built code in the repo.

2. **Callback budget default.** Proposed N=3. Realistic? Too low?
   Qwen3-30B's tool-calling reliability is unknown to us; if it
   tends to over-call, we may want N=2. We will measure during
   Chunk B and revise the default in Chunk C if needed.

3. **Service token class.** Proposed as a new `kind` field on the
   existing token registry, not a separate token store. This keeps
   Sprint 3b's design intact. Alternative: separate file, separate
   middleware. I think the kind-field path is right; flag if you
   disagree.

4. **Endpoint name.** `POST /fabric/callback`. Alternative:
   `/v1/fabric/callback` for the future-versioning prefix. I lean
   `/fabric/callback` for Sprint 4 because the rest of the brainstem
   API is unversioned and adding `/v1` for one endpoint is noise.
   Sprint 5's release-tag work is the right place to pick a global
   versioning policy.

5. **Memory write transcript.** I propose writing the callback
   transcript into the parent-turn document (Section 9). Alternative:
   keep callbacks invisible to memory. The argument for visibility is
   that the fabric's behavior becomes part of the session record and
   future turns can learn from it; the argument against is that the
   document gets larger and the retrieval surface gets noisier. I
   lean visible; flag if you disagree.

6. **Benchmark scope.** 40 notebooks, 30 questions, three arms. This
   is bigger than a smoke test and smaller than a paper-ready run.
   If Drew wants the Sprint 4 demo to be the paper run, we should
   bump to maybe 100 notebooks and 60 questions; if Sprint 4 is the
   feasibility demo and the paper run is Sprint 5+, 40/30 is right.

7. **Cross-validation provision.** The user's standing preference is
   to engage additional agents on technically contested points. The
   benchmark scoring is the contested point here; my proposal is to
   sample 5 disagreements through a separate model. Approve or
   override.

Sprint 4 does not start cutting code until these are reviewed. Once
reviewed I will proceed with Chunk A.

Sources: this design synthesizes prior context from
`docs/handoffs/HANDOFF_2026-05-17_sprint-3c-exposure.md`,
`docs/handoffs/HANDOFF_2026-05-16_sprint-2-complete.md`,
`docs/handoffs/HANDOFF_2026-05-14_fabric-access-and-model.md`,
`docs/memory_system.md`, `docs/auth_middleware.md`,
`docs/exposure_and_cortex_down.md`,
`docs/experiments/experiment-program-top5.md` (M2: callback ablation
and selectivity), and the current state of
`nodes/brainstem_4070/cortex_client.py` and
`nodes/brainstem_4070/embedder_client.py`. The vLLM tool-calling
flags were confirmed in the 2026-05-14 fabric-access handoff.
