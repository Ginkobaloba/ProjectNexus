# Auth middleware (Sprint 3b)

Status: design + decisions for Sprint 3b. Implementation lives in `nodes/brainstem_4070/auth.py`, the CLI in `scripts/create_token.py`, and the tests in `tests/test_auth.py`.

## Problem

The brainstem exposes `/generate`, `/embed`, `/stm/write`, and the embedder pass-through with no authentication. Today the only access control is Tailscale ACL plus LAN scoping. Anything on the tailnet or the LAN can hit those endpoints. That is circumstantial defense, not designed defense.

Sprint 3b adds the first explicit access-control layer to the fabric. Tailscale ACL remains the perimeter; this middleware is depth-in-defense.

## Constraints

Solo user. Multiple clients (laptop CLI, phone web, future Jetson, future scheduled jobs). Long-lived tokens are fine because the tokens never leave devices the user controls. The blast radius of a leaked token is "anyone who has it can talk to my brainstem until I revoke it," which is acceptable as long as revocation is trivial and per-token attribution is logged so a leak is detectable.

No human team. No need for OIDC, SSO, MFA, or audit trails beyond a per-request log line.

Phase 0 single-process brainstem. The token store has to live somewhere durable across container restarts but does not need cross-host replication yet.

## Token-storage decision (the open thread the Sprint 2 handoff flagged)

Five real options considered. Decision recorded here, not in code comments, because the choice shapes the rotation story and the operational doc.

### Option 1: env var, single token

`BRAINSTEM_AUTH_TOKEN=...` set by docker-compose. Middleware compares against the env var literal.

Pros: smallest possible diff. No file I/O. Trivial to reason about.

Cons: one token across all clients. No per-client attribution in the metric record. Rotation forces every client to update at the same instant. Token sits in plaintext in the compose file or the host shell env and shows up in `docker inspect`.

Verdict: rejected. The handoff explicitly asked for per-client tokens, attribution, and revocation. This option fails the brief on all three.

### Option 2: plaintext token file, one token per line

`/data/auth/tokens.txt` mounted as a named volume. Each line is `<name>\t<token>`. Middleware loads on every request (or caches with a file-mtime check) and compares strings.

Pros: revoke by deleting a line. Per-client attribution by name. Fast verification (string equality).

Cons: tokens sit in plaintext on disk. Anyone with file read on `/data/auth` (host root, a sidecar container with the same mount, a backup that includes the volume) gets every token. Backup hygiene becomes a security control. This is the same failure mode that turned "password files" into "password hash files" forty years ago.

Verdict: rejected. The cost of upgrading to hashed storage is small; the upside is large enough that it would be embarrassing to ship plaintext on purpose.

### Option 3: hashed token JSON store (recommended)

`/data/auth/tokens.json` mounted as a named volume. Each entry holds `{name, hash, created_at, last_used_at, use_count}`. The hash is argon2id (or scrypt as a fallback if argon2-cffi is unavailable in the image). Tokens themselves are generated on the brainstem by the CLI, printed to stdout once, never persisted in plaintext.

Pros:
- Disk compromise leaks names and hashes, not tokens. An attacker has to crack each hash offline against the argon2id work factor.
- Per-client attribution falls out: log the matching entry's name on every authenticated request.
- Revocation is one line: drop the entry, save the file.
- "Token created once, shown once, lost if you lose it" matches every modern API key UX, so the operator instinct is already correct.

Cons:
- Verification is O(n) in tokens, because each entry has its own salt and we cannot index by hash. n stays small (under ~10 for solo-user-with-multiple-clients), so this is a non-issue.
- argon2-cffi adds a Python dep. It is a thin wrapper over the reference C library, widely deployed, has been in PyPI's top 1k for years. Acceptable.

Verdict: chosen. Implementation uses `argon2-cffi` when importable, `hashlib.scrypt` from the stdlib as a documented fallback so the image still builds if pip resolution misbehaves. The fallback path is functionally equivalent at our scale; the upgrade is the default.

### Option 4: SOPS-encrypted token vault

Reuse the SOPS + age setup `SECRETS.md` describes. Tokens stored as ciphertext, decrypted at brainstem boot, kept in memory only.

Pros: tokens on disk are already in their final encrypted form. Aligns with the rest of the secret story in this repo.

Cons:
- Adds a startup-time decryption step and an age key bind-mount that the brainstem container does not currently need.
- The decrypted tokens still have to live somewhere for verification. If we hash them at boot to avoid keeping plaintext, we have built Option 3 with extra steps. If we keep plaintext in memory, a process dump leaks the lot.
- Revocation requires re-encrypting and a brainstem restart, or a brainstem-side reload signal. More moving parts.

Verdict: rejected for this sprint. If we later want offline-readable tokens, we can SOPS-encrypt the same JSON file Option 3 writes, gaining encrypted-at-rest with no other API changes. That is a strict superset and a clean upgrade path, not a fork.

### Option 5: external auth (Keycloak, Auth0, Authentik, etc.)

Pros: real OIDC. Federated identity if a team ever shows up.

Cons: massive over-engineering for a solo lab. Adds a whole new dependency, a new container, a new failure mode that takes the whole fabric down when the auth server is unreachable. Nothing in the brief requires it.

Verdict: rejected. The day a second human gets a login on this stack, revisit.

## Chosen design

Token format: `nxs_<32 url-safe random bytes>` from `secrets.token_urlsafe(32)`. The `nxs_` prefix is a soft tag so a token leaking into a log is recognizable. ~43 chars of entropy after the prefix.

Storage: `/data/auth/tokens.json`. Schema:

```json
{
  "version": 1,
  "kdf": "argon2id",
  "tokens": [
    {
      "name": "laptop",
      "hash": "$argon2id$v=19$m=65536,t=3,p=4$...",
      "created_at": "2026-05-17T12:00:00+00:00",
      "last_used_at": null,
      "use_count": 0
    }
  ]
}
```

`kdf` is `"argon2id"` when argon2-cffi is installed, `"scrypt"` for the stdlib fallback (in which case `hash` is `$scrypt$N=...,r=...,p=...$<b64 salt>$<b64 hash>`, a format we own because stdlib has no PHC-string helper).

Volume: docker named volume `auth_data`, mounted into the brainstem container at `/data/auth`. Survives container restarts and rebuilds. The mount path is configurable via `BRAINSTEM_TOKEN_STORE_PATH` for local-dev runs outside docker.

Middleware: a FastAPI dependency `require_token` that:
1. Reads `Authorization: Bearer <token>` off the request.
2. If missing or malformed, returns 401 with `{"detail": "missing or invalid Authorization header"}` and no further work.
3. Iterates the loaded token entries, runs `verify(hash, token)` for each, short-circuits on first match.
4. If no match, returns 401 with `{"detail": "invalid token"}`. Constant-ish time across the entry set because every miss runs all the verifies; we accept the cost (n is tiny).
5. On match, updates `last_used_at` and `use_count` in-memory (debounced flush to disk every 60 s) and attaches `(name, token_id)` to `request.state` for downstream use (per-request log line, metric attribution).

Excluded endpoints (still anonymous): `/health`, `/cortex/health`, `/embedder/health`, `/fabric/status`, `/dashboard`, `/` (the JSON root pointer). These are status-only and used by monitoring; auth-gating them would force the dashboard and any external uptime check to carry a token, which has no upside.

Token CLI: `python scripts/create_token.py`:
- `--name <name>` mints a token, hashes it, appends to the store, prints the plaintext token once.
- `--list` prints `name, created_at, last_used_at, use_count` for each entry.
- `--revoke <name>` removes the named entry.
- `--store <path>` overrides the default store path (lets the script run against an arbitrary store, e.g. for dev or for a different host).

Per-token attribution: the metric record gets a new `token_name` field, populated from `request.state.token_name` on `/generate`. Backfills cleanly: missing on records from before this sprint, present after.

## Operational notes

Token creation runs on the brainstem host so the token never travels over the network. Operator runs `docker compose exec brainstem python scripts/create_token.py --name laptop`, captures the printed token, pastes it into the client's config or environment, and the entry in `/data/auth/tokens.json` already holds the hash. The plaintext token never touches the host filesystem; if the operator wants to write it down, the operator chooses where.

Rotation: mint a new token with the same client name, update the client, revoke the old one. Or just `--revoke laptop` and re-mint. There is no token-lifetime check in the middleware on purpose: revocation is the only expiration story, and it is explicit.

Logging: every authenticated request logs `auth ok: token=<name>` at info level. Every rejected request logs `auth fail: <reason>` at warn level. No token plaintext ever appears in logs.

Tailscale ACL still owns the perimeter. The middleware presumes the request already passed an outer access control; it does not try to be the only gate. The two layers together cover "the wrong device cannot even reach the port" plus "even if it does, it cannot make a real request."

## What this leaves for later

- Token rotation policy. We have the mechanism (revoke + mint); we do not have a calendar reminder. Stage 1 work.
- Per-token rate limiting. A leaked token currently has full access at the brainstem's throughput. Add a leaky bucket per-token when the metric record shows we need it.
- Per-endpoint token scopes (e.g., a "monitoring" token that can hit `/fabric/status` only). The hook is there (`request.state.token_name` plus a scope field on the entry), unimplemented for now. Add when a non-trusted caller actually needs limited access.
- SOPS-at-rest for the token store. Strict superset of the current design; flip when the operational pain of unencrypted-but-hashed becomes real.
