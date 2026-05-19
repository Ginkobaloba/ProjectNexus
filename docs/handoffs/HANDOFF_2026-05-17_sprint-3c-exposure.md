# Handoff: 2026-05-17 Sprint 3c (endpoint exposure + Cortex-down graceful degradation)

Status: code complete on `foundation/consolidation`, all tests green
(22/22 across `tests/test_auth.py` and `tests/test_cortex_down.py`).
Commit and push were not run from the agent session because the .git
index was in a pre-existing lock-and-stale-rename state that
PowerShell-side cleanup will resolve cleanly. The PowerShell commands
to run, in order, are at the bottom of this handoff.

## What shipped

Two related concerns that Sprint 3b's auth landing exposed:

1. The brainstem container's published port was reachable on every host
   interface, even though the auth perimeter now demanded the outer
   perimeter also be the Tailscale interface.
2. A Cortex outage produced a generic 502 with free-text `detail`,
   which gave clients no way to retry intelligently and gave the
   operator no way to tell apart "Cortex is starting up" from
   "Cortex took the request and timed out."

Both are fixed.

### Tailscale-only bind (host-side)

`docker/docker-compose.yml` now binds the published port to a single
host interface via Docker's `HOST_IP:HOST_PORT:CONTAINER_PORT` syntax:

```yaml
ports:
  - "${BRAINSTEM_BIND_HOST:-127.0.0.1}:5001:5001"
```

Inside the container the brainstem still listens on `0.0.0.0:5001` so
the compose-network peers (embedder, nas) can reach it and the new
healthcheck can hit it. The host-side bind is what is restricted to
the Tailscale interface; Docker's iptables rules drop traffic on every
other host interface.

The bind host comes from `docker/.env` (gitignored, per-host operational
fact). A template lives at `docker/.env.example`:

```
BRAINSTEM_BIND_HOST=100.89.210.52
```

Tailscale IP rotation is a one-command fix:

```
scripts/setup/refresh-tailscale-bind.ps1
```

The PowerShell helper reads `tailscale ip -4`, picks the 100.x CGNAT
address, and rewrites the `BRAINSTEM_BIND_HOST=` line in `docker/.env`.
A laptop dev workflow with no Tailscale install falls through the
`${...:-127.0.0.1}` default expansion and stays runnable end to end.

### Cortex-down 503 contract

`POST /generate` returns `503 Service Unavailable` when the Cortex
client raises `CortexError` after its internal retries.

Body:

```json
{
  "error": "cortex_unavailable",
  "retry_after_seconds": 5,
  "message": "Cortex (4090 inference peer) is unreachable. The brainstem is up; this is a transient downstream failure.",
  "session_id": "<the X-Session-Id the caller sent>",
  "turn_idx": null
}
```

Header: `Retry-After: 5` (RFC 7231; same integer the body carries).

Two error codes:

- `cortex_unavailable` (connection refused, reset, DNS, OS error) ->
  `retry_after_seconds = 5` by default. The 4090 looks like it has not
  finished coming up.
- `cortex_timeout` (anything with "timeout" / "timed out" in the
  message) -> `retry_after_seconds = 15` by default. Cortex took the
  request, the model is just slow.

Both knobs are config-overridable
(`BRAINSTEM_CORTEX_DOWN_RETRY_AFTER_SECONDS`,
`BRAINSTEM_CORTEX_TIMEOUT_RETRY_AFTER_SECONDS`). Memory writes are
skipped cleanly on the failure path (no assistant text to embed). The
metric record still lands with `ok: false` and `token_name: <name>`,
so the per-token attribution stays intact in the dashboard view.

### Request-time vs periodic probe (decision)

Request-time. Every incoming `/generate` tries the Cortex call and
catches the connection-class error; no shared state, no background
task. The CortexClient already retries once internally and the health
timeout is short, so the worst-case latency a hard-down peer adds is
bounded. If a production load profile ever shows the timeout cost as a
real problem, swap in a periodic probe; the 503 contract this sprint
locks does not change. The full rationale is in
`docs/exposure_and_cortex_down.md`.

### Client behavior on 503

CLI (`clients/cli/nexus_cli.py`):

- A new `CortexDownError` (subclass of `BrainstemError`) carries
  `retry_after_seconds` and the `error` code.
- `_call_with_cortex_down_retry` does exactly one informed retry,
  capped at 30s, with a `[cortex down] ... retrying in Ns...` stderr
  line so the user sees what is happening.
- A second 503 surfaces a `cortex still unavailable after one retry`
  message and the REPL stays open.

Web (`clients/web/index.html`):

- `generateOnce` / `parseCortexDownBody` / `retryAfterSeconds` / `sleep`
  helpers handle the round trip and the body parse defensively.
- On the first 503 the page renders an inline `system`-style message
  with the human-readable message and a "Retrying in Ns..." countdown,
  sleeps, and retries.
- A second 503 renders an `error` bubble with the human message and a
  "Try again in about N seconds" line.

### Healthcheck

`docker/docker-compose.yml` now defines a brainstem healthcheck that
hits `http://127.0.0.1:5001/health` inside the container. `/health` is
explicitly independent of Cortex (it only probes the embedder), so a
Cortex outage does not take the brainstem out of rotation from a
load-balancer's perspective. A regression test pins that property.

### Docs

- `docs/exposure_and_cortex_down.md` (new) - the design doc. Options
  considered for the bind, the chosen approach (Docker
  `HOST_IP:HOST_PORT:CONTAINER_PORT`), the 503 contract, request-time
  vs periodic rationale, rollout notes.
- The root `/` index endpoint now publishes a `cortex_down_contract`
  block so a client poking the URL can discover the 503 shape. A test
  pins this so the contract is self-describing.

### Tests

`tests/test_cortex_down.py` (new), 9 cases:

```
$ python -m pytest tests/test_cortex_down.py -v
collected 9 items
tests/test_cortex_down.py::test_generate_returns_200_when_cortex_up PASSED
tests/test_cortex_down.py::test_generate_returns_503_when_cortex_unreachable PASSED
tests/test_cortex_down.py::test_generate_503_classifies_timeout_separately PASSED
tests/test_cortex_down.py::test_metric_record_lands_on_cortex_down PASSED
tests/test_cortex_down.py::test_health_stays_200_while_cortex_down PASSED
tests/test_cortex_down.py::test_root_documents_cortex_down_contract PASSED
tests/test_cortex_down.py::test_dev_fallback_bind_is_loopback PASSED
tests/test_cortex_down.py::test_dev_fallback_bind_respects_env PASSED
tests/test_cortex_down.py::test_brainstem_config_exposes_retry_knobs PASSED
======================== 9 passed in 0.93s ========================
```

Full suite (Sprint 3b auth + Sprint 3c): **22 passed, 0 failed**.

The four cases the brief asked for are all there, plus a regression
on the metric record, a regression on the `/` self-description, the
timeout classification split, and the config-knob existence check.

## Tailscale-bind decision rationale (one-paragraph)

We chose Docker's `HOST_IP:HOST_PORT:CONTAINER_PORT` port-publish
syntax rather than container-side bind-address logic, host networking,
or a tailscaled sidecar. The reason is shape: the bind constraint is
about which host interface receives traffic, which is exactly what
Docker's port-mapping is designed to express. Container-side bind
logic would have required talking to the host's tailscaled (which the
bridge network does not expose), and host networking would have
broken the compose-network DNS that embedder and nas rely on. The
chosen approach keeps the inside-the-container service config
unchanged, lets the embedder/nas mesh keep working untouched, gives
the operator a one-knob (`BRAINSTEM_BIND_HOST` in `docker/.env`)
control surface that survives Tailscale IP rotation via a small
PowerShell helper, and falls back cleanly to `127.0.0.1` for a fresh
laptop checkout without Tailscale installed. The full options-with-
reasoning table is in `docs/exposure_and_cortex_down.md`.

## Open threads worth attention soon

- The `_turn_idx_by_session` snapshot-to-disk thread (Sprint 2). Still
  in-process. Unchanged this sprint.
- `data/metrics` bind-mount vs named volume (Sprint 2). Unchanged.
- Per-token rate limiting (Sprint 3b). Unchanged; still a future
  refinement when the metric record shows the need.
- A periodic Cortex probe (Sprint 3c). The request-time path we shipped
  is the simpler answer; a periodic prefetcher is the next optimization
  if the connection-timeout cost becomes a real problem.
- The brainstem healthcheck assumes `urllib` is in the runtime image
  (it is, via stdlib) but does not test the auth perimeter. If a future
  refactor moves the liveness probe behind auth, the healthcheck will
  start 401-ing; this is documented in the design doc.
- The CLI's `_extract_cortex_down_body` reads the HTTPError body once
  and stashes the parsed dict. If a future error path also wants to
  read the body, it gets an empty dict on the second call. The body
  buffer dance from the earlier draft was a complication that the
  current shape removes; this is fine because the only caller is the
  503 handler.

## Entry point for Sprint 3d (laptop / phone / CLI integration test)

Sprint 3d closes the loop the architecture has been promising since
Stage 0 Sprint 3 opened: real client devices talking to the brainstem
over Tailscale, with auth, with the 503 retry working end to end. The
shape:

- On the 4070: write `docker/.env` from `docker/.env.example` (or run
  `scripts/setup/refresh-tailscale-bind.ps1`), `docker compose down`,
  `docker compose up -d`, verify the brainstem's port is bound only
  on the Tailscale interface (`netstat -an | findstr 5001`).
- Mint three tokens (`laptop`, `phone`, `cli`) via
  `docker compose exec brainstem python scripts/create_token.py --name <name>`.
- From the laptop, hit `http://100.89.210.52:5001/health` and
  `/generate` (auth required). Confirm the LAN-only path is now
  refused (`http://192.168.1.251:5001/...` should be unreachable).
- From the phone, load `clients/web/serve.py` proxied to the
  Tailscale target. Confirm the chat works, then kill the 4090's vLLM
  and confirm the friendly "retrying in 5s..." line appears, then
  bring vLLM back and confirm the second attempt succeeds.
- From the CLI, the same sequence: `python clients/cli/nexus_cli.py
  --prompt "ping" --target tailscale` while Cortex is up, then while
  Cortex is down (one auto-retry, then the human-readable error).

Read first:

- This handoff.
- `docs/exposure_and_cortex_down.md` for the 503 contract and the
  bind-host design.
- `docs/auth_middleware.md` for the token model the integration test
  will exercise.
- `nodes/brainstem_4070/server.py` `_cortex_down_response` and the
  `/generate` failure branch.
- `clients/cli/nexus_cli.py` `_call_with_cortex_down_retry` and the
  `clients/web/index.html` `sendPrompt` 503 branch for the client
  side of the contract.

Sprint 3d's done-criterion is the "visible win" Stage 0 Sprint 3
promised: a real phone, in your hand, off the home LAN, talking to
the 4070 through Tailscale, with the 4090 producing the text, and the
503 path obviously working when Cortex blinks. Tag the commit when it
passes.

## Commit + push commands (run via PowerShell on the 4070 host)

The agent session's Linux sandbox could not clear the stale
`.git/index.lock` (Windows ACL state), so the commits should run from
PowerShell on the host. Defensive lock cleanup first, then commit in
two clean chunks:

```powershell
# 1. defensive lock cleanup
if (Test-Path .git\index.lock) { Remove-Item .git\index.lock -Force }

# 2. reset the stale index entries from prior session state
git reset HEAD

# 3. chunk A: brainstem 503 contract + bind + tests + design doc
git add nodes/brainstem_4070/server.py `
        nodes/brainstem_4070/config.py `
        docker/docker-compose.yml `
        docker/.env.example `
        scripts/setup/refresh-tailscale-bind.ps1 `
        tests/test_cortex_down.py `
        docs/exposure_and_cortex_down.md
git commit -m "sprint-3c chunk A: tailscale-only bind + cortex-down 503 contract + tests"

# 4. chunk B: client wiring (CLI + web) for the 503 retry
git add clients/cli/nexus_cli.py clients/web/index.html
git commit -m "sprint-3c chunk B: CLI + web 503 retry handling"

# 5. chunk C: this handoff
git add docs/handoffs/HANDOFF_2026-05-17_sprint-3c-exposure.md
git commit -m "sprint-3c chunk C: handoff"

# 6. push
git push origin foundation/consolidation
```

The other in-flight changes the working tree shows
(`clients/README.md`, `docker/brainstem.Dockerfile`,
`nodes/brainstem_4070/embed.py`, the various handoff files with
CRLF-vs-LF flux, the deleted-or-renamed papers, etc.) are pre-existing
state from the prior session and are not part of Sprint 3c. They
should be left to a separate cleanup pass; mixing them into Sprint 3c
would muddy the commit history this handoff describes.

Sources: this handoff is based on the in-progress state of
`foundation/consolidation` plus the full test runs above. Source files:
`nodes/brainstem_4070/server.py`, `nodes/brainstem_4070/config.py`,
`docker/docker-compose.yml`, `docker/.env.example`,
`scripts/setup/refresh-tailscale-bind.ps1`, `clients/cli/nexus_cli.py`,
`clients/web/index.html`, `tests/test_cortex_down.py`,
`docs/exposure_and_cortex_down.md`.
