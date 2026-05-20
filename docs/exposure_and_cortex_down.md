# Sprint 3c design: Tailscale-only exposure + graceful Cortex-down

Two related concerns picked up after Sprint 3b's auth landing:

1. The brainstem container currently binds on `0.0.0.0:5001` and Docker
   publishes that on every host interface. Auth is the inner perimeter;
   the outer perimeter should be the Tailscale interface. Anything that
   only reaches the host over the LAN should not even see a listening
   socket on the brainstem port.
2. When the 4090 Cortex peer is unreachable, the brainstem currently
   raises a generic 502 with a free-text `detail`. Clients see "Cortex
   unreachable" but cannot tell whether to retry, when to retry, or
   whether the brainstem itself is the problem. The contract should be
   sharper.

This doc locks the design before the code changes. Implementation lives
across `nodes/brainstem_4070/server.py`, `nodes/brainstem_4070/config.py`,
`docker/docker-compose.yml`, `clients/cli/nexus_cli.py`,
`clients/web/index.html`, and `tests/test_cortex_down.py`.

## Tailscale-only bind: options considered

The container has to listen on the Tailscale interface and nothing
else. The constraint is that the brainstem also has to keep talking to
the `embedder` and `nas` services over the compose bridge network, so a
naive "switch to host networking" choice breaks the rest of the stack.

The options I weighed:

**A. Hard-code the Tailscale IP in an env var.**
Simple, fully deterministic. Brittle: a Tailscale IP rotation (rare but
real) breaks the brainstem until someone updates the env. Couples host
config to container config in a way that is annoying when you want to
move the 4070 host around.

**B. Discover the Tailscale IP inside the container at startup.**
Container would need to talk to the host's tailscaled, which is not
exposed by the bridge network. You can hack around it (bind-mount the
tailscale socket, run tailscaled in a sidecar) but every variant adds a
moving part. Phase 0 cost is too high.

**C. Host networking for the whole stack.**
Lets the brainstem bind directly to `tailscale0`. Loses compose-network
DNS, so `embedder` and `nas` would need to be reached on explicit ports
on `127.0.0.1`. Workable, but a real regression in the stack's
"compose-up and it works" property.

**D. Per-container host networking just for brainstem.**
Same as C with the same DNS problem, plus an asymmetric topology that
will trip future-me up.

**E. Docker port binding to a specific host interface (`HOST_IP:CONTAINER_PORT:HOST_PORT`).**
The chosen option. The brainstem still binds `0.0.0.0` inside the
container (so it can reach embedder/nas via the compose bridge and the
liveness probe still works), but Docker only publishes the port on the
specified host IP. Docker's iptables rules drop traffic on every other
host interface. The compose-network DNS keeps working untouched. IP
rotation is handled by re-reading `tailscale ip -4` at compose-up via
the `.env` file pattern. A `BRAINSTEM_BIND_HOST` env var with a
`127.0.0.1` default makes the dev workflow (laptop, no Tailscale)
identical to before.

E is what the rest of this doc assumes.

## Chosen design (option E)

In `docker/.env` (operator-maintained, gitignored):

```
BRAINSTEM_BIND_HOST=<REDACTED_TAILSCALE_IP>
```

In `docker/docker-compose.yml`:

```
brainstem:
  ports:
    - "${BRAINSTEM_BIND_HOST:-127.0.0.1}:5001:5001"
```

Default to `127.0.0.1` so a fresh checkout without a `.env` is still
runnable end to end on the developer's laptop. On the production 4070
the operator writes the Tailscale IP into `.env` before the first
compose-up. A helper script `scripts/setup/refresh-tailscale-bind.ps1`
captures the current Tailscale IP via `tailscale ip -4` and writes the
result back to `docker/.env`, so a Tailscale IP rotation is a
one-command fix rather than a code change.

Tradeoffs surfaced:

- Operator surprise. Someone on the LAN who got used to hitting
  `http://<REDACTED_LAN_IP>:5001` will get connection refused now. The
  operational doc and the dashboard URL line both flag this.
- Localhost still works on the 4070 host itself because Docker's port
  bind on `<REDACTED_TAILSCALE_IP>` does not block `127.0.0.1` traffic that goes
  through the loopback. If localhost-from-host stops working in some
  unexpected setup we can publish the port twice (once on Tailscale,
  once on `127.0.0.1`).
- The bind is per-host, not per-tenant. Same Tailscale IP, same
  brainstem, same audience. This is the right shape for Phase 0.

## Cortex-down handling: request-time vs periodic probe

Two patterns are common:

**Request-time:** every incoming `/generate` tries the Cortex call. If
the underlying client raises a connection-class error, return 503. No
shared state, no background tasks, no race conditions, fail-open is
the natural behavior (Cortex comes back, the very next request just
works).

**Periodic:** a background task pings `/v1/models` every N seconds and
flips an in-process flag. Requests during the "Cortex down" window
short-circuit to 503 without waiting for the connection timeout. Saves
the timeout cost on every queued request but pays a complexity cost in
state management, probe scheduling, and the timing window between
"Cortex came back" and "the next probe noticed."

Request-time wins for Sprint 3c. The CortexClient already retries
once internally and the health-check timeout is short (5s), so the
worst-case latency added by a hard-down peer is bounded and small
relative to a generation call. The complexity savings are real. If a
real production load profile later shows the per-request timeout cost
as a problem, swap in the periodic pattern; the 503 contract this doc
locks does not change.

## 503 response contract

Returned by `/generate` (and any other endpoint that hard-depends on
Cortex) when the Cortex client raises `CortexError` after its internal
retries.

Status: `503 Service Unavailable`.

Headers:

- `Retry-After: <seconds>` per RFC 7231 section 7.1.3. Clients that
  honor the standard header get the retry hint for free.

Body (JSON):

```json
{
  "error": "cortex_unavailable",
  "retry_after_seconds": 10,
  "message": "Cortex (4090 inference peer) is unreachable. The brainstem is up; this is a transient downstream failure.",
  "session_id": "abc-...",
  "turn_idx": null
}
```

Field contract:

- `error` is a stable machine-readable code. Clients branch on this,
  not on the human-readable message. Stable values are
  `cortex_unavailable` (the 4090 was not reachable or returned an
  error after retries), `cortex_timeout` (the connection succeeded but
  the generation call exceeded the timeout window), and reserved for
  future: `cortex_overloaded` (Cortex returned a 503 of its own).
- `retry_after_seconds` is the same integer the `Retry-After` header
  carries. It is small but non-zero. Phase 0 picks: `5` for connection
  errors (probably starting up), `15` for timeouts (the model is
  responding but slow), and `30` for repeated failures. Sprint 3c
  ships with the simple constant `5` and a config knob; the
  per-failure-type variant is a Sprint 3d-or-later refinement.
- `message` is human-readable and explicitly disambiguates "the
  brainstem itself is fine" so an operator reading the dashboard does
  not chase the wrong box.
- `session_id` and `turn_idx` are echoed so a client can correlate the
  503 with the request it sent. `turn_idx` is `null` because no turn
  was actually written.

Memory writes are skipped cleanly when Cortex fails: there is no
assistant text to embed. The metric record still lands so the
operational view sees the failure and the per-token attribution stays
intact.

## Client behavior on 503

Both clients show a friendly "Cortex is down, retrying in Ns" message
and do **one** automatic retry honoring `Retry-After`. If the retry
also 503s, the client surfaces the human-readable message and stops
auto-retrying. The user can re-send if they want.

The CLI prints to stderr and continues the REPL. The web client
renders an inline `error`-style message bubble with the message and
the retry countdown.

## Test cases (the four the brief calls for)

- `/generate` returns 200 when the (stubbed) Cortex is up. Already
  covered by Sprint 3b's `test_generate_with_valid_token_returns_200`;
  we keep it as a regression anchor.
- `/generate` returns 503 with the structured body and the
  `Retry-After` header when the Cortex client raises. Stubbed by
  monkeypatching `cortex.generate` to raise `CortexError`. The
  response body matches the schema above; `retry_after_seconds` is an
  integer and the header is the same integer as a string.
- `/health` stays 200 while Cortex is down. Health does not depend on
  Cortex; the existing endpoint already only checks the embedder. A
  test pins this so a future refactor cannot regress it.
- The dev fallback bind works. A test boots the app and checks the
  resolved config bind host is `127.0.0.1` when `BRAINSTEM_BIND_HOST`
  is unset, and the configured value when it is set.

## Rollout

The bind change is operational: `docker compose down && docker compose up -d`
on the 4070 after writing the new `.env` file. The 503 contract is
purely additive on the brainstem side; old clients that did not
understand 503 will see "Brainstem returned HTTP 503" which is no
worse than the prior generic-error path. Updated CLI and web clients
do the friendly retry.
