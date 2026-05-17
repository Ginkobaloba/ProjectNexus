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
contract: `POST /generate`. That keeps the client free to evolve, ship,
and break without touching the running fabric.

## The contract these clients speak

The brainstem's `/generate` endpoint takes a JSON body:

```json
{ "prompt": "...", "system": "(optional)", "max_tokens": 512, "temperature": 0.7 }
```

and returns:

```json
{ "text": "...", "model": "...", "finish_reason": "stop", "usage": { ... }, "source": "cortex_4090" }
```

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
  "auth_token": "",
  "generation": { "max_tokens": 512, "temperature": 0.7 }
}
```

Two named targets, same brainstem, different paths to it. The LAN address
works on the home network. The Tailscale address works from anywhere on
the tailnet, on or off the home network, which is why it is the default.
Either client can also be pointed at an explicit `--url`.

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

## Web client

The web client is `web/index.html`, a single self-contained file. The
catch: the brainstem does not send CORS headers, so a browser page loaded
from a different origin cannot `POST /generate` with the custom headers
this client needs. The browser blocks it at the preflight.

The fix that does **not** require touching the brainstem is to serve the
page and the API from the same origin. `web/serve.py` does exactly that:
it serves `index.html` and reverse-proxies a small allowlist of brainstem
endpoints (`/generate`, `/fabric/status`, `/cortex/health`, `/health`) to
the configured 4070 address. The browser only ever talks to `serve.py`,
same origin, no CORS, brainstem untouched.

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
