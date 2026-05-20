#!/usr/bin/env python3
# clients/cli/nexus_cli.py
"""
Nexus thin client, CLI edition.

A terminal client for the 4070 brainstem's /generate endpoint. It does the
same round trip the web client does: send a prompt, get back text generated
by the 4090 Cortex, print it.

Why this exists (cognitive-system framing):
    The brainstem is the fabric's front door. Stage 0 Sprint 3 is about
    making that door reachable from real client devices, not just a bench
    script. This is the keyboard-and-terminal door. The phone-browser door
    is clients/web/.

Scope boundaries (deliberate, see the Sprint 3a brief):
    - This client never touches brainstem internals. It only speaks the
      public HTTP contract.
    - Auth (Sprint 3b): the brainstem requires a bearer token on
      /generate. This client attaches one from --token, NEXUS_AUTH_TOKEN,
      or the shared config. No auth logic lives here, just the header.
    - Cortex-down (Sprint 3c): on the structured 503 cortex-unavailable
      body, the CLI does one informed retry honoring `Retry-After` and
      prints a friendly "retrying in Ns" line to stderr. A second 503
      is surfaced as a human-readable error and the REPL stays open.
    - Server-side session semantics are owned by the Sprint 2 memory agent.
      This client only does its half of the contract: generate a session
      id, persist it, and send it as the X-Session-Id header on every
      request. It does not assume what the server does with it.

Stdlib only, on purpose. The bench tooling in this repo follows the same
rule so it can run from any node without a pip install. This client should
too: drop it on a laptop, a box, a Jetson, and it just runs.

Usage:
    python nexus_cli.py                          # interactive REPL, default target
    python nexus_cli.py --target lan             # point at the LAN address
    python nexus_cli.py --target tailscale       # point at the Tailscale address
    python nexus_cli.py --url http://host:5001   # explicit override
    python nexus_cli.py --prompt "one question"  # one-shot, print, exit
    echo "piped question" | python nexus_cli.py  # one-shot from stdin
    python nexus_cli.py --new-session            # start a fresh session id

Run  python nexus_cli.py --help  for the full flag list.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# --------------------------------------------------------------------------
# Config + session persistence
# --------------------------------------------------------------------------

# clients/config.json is the shared source of truth for both clients: the
# named targets (lan / tailscale), the default, and the (currently empty)
# auth token. We resolve it relative to this file so the client works from
# any working directory.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

# The session id lives outside the repo, in the user's home dir, so it
# survives across runs and is never accidentally committed. Persisting it
# is the client's half of the session contract with the Sprint 2 memory
# work: a stable id means turns from the same user land in the same
# server-side session.
SESSION_DIR = Path.home() / ".nexus"
SESSION_FILE = SESSION_DIR / "cli_session_id"

FALLBACK_CONFIG: Dict[str, Any] = {
    "targets": {
        "lan": "http://<REDACTED_LAN_IP>:5001",
        "tailscale": "http://<REDACTED_TAILSCALE_IP>:5001",
    },
    "default_target": "tailscale",
    "auth_token": "",
    "generation": {"max_tokens": 512, "temperature": 0.7},
}


def load_config(path: Path) -> Dict[str, Any]:
    """Load the shared client config, falling back to baked-in defaults.

    A missing or unreadable config file is not fatal: the client still has
    to be usable from a fresh checkout, so we keep working defaults inline.
    """
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] could not read {path} ({exc}); using built-in defaults",
              file=sys.stderr)
        return dict(FALLBACK_CONFIG)
    # Shallow-merge over the fallback so a partial config file still works.
    merged = dict(FALLBACK_CONFIG)
    merged.update(cfg)
    return merged


def load_session_id(force_new: bool = False) -> str:
    """Return a stable session id, generating and persisting one if needed.

    force_new wipes the stored id and mints a fresh one, which is how a user
    deliberately starts a clean conversation.
    """
    if not force_new and SESSION_FILE.exists():
        existing = SESSION_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    new_id = str(uuid.uuid4())
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(new_id, encoding="utf-8")
    except OSError as exc:
        # If we cannot persist, we still return a usable id for this run;
        # it just will not survive a restart. Better than crashing.
        print(f"[warn] could not persist session id ({exc}); "
              f"using an ephemeral one for this run", file=sys.stderr)
    return new_id


# --------------------------------------------------------------------------
# The round trip
# --------------------------------------------------------------------------


class BrainstemError(RuntimeError):
    """Raised when the brainstem call fails in a way worth showing the user."""


class CortexDownError(BrainstemError):
    """Sprint 3c: brainstem returned the structured 503 cortex-down body.

    Carries `retry_after_seconds` and the `error` code so the caller can
    do one informed retry honoring the contract instead of forcing the
    user to re-send.
    """

    def __init__(self, message: str, retry_after_seconds: int, error_code: str):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.error_code = error_code


def resolve_base_url(args: argparse.Namespace, cfg: Dict[str, Any]) -> str:
    """Decide which brainstem URL to hit.

    Precedence, most specific first: an explicit --url, then a named
    --target, then the config's default_target.
    """
    if args.url:
        return args.url.rstrip("/")
    targets = cfg.get("targets", {})
    target_name = args.target or cfg.get("default_target", "tailscale")
    if target_name not in targets:
        raise BrainstemError(
            f"unknown target '{target_name}'. "
            f"known targets: {', '.join(sorted(targets)) or '(none)'}"
        )
    return targets[target_name].rstrip("/")


def resolve_token(args: argparse.Namespace, cfg: Dict[str, Any]) -> str:
    """Decide the auth token. Required as of Sprint 3b for /generate.

    Precedence: --token, then the NEXUS_AUTH_TOKEN env var, then the config.
    A missing token will not crash the client; it just means the brainstem
    will return 401. We surface that on the round trip instead of trying to
    guess locally.
    """
    if args.token is not None:
        return args.token
    env_token = os.environ.get("NEXUS_AUTH_TOKEN")
    if env_token is not None:
        return env_token
    return cfg.get("auth_token", "") or ""


def build_headers(session_id: str, token: str) -> Dict[str, str]:
    """Assemble the request headers.

    X-Session-Id goes on every request, always. That is the simple, explicit
    session contract the Sprint 2 agent made the server honor.

    Authorization is only attached when there is a non-empty token. The
    brainstem requires it on /generate as of Sprint 3b, so an empty token
    will produce a 401 from the server, which we surface to the user.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Session-Id": session_id,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def call_generate(
    base_url: str,
    prompt: str,
    headers: Dict[str, str],
    system: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> Dict[str, Any]:
    """Do one /generate round trip and return a normalized result dict.

    The result carries the generated text, the model id, token usage, the
    finish reason, and the client-measured latency. Raises BrainstemError
    with a human-readable message on any failure. Sprint 3c: a 503 from
    the brainstem's cortex-down contract raises CortexDownError, a
    BrainstemError subclass that carries the retry_after value.
    """
    url = f"{base_url}/generate"
    body: Dict[str, Any] = {
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        body["system"] = system

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A 401 here means we have no token or the wrong one. A 503
        # (Sprint 3c) is the cortex-down contract: structured body with
        # `error`, `retry_after_seconds`, and a human `message` we
        # surface verbatim. A 502 is anything else downstream.
        body_dict = _extract_cortex_down_body(exc)
        detail = (
            body_dict.get("message")
            or body_dict.get("detail")
            or _readable_reason(exc)
        )
        if exc.code == 401:
            raise BrainstemError(
                f"brainstem rejected the request (401 {detail}). "
                f"Set --token, NEXUS_AUTH_TOKEN, or auth_token in config.json. "
                f"Mint one on the 4070 with "
                f"`docker compose exec brainstem python scripts/create_token.py --name <client>`."
            ) from exc
        if exc.code == 503:
            retry_after = (
                body_dict.get("retry_after_seconds")
                or _retry_after_header_seconds(exc)
                or 5
            )
            raise CortexDownError(
                message=str(detail),
                retry_after_seconds=int(retry_after),
                error_code=str(body_dict.get("error") or "cortex_unavailable"),
            ) from exc
        if exc.code == 502:
            raise BrainstemError(
                f"brainstem reached, but a downstream call failed (502): {detail}"
            ) from exc
        raise BrainstemError(f"brainstem returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BrainstemError(
            f"could not reach brainstem at {url} ({exc.reason}). "
            f"check the target address and that the 4070 stack is up."
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise BrainstemError(f"request to {url} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BrainstemError(f"brainstem returned non-JSON from {url}: {exc}") from exc

    client_ms = (time.monotonic() - t0) * 1000.0
    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens", 0) or 0
    tokens_per_s = (
        completion_tokens / (client_ms / 1000.0)
        if client_ms > 0 and completion_tokens
        else 0.0
    )
    return {
        "text": payload.get("text", ""),
        "model": payload.get("model", "unknown"),
        "finish_reason": payload.get("finish_reason"),
        "completion_tokens": completion_tokens,
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "client_ms": client_ms,
        "tokens_per_s": tokens_per_s,
    }


def _readable_reason(exc: urllib.error.HTTPError) -> str:
    """Cheap fallback when we have no parseable body to lean on."""
    try:
        return exc.reason or f"HTTP {exc.code}"
    except AttributeError:
        return f"HTTP {exc.code}"


def _extract_cortex_down_body(exc: urllib.error.HTTPError) -> Dict[str, Any]:
    """Parse the Sprint 3c 503 body (or any other JSON error body).

    HTTPError.read() consumes the underlying stream, so we read once and
    keep the parsed dict. Returns an empty dict on any surprise so callers
    can fall back to the Retry-After header for the timing and the
    exception's reason for the message.
    """
    try:
        raw = exc.read().decode("utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {}


def _retry_after_header_seconds(exc: urllib.error.HTTPError) -> Optional[int]:
    """Read the Retry-After header from an HTTPError. RFC 7231 allows a
    seconds-integer or an HTTP-date; we only care about the integer
    form, since the brainstem only ever emits that."""
    try:
        value = exc.headers.get("Retry-After")  # type: ignore[union-attr]
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------


def format_footer(result: Dict[str, Any]) -> str:
    """One-line round-trip summary: model, latency, tokens, throughput."""
    return (
        f"  [model {result['model']}  "
        f"| {result['client_ms']:.0f} ms round trip  "
        f"| {result['completion_tokens']} tokens  "
        f"| {result['tokens_per_s']:.1f} tok/s  "
        f"| finish: {result['finish_reason']}]"
    )


def _call_with_cortex_down_retry(
    base_url: str,
    prompt: str,
    headers: Dict[str, str],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Run /generate with one informed retry on the Sprint 3c 503.

    A CortexDownError on the first attempt prints a friendly waiting
    message to stderr and sleeps for `retry_after_seconds` (capped) before
    the second attempt. If the second attempt also fails we let the
    exception propagate so the caller renders the final state.
    """
    try:
        return call_generate(
            base_url, prompt, headers, args.system,
            args.max_tokens, args.temperature, args.timeout,
        )
    except CortexDownError as exc:
        wait = max(1, min(int(exc.retry_after_seconds or 5), 30))
        print(
            f"[cortex down] {exc} retrying in {wait}s...",
            file=sys.stderr,
        )
        time.sleep(wait)
        return call_generate(
            base_url, prompt, headers, args.system,
            args.max_tokens, args.temperature, args.timeout,
        )


def run_once(
    base_url: str,
    prompt: str,
    headers: Dict[str, str],
    args: argparse.Namespace,
) -> int:
    """One-shot mode: send a single prompt, print the response, return exit code."""
    try:
        result = _call_with_cortex_down_retry(base_url, prompt, headers, args)
    except CortexDownError as exc:
        print(
            f"[error] cortex still unavailable after one retry: {exc}",
            file=sys.stderr,
        )
        return 1
    except BrainstemError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(result["text"])
    if not args.quiet:
        print(format_footer(result), file=sys.stderr)
    return 0


def run_repl(
    base_url: str,
    headers: Dict[str, str],
    session_id: str,
    args: argparse.Namespace,
) -> int:
    """Interactive mode: a small REPL over the same round trip.

    Slash commands keep the session controls in reach without leaving the
    prompt: /new starts a fresh session id, /session prints the current one,
    /help lists commands, /exit leaves.
    """
    print(f"Nexus CLI client  ->  {base_url}")
    print(f"session: {session_id}")
    print("type a prompt and press enter. /help for commands, /exit to quit.\n")

    current_headers = headers
    while True:
        try:
            line = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/help":
            print("  /new      start a fresh session id")
            print("  /session  show the current session id")
            print("  /target   show the brainstem url in use")
            print("  /exit     quit\n")
            continue
        if line == "/session":
            print(f"  session: {current_headers['X-Session-Id']}\n")
            continue
        if line == "/target":
            print(f"  target: {base_url}\n")
            continue
        if line == "/new":
            fresh = load_session_id(force_new=True)
            current_headers = build_headers(fresh, current_headers.get(
                "Authorization", "").removeprefix("Bearer ").strip())
            print(f"  new session: {fresh}\n")
            continue

        try:
            result = _call_with_cortex_down_retry(
                base_url, line, current_headers, args,
            )
        except CortexDownError as exc:
            print(
                f"[error] cortex still unavailable after one retry: {exc}\n",
                file=sys.stderr,
            )
            continue
        except BrainstemError as exc:
            print(f"[error] {exc}\n", file=sys.stderr)
            continue

        print(f"nexus > {result['text']}")
        if not args.quiet:
            print(format_footer(result))
        print()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Nexus thin client (CLI) for the 4070 brainstem /generate endpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH,
        help="path to the shared clients config.json",
    )
    ap.add_argument(
        "--target", choices=["lan", "tailscale"], default=None,
        help="named brainstem target from the config (default: config's default_target)",
    )
    ap.add_argument(
        "--url", default=None,
        help="explicit brainstem base url, overrides --target",
    )
    ap.add_argument(
        "--token", default=None,
        help="auth token (optional; Sprint 3b). also reads NEXUS_AUTH_TOKEN env var",
    )
    ap.add_argument(
        "--session-id", default=None,
        help="override the persisted session id for this run",
    )
    ap.add_argument(
        "--new-session", action="store_true",
        help="mint and persist a fresh session id before starting",
    )
    ap.add_argument("--system", default=None, help="optional system prompt")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="max tokens to generate (default: config value)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="sampling temperature (default: config value)")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="per-request timeout in seconds")
    ap.add_argument("--prompt", default=None,
                    help="one-shot mode: send this prompt, print the reply, exit")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress the round-trip metadata footer")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = load_config(args.config)

    # Fill generation defaults from config when the flags were not given.
    gen_defaults = cfg.get("generation", {})
    if args.max_tokens is None:
        args.max_tokens = int(gen_defaults.get("max_tokens", 512))
    if args.temperature is None:
        args.temperature = float(gen_defaults.get("temperature", 0.7))

    try:
        base_url = resolve_base_url(args, cfg)
    except BrainstemError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    token = resolve_token(args, cfg)

    # Session id precedence: explicit --session-id wins; otherwise the
    # persisted one (optionally regenerated via --new-session).
    if args.session_id:
        session_id = args.session_id
    else:
        session_id = load_session_id(force_new=args.new_session)

    headers = build_headers(session_id, token)

    # One-shot if --prompt was given, or if something is piped on stdin.
    piped = not sys.stdin.isatty()
    if args.prompt is not None:
        return run_once(base_url, args.prompt, headers, args)
    if piped:
        piped_prompt = sys.stdin.read().strip()
        if not piped_prompt:
            print("[error] empty prompt on stdin", file=sys.stderr)
            return 2
        return run_once(base_url, piped_prompt, headers, args)

    return run_repl(base_url, headers, session_id, args)


if __name__ == "__main__":
    sys.exit(main())
