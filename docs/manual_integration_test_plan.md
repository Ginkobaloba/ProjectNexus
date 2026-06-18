# Manual integration test plan: Sprint 3d

Companion to the automated suite at `tests/integration/`. This plan
walks the brainstem end-to-end from each real client surface: laptop
browser, phone browser, CLI. Every step is one curl, one click, or one
CLI invocation, and every step has an EXPECTED RESULT. Format is a
flat checklist so you can run it during a coffee.

## Prerequisites

Before you run this plan, confirm:

- The 4070 host has the brainstem stack up: `docker compose ps` in
  `docker/` shows `brainstem`, `embedder_4070`, and `nas_memory`
  healthy.
- The 4090 host is reachable from the 4070: the brainstem's
  `/cortex/health` reports `reachable: true`.
- Tailscale is up on both the 4070 host and the device you are testing
  from. The brainstem's Tailscale URL is in `clients/config.json` under
  `targets.tailscale`.
- You have at least two minted tokens for this run. Mint them with:

  ```
  docker compose exec brainstem python scripts/create_token.py --name laptop
  docker compose exec brainstem python scripts/create_token.py --name phone
  ```

  Save each printed token somewhere you can paste it once. The
  brainstem only stores the hash, so a token you lose is gone for good.

Throughout this plan:

- `${BRAINSTEM_URL}` is the Tailscale URL of the brainstem
  (e.g. `http://100.89.210.52:5001`).
- `${LAPTOP_TOKEN}` and `${PHONE_TOKEN}` are the two tokens you just
  minted. Tokens never leave the device they were issued on; do not
  paste them into a chat window or commit them.

## Section A: Laptop browser

- [ ] **A1. Reach the web client.** Run `python clients/web/serve.py`
  on the laptop and open `http://localhost:8081/` in a browser.

  Expected: the page renders. Header reads "Nexus thin client". An
  input box and a Settings panel are visible.

- [ ] **A2. Configure the client.** Open Settings. Set the brainstem
  URL to `${BRAINSTEM_URL}`. Paste `${LAPTOP_TOKEN}` into the auth
  token field. Save.

  Expected: the page persists the values to localStorage. Reloading
  the page keeps both values.

- [ ] **A3. Send a prompt.** Type `Reply with the single word OK.`
  and submit.

  Expected: a response from Cortex appears within a few seconds. The
  footer shows model id, latency, and token counts. No console error
  in the browser devtools.

- [ ] **A4. Session id is stable.** Reload the page, send another
  prompt. Confirm the session id displayed in the page header is the
  same as before A3.

  Expected: same session id pre- and post-reload. The session id
  lives in localStorage; only the "new session" control mints a fresh
  one.

## Section B: Phone browser

- [ ] **B1. Reach the web client from the phone.** On a phone with
  Tailscale up, open `http://${LAPTOP_TAILSCALE_IP}:8081/` (where
  `serve.py` is still running on the laptop), or open
  `${BRAINSTEM_URL}/dashboard` for the brainstem's own dashboard if
  you also wired the static page to be served from the brainstem.

  Expected: the page renders at a phone viewport without horizontal
  scroll. Input, send button, and Settings are all reachable with one
  hand.

- [ ] **B2. Configure the phone client.** Open Settings. Set the
  brainstem URL to `${BRAINSTEM_URL}`. Paste `${PHONE_TOKEN}`. Save.

  Expected: values persist. Reload keeps them.

- [ ] **B3. Send a prompt from the phone.** Type a short prompt and
  submit.

  Expected: response within a few seconds. No layout breakage on
  iOS Safari or Android Chrome.

## Section C: CLI

- [ ] **C1. One-shot from CLI.** From any Tailscale-connected
  machine:

  ```
  NEXUS_AUTH_TOKEN=${LAPTOP_TOKEN} \
  python clients/cli/nexus_cli.py \
    --url ${BRAINSTEM_URL} \
    --prompt "Reply with the single word OK." \
    --quiet
  ```

  Expected: stdout is the model's reply. Exit code 0.

- [ ] **C2. REPL mode.** Run:

  ```
  NEXUS_AUTH_TOKEN=${LAPTOP_TOKEN} \
  python clients/cli/nexus_cli.py --url ${BRAINSTEM_URL}
  ```

  Expected: the banner prints. Typing a prompt and pressing enter
  returns a reply with a footer line. Slash commands `/session`,
  `/target`, and `/exit` work. `/new` mints a fresh session id and
  the new id is printed.

- [ ] **C3. Piped one-shot.** Run:

  ```
  echo "Reply with the single word OK." | \
    NEXUS_AUTH_TOKEN=${LAPTOP_TOKEN} \
    python clients/cli/nexus_cli.py --url ${BRAINSTEM_URL} --quiet
  ```

  Expected: stdout is the model's reply. Exit code 0.

## Section D: Cortex-down behavior

You can simulate Cortex being down by stopping vLLM on the 4090 OR by
pointing the brainstem at a bogus Cortex URL via
`BRAINSTEM_CORTEX_URL`. Pick the path that does not disrupt other
work; the cheap version is to set the URL to `http://127.0.0.1:1` and
restart the brainstem container.

- [ ] **D1. From CLI: 503 with retry message.**

  ```
  NEXUS_AUTH_TOKEN=${LAPTOP_TOKEN} \
  python clients/cli/nexus_cli.py \
    --url ${BRAINSTEM_URL} \
    --prompt "anything"
  ```

  Expected: stderr prints
  `[cortex down] Cortex (4090 inference peer) is unreachable... retrying in Ns...`
  followed by a second error if Cortex stays down. Exit code 1.

- [ ] **D2. From the web client: 503 with retry message.** With
  Cortex down, submit a prompt from the laptop browser.

  Expected: a system message appears reading something close to
  "Cortex is down. Retrying in N seconds...". After the retry window
  a second attempt is made; if still down, a final human-readable
  error renders. The session id stays the same.

- [ ] **D3. From curl: raw 503 contract.**

  ```
  curl -i -X POST ${BRAINSTEM_URL}/generate \
    -H "Authorization: Bearer ${LAPTOP_TOKEN}" \
    -H "X-Session-Id: sess_manual_503" \
    -H "Content-Type: application/json" \
    -d '{"prompt":"anything"}'
  ```

  Expected: `HTTP/1.1 503` with a `Retry-After: <int>` header. JSON
  body has `error` (either `cortex_unavailable` or `cortex_timeout`),
  `retry_after_seconds` matching the header, `session_id` of
  `sess_manual_503`, and a `message` that starts with
  `Cortex (4090 inference peer)...`.

- [ ] **D4. /health stays green during Cortex outage.**

  ```
  curl ${BRAINSTEM_URL}/health
  ```

  Expected: HTTP 200, body `{"status":"ok",...}`. The brainstem is
  up; a Cortex outage must not pull it out of rotation.

- [ ] **D5. Restore Cortex, confirm recovery.** Restart vLLM (or
  reset `BRAINSTEM_CORTEX_URL` and restart the brainstem). Re-run D1
  through D3.

  Expected: 200 with a real response. No leftover circuit-breaker
  behavior or stuck error state in the brainstem.

## Section E: Token revocation

- [ ] **E1. Revoke a token live.** On the 4070 host:

  ```
  docker compose exec brainstem python scripts/create_token.py --revoke phone
  ```

  Expected: stdout reports "revoked phone".

- [ ] **E2. Attempt to use the revoked token.** From the phone (or
  any client holding `${PHONE_TOKEN}`):

  ```
  curl -i -X POST ${BRAINSTEM_URL}/generate \
    -H "Authorization: Bearer ${PHONE_TOKEN}" \
    -H "X-Session-Id: sess_manual_revoke" \
    -H "Content-Type: application/json" \
    -d '{"prompt":"hello"}'
  ```

  Expected: `HTTP/1.1 401` with body `{"detail":"invalid token"}`. No
  brainstem restart required for the revocation to take effect.

- [ ] **E3. Other tokens still work.** Re-run C1 with
  `${LAPTOP_TOKEN}` to confirm only the revoked token is rejected.

  Expected: 200 with a real response.

## Section F: Cross-device session continuity

Sprint 2 done-criterion validated from the outside.

- [ ] **F1. Plant a fact from the laptop.** From the laptop CLI:

  ```
  NEXUS_AUTH_TOKEN=${LAPTOP_TOKEN} \
  python clients/cli/nexus_cli.py \
    --url ${BRAINSTEM_URL} \
    --session-id sess_xdev \
    --prompt "Remember this: my favorite mountain is Mount Rainier."
  ```

  Expected: 200 with a reply (the content doesn't matter; what
  matters is that the turn lands in memory under `sess_xdev`).

- [ ] **F2. Ask from the phone (same session id, different token).**
  On the phone, open the web client. In Settings, paste
  `${PHONE_TOKEN}` as the auth token AND override the session id
  field to `sess_xdev`. Submit:

  ```
  What is my favorite mountain?
  ```

  Expected: the reply references Mount Rainier, OR the
  retrieve-before-generate path injected the prior turn into the
  system prompt visible in the brainstem logs:

  ```
  docker compose logs brainstem --tail=50 | grep retrieved=
  ```

  The log line for the second request should show `retrieved=1` or
  greater. The model may or may not repeat "Rainier" verbatim, but
  the retrieval landed.

- [ ] **F3. Same flavor with a fresh session id.** Optional. Start a
  new session id on the phone (`/new` in CLI, "new session" in web).
  Ask the same question. Expected: retrieval STILL crosses sessions
  (cross-session recall is the Sprint 2 done-criterion), so the
  brainstem log still shows `retrieved>=1`.

## Section G: Things to test if you have time but aren't automatable

The automated suite stubs the network. Real-world failure modes that
the suite cannot reproduce, ordered by likelihood:

- [ ] **G1. Real Tailscale dropout mid-call.** Disable Tailscale on
  the laptop in the middle of an in-flight `/generate`. Expected: the
  CLI / web client surfaces a connection error rather than hanging
  indefinitely; the brainstem-side metric record still lands with
  `ok: false`.

- [ ] **G2. Real Cortex token-window exhaustion.** Send a prompt that
  pushes the served model past its `max_model_len`. Expected: vLLM
  returns an error the brainstem surfaces as a 502 with a useful
  detail, NOT a hung connection.

- [ ] **G3. Real network partition between brainstem and embedder.**
  Stop the embedder container, then send a prompt. Expected: the
  brainstem logs the embedder failure, continues with the caller's
  original system prompt (no retrieved context), and a 200 reply
  still lands. `memory_written` is `false` on the response, and the
  metric record shows the embedder failure path.

- [ ] **G4. Two clients writing the same session id simultaneously.**
  Race the laptop and the phone, both with session id
  `sess_race`. Expected: both turns land in memory under the same
  session, with monotonically-increasing turn_idx values (no
  duplicate idx). The brainstem's per-session counter is in-process
  and not lock-free across containers, so this is one of the soft
  spots Sprint 4 will need to harden.

- [ ] **G5. Brainstem restart mid-conversation.** Restart the
  brainstem container while a client has a session open. Expected:
  the client's next call works; the server-side turn counter for
  that session resets to 0 (documented behavior - see
  `docs/exposure_and_cortex_down.md`). Memory persists in Chroma; a
  cross-session query should still recover the pre-restart turns.

- [ ] **G6. Tailscale IP rotation.** Rare. If the 4070's Tailscale IP
  changes, run `scripts/setup/refresh-tailscale-bind.ps1` to refresh
  the bind. Expected: clients pointed at the new IP work; clients
  still pointed at the old IP get a connection error, not an auth
  error.

- [ ] **G7. Very large prompt.** Send a prompt at the 8K+ token mark.
  Expected: graceful behavior, not a brainstem crash. If the model
  cannot handle it, the failure is surfaced as a 502.

## Section H: Sign-off

- [ ] All sections A through F passed.
- [ ] Section G items either passed, were skipped intentionally, or
  generated a bug ticket.
- [ ] `pytest tests/integration/` was run from the 4070 host or a
  developer machine with the brainstem stack importable. Result
  recorded in the handoff.
- [ ] Live-smoke subset was run with the env vars set:

  ```
  NEXUS_LIVE_URL=${BRAINSTEM_URL} NEXUS_LIVE_TOKEN=${LAPTOP_TOKEN} \
    pytest tests/integration/test_live_smoke.py -v
  ```

  Result recorded in the handoff.
