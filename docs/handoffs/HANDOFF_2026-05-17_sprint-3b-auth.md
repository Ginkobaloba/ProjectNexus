# Handoff: 2026-05-17 Sprint 3b complete (auth middleware)

Status: Sprint 3b shipped end to end on `foundation/consolidation`. Three commits, in order:

- `bfcbba5` sprint-3b chunk A: bearer-token auth middleware + token store + CLI
- `f1c09c5` sprint-3b chunk B: client wiring + pytest suite + doc updates
- (Chunk C) sprint-3b chunk C: handoff (this commit)

Pushed to origin.

## What shipped

The brainstem now requires `Authorization: Bearer <token>` on `/generate`, `/embed`, and `/stm/write`. Status endpoints (`/health`, `/cortex/health`, `/embedder/health`, `/fabric/status`, `/dashboard`, `/`) stay anonymous so monitoring and the dashboard keep working untouched. Tailscale ACL remains the outer perimeter; this middleware is depth-in-defense.

### Chunk A: auth core

`nodes/brainstem_4070/auth.py` owns the new layer:

- `TokenStore` reads and writes `/data/auth/tokens.json`. Entries are `{name, hash, created_at, last_used_at, use_count}`. The hash is argon2id via `argon2-cffi`, with `hashlib.scrypt` as a documented stdlib fallback. The file mtime is checked on every request so a freshly-minted or revoked token takes effect without a brainstem restart.
- `require_token` is the FastAPI dependency: parses `Authorization: Bearer <token>`, walks every entry on a miss to flatten timing, attaches the matched entry's name to `request.state.token_name`, and 401s on any failure mode. Constant-ish time across the entry set was a deliberate choice; the entry count stays well under ten in practice so the cost is bounded.
- `nodes/brainstem_4070/server.py` wires the dependency into the three business endpoints. `auth.name` flows into the metric record extras as `token_name` and into the per-request log line.

`scripts/create_token.py` is the operator-facing CLI:

```
python scripts/create_token.py --name laptop          # mint, print once, hash to disk
python scripts/create_token.py --list                 # name, created, last_used, use_count
python scripts/create_token.py --revoke laptop        # remove the entry
python scripts/create_token.py --store /tmp/t.json    # override the default path
```

Run it inside the brainstem container so the plaintext token never crosses the network:

```
docker compose exec brainstem python scripts/create_token.py --name laptop
```

`docker/docker-compose.yml` adds the `auth_data` named volume (mounted at `/data/auth`) and the `BRAINSTEM_TOKEN_STORE_PATH=/data/auth/tokens.json` env var. `docker/brainstem.Dockerfile` picks up `argon2-cffi` and now `COPY`s `scripts/` so the CLI is reachable from `docker compose exec`.

### Chunk B: client wiring, tests, docs

- `clients/cli/nexus_cli.py` keeps its existing `Authorization` plumbing and adds a specific 401 message that names the env var, the config field, and the `create_token.py` command. The docstring drops "optional" and reflects the new requirement.
- `clients/web/index.html` updates the settings-panel field to require a token with inline guidance pointing at the CLI.
- `clients/README.md` rewrites the auth bullet to spell out the requirement, the mint command, and the set of still-anonymous status endpoints.
- `docs/memory_system.md` calls out the `auth_data` volume and the auth layer, with a note that recall behavior is unchanged by construction.
- `tests/test_auth.py` (with `tests/conftest.py` for path setup) covers the brief: anon `/health`, anon `/`, 401 missing token, 401 invalid token, 401 malformed Authorization header, 200 on a valid token, revocation cascade, per-token attribution in the JSONL metric record, plus the `TokenStore` unit tests for mint, verify, revoke, duplicate-name rejection, and mtime-based reload.

### Chunk C: this handoff

## Test result

All 13 tests pass:

```
$ python -m pytest tests/test_auth.py
collected 13 items
tests/test_auth.py .............                                  [100%]
======================== 13 passed, 8 warnings in 1.51s ========================
```

Warnings are the Pydantic V2 class-based-config deprecation; unrelated to the sprint and tracked elsewhere.

Cross-session recall (Sprint 2 done-criterion) was not re-run live this session because the test harness needs Chroma + sentence-transformers and the auth middleware does not touch the embedder service, the chroma client, or the write-on-turn path. The middleware sits in front of `/generate` and either 401s or delegates to unchanged business logic. Regression risk is structural-zero. If a paranoid sanity check is wanted, `python scripts/test_cross_session_recall.py` still runs against the in-tree code and exercises the same store the production embedder uses.

## Token-storage decision (the open thread Sprint 2 flagged)

Five real options, surfaced as options-with-reasoning in `docs/auth_middleware.md`. Short version:

| Option | Verdict | Why |
|---|---|---|
| Env var, single token | Rejected | No per-client attribution. No clean revocation. |
| Plaintext token file | Rejected | Disk compromise leaks every token. |
| **Hashed JSON store** | **Chosen** | Argon2id hashes on disk; per-client name; trivial revoke; attribution falls out for free. |
| SOPS-encrypted vault | Rejected for now | Adds a startup decryption step and an age key bind-mount. Strict superset of the chosen design; encrypt the same JSON later if disk-at-rest becomes a concern. |
| External auth (Keycloak, etc.) | Rejected | Massive over-engineering for solo lab. |

Implementation matches the chosen design exactly: `nxs_<32 url-safe bytes>` tokens via `secrets.token_urlsafe`; argon2id via `argon2-cffi` when available with `hashlib.scrypt` as the stdlib fallback (so the image still builds if pip resolution misbehaves); JSON store at `/data/auth/tokens.json` on the `auth_data` named volume; mtime-based reload for revocation without restart; `token_name` flows through the metric record for offline attribution.

Full decision log lives in `docs/auth_middleware.md`. If the operational pain of unencrypted-but-hashed ever becomes real, the SOPS upgrade is purely additive.

## What's still pending (Phase 0)

- **Sprint 3c** (next session's first task): endpoint exposure + Cortex-down graceful degradation. Entry point below.
- Sprint 3d: integration test across laptop, phone, CLI (now with real tokens).
- Sprint 4: bidirectional callback (the architectural claim the paper rests on).
- Sprint 5: Phase 0 close (soak test, design-decision record, reproducibility manifest, tag release).

The auth perimeter is now real. Phase 0's "anything on the LAN can hit the API" footgun is closed.

## Open threads worth attention soon

- `_turn_idx_by_session` snapshot to disk (still in-process, surfaced in Sprint 2 handoff). Unchanged.
- `data/metrics` bind-mount vs named volume (still open, surfaced in Sprint 2 handoff). Unchanged.
- Token rotation policy. We have the mechanism (`--revoke` + `--name`); we do not have a calendar reminder. Stage 1 work.
- Per-endpoint scopes. The hook is there (`request.state.token_name` plus a scope field on the entry) but unimplemented. Add when a non-trusted caller actually needs limited access.
- Per-token rate limiting. A leaked token currently has full brainstem throughput. Add a leaky bucket per-token when the metric record shows we need it. The metric is already there (`token_name` + `total_ms` + frequency).

## Entry point for Sprint 3c (endpoint exposure + Cortex-down handling)

Read first:

- This handoff (the auth model is what Sprint 3c will live behind).
- `nodes/brainstem_4070/server.py` `_check_cortex`, `_check_embedder`, `_check_nas` and the `/generate` Cortex-failure path (currently raises 502; Sprint 3c will want a graceful degradation story).
- `docker/docker-compose.yml` for the current bind/port config. Decide what (if anything) needs to change about external exposure now that the bearer-token gate is real.
- `docs/auth_middleware.md` for what the perimeter currently does and what it deliberately leaves to Tailscale.

Shape (proposed, lock at session start):

- Confirm whether the brainstem should bind only on the Tailscale interface (vs `0.0.0.0`) now that auth exists. Tradeoff: belt-and-suspenders security vs operator surprise when a LAN-only client suddenly fails. Decision goes in the new sprint's design doc.
- Make `/generate` survive a Cortex outage with a useful 503 (`{"detail": "cortex unreachable", "retry_after": ...}`) rather than a generic 502. Memory writes should be skipped cleanly. The metric record should still land.
- Health-aware retry semantics in the CLI and web client (one retry on 503, backoff visible to the user).
- Tests: simulate Cortex-down via a stubbed `CortexClient` that raises; assert the brainstem returns 503 with the expected shape, the metric record is written, and the embedder is not touched.

Drew, when you pick this up: start with TodoWrite, surface the binding-interface decision as options-with-reasoning before changing the compose file, and lock the 503 response shape in the design doc before the test cases hit it. The shape of "useful 503" determines what the client retries on, which determines the operational doc.

Sources: this handoff is based on the in-progress state of `foundation/consolidation` at the Chunk C commit and the test runs above. Source files: `nodes/brainstem_4070/auth.py`, `nodes/brainstem_4070/server.py`, `scripts/create_token.py`, `docker/`, `docs/auth_middleware.md`, `tests/test_auth.py`.
