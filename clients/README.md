# Nexus thin clients

Stage 0 Sprint 3a. The thin client is the "visible win" of Sprint 3: the
fabric, reachable from a device in your hand. Two clients live here, both
talking to the same public endpoint on the 4070 brainstem.

- `web/` is a single-page chat interface built phone-first. Open it in a
  mobile browser, type, get text back from the 4090 Cortex.
- `cli/` is a terminal client that does the same round trip from a shell,
  as a REPL or one-shot.

Both are deliberately a **separate artifact** from the brainstem service.
They never import or edit brainstem code. They speak only its public HTTP
contract: the legacy `POST /generate`, and, as of Sprint 5, the family hub
member API (`GET /family`, `POST /members/{id}/chat`,
`GET /members/{id}/inbox/{msg_id}`). That keeps the client free to evolve,
ship, and break without touching the running fabric.

## The contract these clients speak

The brainstem's `/generate` endpoint takes a JSON body:

```json
{ "prompt": "...", "system": "(optional)", "max_tokens": 512, "temperature": 0.7 }
```

and returns:

```json
{ "text": "...", "model": "...", "finish_reason": "stop", "usage": { ... }, "source": "cortex_4090" }
```

### Sprint 5: the family hub member API

The brainstem's Sprint 5 family hub adds a member-aware surface alongside
`/generate`, which keeps working unchanged as the hub's default member.

- `GET /family` (anonymous) - the household roster: `{members: [{id,
  display_name, presence, queue_depth, model: {source, quant,
  context_length}}]}`.
- `POST /members/{id}/chat` (Bearer auth, **no** `X-Session-Id` - member
  sessions are hub-minted per person+member on the server) - body
  `{prompt, system?, max_tokens?, temperature?}`. Three possible
  responses:
  - `200` - answered live: `{member_id, display_name, text, model,
    finish_reason, usage, session_id, turn_idx, memory_written}`.
  - `202` - the member is asleep or busy: `{queued, msg_id, member_id,
    presence, status_url}`. The message waits in their inbox.
  - `503 member_loading` - the member is waking up: structured body with
    `retry_after_seconds` and a `Retry-After` header, same shape as the
    older `cortex_unavailable`/`cortex_timeout` 503s (which can still
    pass through this endpoint too).
- `GET /members/{id}/inbox/{msg_id}` (Bearer auth, sender only) - status
  of a queued message: `{msg_id, member_id, status: "queued"|"answered",
  queued_at, result}`. `result.text` carries the reply once answered.

On every request both clients also send:

- `X-Session-Id` - a session id the client generates once and persists.
  This is the client's half of the session contract. The Sprint 2 memory
  work owns what the server does with it; the client just mints it,
  keeps it stable across runs, and sends it. Nothing here invents
  server-side session semantics.
- `Authorization: Bearer <token>` - **required as of Sprint 3b on
  `/generate`, `/embed`, and `/stm/write`.** Mint a token on the 4070
  with `docker compose exec brainstem python scripts/create_token.py
  --name <client>`, then paste it into the client's config (`auth_token`
  field), the `NEXUS_AUTH_TOKEN` env var, the CLI's `--token` flag, or
  the web client's settings panel. Without a token these endpoints
  return 401. Status endpoints (`/health`, `/cortex/health`,
  `/embedder/health`, `/fabric/status`, `/dashboard`) stay anonymous for
  monitoring. See `docs/auth_middleware.md` for the design.

## Configuration

`config.json` is the shared source of truth for both clients:

```json
{
  "targets": {
    "lan": "http://<REDACTED_LAN_IP>:5001",
    "tailscale": "http://<REDACTED_TAILSCALE_IP>:5001"
  },
  "default_target": "tailscale",
  "default_member": "vera",
  "auth_token": "",
  "generation": { "max_tokens": 512, "temperature": 0.7 }
}
```

Two named targets, same brainstem, different paths to it. The LAN address
works on the home network. The Tailscale address works from anywhere on
the tailnet, on or off the home network, which is why it is the default.
Either client can also be pointed at an explicit `--url`. `default_member`
(Sprint 5) is which family member the CLI's `--member` flag talks to when
you don't name one explicitly.

## CLI client

Standard library only, so it runs from any box, laptop, or Jetson with a
Python install and no `pip install` step.

```
cd clients/cli
python nexus_cli.py                          # interactive REPL, default target
python nexus_cli.py --target lan             # point at the LAN address
python nexus_cli.py --target tailscale       # point at the Tailscale address
python nexus_cli.py --url http://host:5001   # explicit override
python nexus_cli.py --prompt "one question"  # one-shot: print reply, exit
echo "piped question" | python nexus_cli.py  # one-shot from stdin
python nexus_cli.py --new-session            # start a fresh session id
```

The session id is persisted to `~/.nexus/cli_session_id` so a shell keeps
the same conversation thread across runs. In the REPL, `/new` starts a
fresh session, `/session` shows the current one, `/target` shows the
brainstem url, `/exit` quits. `python nexus_cli.py --help` lists every flag.

### Talking to a family member (Sprint 5)

```
python nexus_cli.py --family                       # list the roster: id, presence, queue depth, model
python nexus_cli.py --member vera --prompt "hi"     # one-shot chat with member "vera"
python nexus_cli.py --member --prompt "hi"          # same, using config's default_member
python nexus_cli.py --member vera                   # REPL in member mode
python nexus_cli.py --member vera --check-inbox <msg_id>  # resume a queued reply later
```

`--member` (with or without an id) switches the chat round trip from the
legacy `/generate` to `POST /members/{id}/chat`. Three things can happen:

- **Answered live (200)**: printed exactly like a `/generate` reply, with
  the member's name in the footer.
- **Queued (202)** - the member is asleep or busy: the CLI prints the
  `msg_id` and polls the returned `status_url` every `--poll-interval`
  seconds (default 5s) until it is answered or `--max-wait` (default
  300s) elapses. If it gives up, it prints the exact command to resume
  polling later with `--check-inbox`; the message is not lost, it is
  still sitting in the member's inbox.
- **Waking (503 `member_loading`)**: the CLI retries up to 3 times,
  honoring the server's `Retry-After` each time (capped at 60s), before
  giving up with a clear error. The older `cortex_unavailable`/
  `cortex_timeout` 503s still get the original Sprint 3c one-retry
  treatment on this path.

In the REPL, `/family` lists the roster, `/member <id>` switches to
chatting with that member, and `/legacy` switches back to `/generate`.
Member chat does not send `X-Session-Id`: the hub mints and persists a
session per (person, member) itself.

## Web client

The web client is `web/index.html`, a single self-contained file. The
catch: the brainstem does not send CORS headers, so a browser page loaded
from a different origin cannot `POST /generate` with the custom headers
this client needs. The browser blocks it at the preflight.

The fix that does **not** require touching the brainstem is to serve the
page and the API from the same origin. `web/serve.py` does exactly that:
it serves `index.html` and reverse-proxies a small allowlist of brainstem
endpoints (`/generate`, `/fabric/status`, `/cortex/health`, `/health`,
and, as of Sprint 5, `/family`, `/members/{id}/chat`,
`/members/{id}/inbox/{msg_id}`) to the configured 4070 address. The
browser only ever talks to `serve.py`, same origin, no CORS, brainstem
untouched.

```
cd clients/web
python serve.py                        # default target, port 8080
python serve.py --target lan           # front the 4070 LAN address
python serve.py --target tailscale     # front the 4070 Tailscale address
python serve.py --url http://host:5001 # explicit brainstem override
python serve.py --port 9000            # bind a different port
```

Run `serve.py` on any always-on box on the tailnet, then open
`http://<that-box>:8080/` in a phone browser. The proxy forwards
`X-Session-Id` and `Authorization` straight through, untouched: it owns
neither sessions nor auth, same as the rest of these clients.

`serve.py` is also standard library only.

In the page itself, the gear icon opens settings: the brainstem
connection (blank means "use the proxy", which is the recommended path),
an optional auth token, generation parameters, and the session id with a
"new session" button. The session id is persisted in `localStorage`, so a
phone keeps its conversation thread across reloads.

### Talking to a family member (Sprint 5)

The people icon in the header opens the family sheet, populated from
`GET /family`: each member's presence (green dot = awake, amber = busy or
waking, grey = asleep) and queue depth, plus a "Legacy /generate" row to
go back to the original endpoint. Tapping a member routes chat through
`POST /members/{id}/chat` instead; the header subtitle shows who you're
currently talking to. The chosen member is persisted in `localStorage`,
same as the session id, so a phone remembers it across reloads.

- **Answered live (200)**: rendered exactly like a `/generate` reply,
  with the member's name in the footer.
- **Queued (202)** - the member is asleep or busy: the page shows
  "*&lt;name&gt; is asleep -- message queued (msg_id). Waiting...*" and
  polls the inbox status URL at the interval set in Settings ("Queue
  poll interval", default 5s) until answered, or until "Queue max wait"
  (default 300s) elapses. If it gives up, a "Check again" button appears
  so you can resume polling without retyping the message.
- **Waking (503 `member_loading`)**: shown as a countdown ("*retrying in
  Ns... (attempt a/3)*") honoring the server's `Retry-After`, up to 3
  attempts, before surfacing a clear error. The older
  `cortex_unavailable`/`cortex_timeout` 503s still get the original
  Sprint 3c one-retry treatment on this path.

Member chat deliberately does not send `X-Session-Id`: the hub mints and
persists a session per (person, member) itself.

### Future: serving the page from the brainstem directly

The proxy exists because the brainstem has no CORS and the client may not
edit it. The cleaner long-term deployment is a one-line static mount on
the brainstem so it serves `index.html` itself, same origin by
construction, no proxy needed. The web client already supports this: it
makes same-origin relative requests by default, so the day the brainstem
serves the page, it just works. That change belongs to the brainstem
owner, not to this artifact, so it is noted here as a handoff rather than
done here.

## Done-criterion

Sprint 3a is done when the web client works from a phone browser and the
CLI client works from a terminal, both completing a round trip against
the brainstem and displaying the generated response. Verification notes
live in the commit that adds these files.
