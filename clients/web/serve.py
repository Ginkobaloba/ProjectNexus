#!/usr/bin/env python3
# clients/web/serve.py
"""
Static server + same-origin reverse proxy for the Nexus web client.

Why this exists:
    The 4070 brainstem does not send CORS headers. A browser page loaded
    from a different origin therefore cannot POST to /generate with the
    custom headers this client needs (X-Session-Id, and later an auth
    token) - the browser blocks it at the preflight. The clean fix that
    does NOT require touching the brainstem is to serve the page and the
    API from the same origin. That is this script's whole job:

      - serve clients/web/index.html
      - reverse-proxy a small allowlist of brainstem endpoints to the
        configured 4070 address (LAN or Tailscale)

    The browser only ever talks to this server. Same origin, no CORS, and
    the brainstem stays untouched. When some later deployment serves the
    page from the brainstem directly, this proxy is simply not needed and
    the web client's same-origin relative requests still work.

Scope boundaries (see the Sprint 3a brief):
    - Does not touch brainstem internals. It is an outside HTTP client.
    - Does not add, validate, or strip auth. It forwards the Authorization
      header through untouched if the browser sent one. Auth is Sprint 3b.
    - Does not invent session semantics. It forwards X-Session-Id through
      untouched. The client mints it, the Sprint 2 memory work consumes it.

Stdlib only, on purpose - drop it on any box with Python and run it.

Usage:
    python serve.py                        # default target, port 8080
    python serve.py --target lan           # front the 4070 LAN address
    python serve.py --target tailscale     # front the 4070 Tailscale address
    python serve.py --url http://host:5001 # explicit brainstem override
    python serve.py --port 9000            # bind a different port

Then open http://<this-machine>:8080/ in a browser. From a phone, use the
LAN or Tailscale address of the machine running this script.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

# index.html lives next to this script; config.json one level up in clients/.
HERE = Path(__file__).resolve().parent
INDEX_PATH = HERE / "index.html"
DEFAULT_CONFIG_PATH = HERE.parent / "config.json"

FALLBACK_CONFIG: Dict[str, Any] = {
    "targets": {
        "lan": "http://192.168.1.251:5001",
        "tailscale": "http://100.89.210.52:5001",
    },
    "default_target": "tailscale",
}

# Only these brainstem paths are proxied. An allowlist keeps this from
# being an open relay: it forwards the client round trip and the status
# polling, nothing else.
PROXY_GET = {"/fabric/status", "/cortex/health", "/health"}
PROXY_POST = {"/generate"}

# /generate waits on the 4090 model, which is deliberately slow under
# enforce-eager. Status checks should stay snappy.
GENERATE_TIMEOUT = 180.0
STATUS_TIMEOUT = 10.0

# Request headers worth forwarding upstream. Everything else (Host,
# Connection, hop-by-hop headers) is dropped and rebuilt by urllib.
FORWARD_REQUEST_HEADERS = ("content-type", "authorization", "x-session-id")


def load_config(path: Path) -> Dict[str, Any]:
    """Load the shared client config, falling back to baked-in defaults."""
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] could not read {path} ({exc}); using built-in defaults",
              file=sys.stderr)
        return dict(FALLBACK_CONFIG)
    merged = dict(FALLBACK_CONFIG)
    merged.update(cfg)
    return merged


def resolve_upstream(args: argparse.Namespace, cfg: Dict[str, Any]) -> tuple:
    """Decide the brainstem this proxy fronts. Returns (target_name, base_url)."""
    if args.url:
        return ("custom", args.url.rstrip("/"))
    targets = cfg.get("targets", {})
    target_name = args.target or cfg.get("default_target", "tailscale")
    if target_name not in targets:
        raise SystemExit(
            f"[error] unknown target '{target_name}'. "
            f"known targets: {', '.join(sorted(targets)) or '(none)'}"
        )
    return (target_name, targets[target_name].rstrip("/"))


def make_handler(upstream: str, target_name: str):
    """Build the request handler class, closed over the chosen upstream."""

    class NexusClientHandler(BaseHTTPRequestHandler):
        # Quieter, single-line logging.
        def log_message(self, fmt: str, *fmt_args: Any) -> None:
            sys.stderr.write(
                "  %s - %s\n" % (self.address_string(), fmt % fmt_args)
            )

        # -- routing -------------------------------------------------------
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path == "/client/info":
                self._serve_client_info()
            elif path in PROXY_GET:
                self._proxy(path, method="GET", timeout=STATUS_TIMEOUT)
            else:
                self._send_json(404, {"detail": f"not found: {path}"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in PROXY_POST:
                self._proxy(path, method="POST", timeout=GENERATE_TIMEOUT)
            else:
                self._send_json(404, {"detail": f"not found: {path}"})

        # -- static --------------------------------------------------------
        def _serve_index(self) -> None:
            try:
                body = INDEX_PATH.read_bytes()
            except OSError as exc:
                self._send_json(500, {"detail": f"index.html unreadable: {exc}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _serve_client_info(self) -> None:
            # Lets the web UI display which brainstem it is effectively
            # talking to. Purely informational.
            self._send_json(200, {"target": target_name, "upstream": upstream})

        # -- proxy ---------------------------------------------------------
        def _proxy(self, path: str, method: str, timeout: float) -> None:
            url = upstream + path

            body: Optional[bytes] = None
            if method == "POST":
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""

            # Forward only the headers that matter. X-Session-Id and
            # Authorization pass straight through, untouched - this proxy
            # owns neither sessions nor auth.
            fwd_headers: Dict[str, str] = {}
            for name in FORWARD_REQUEST_HEADERS:
                value = self.headers.get(name)
                if value is not None:
                    fwd_headers[name] = value

            req = urllib.request.Request(
                url, data=body, headers=fwd_headers, method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    self._relay_response(resp.status, resp.headers, resp.read())
            except urllib.error.HTTPError as exc:
                # Brainstem answered with an error (e.g. 502 when the
                # Cortex round trip fails). Relay it faithfully so the web
                # client can show the real detail.
                self._relay_response(exc.code, exc.headers, exc.read())
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                # Brainstem unreachable from this proxy machine.
                reason = getattr(exc, "reason", exc)
                self._send_json(502, {
                    "detail": f"proxy could not reach brainstem at {url}: {reason}"
                })

        def _relay_response(self, status: int, headers: Any, body: bytes) -> None:
            self.send_response(status)
            content_type = "application/json"
            if headers is not None:
                content_type = headers.get("Content-Type", content_type)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        # -- helpers -------------------------------------------------------
        def _send_json(self, status: int, obj: Dict[str, Any]) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return NexusClientHandler


def local_addresses() -> list:
    """Best-effort primary LAN address, for the startup hint.

    Uses only the "which interface would reach the internet" UDP-socket
    trick, which is instant and needs no DNS. A hostname getaddrinfo lookup
    was deliberately avoided here: on some hosts it blocks for seconds and
    this is just a convenience line in the banner.
    """
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in addrs if a != "127.0.0.1")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Static server + same-origin reverse proxy for the Nexus web client.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                    help="path to the shared clients config.json")
    ap.add_argument("--target", choices=["lan", "tailscale"], default=None,
                    help="named brainstem target (default: config's default_target)")
    ap.add_argument("--url", default=None,
                    help="explicit brainstem base url, overrides --target")
    ap.add_argument("--host", default="0.0.0.0",
                    help="address to bind (0.0.0.0 lets a phone on the network reach it)")
    ap.add_argument("--port", type=int, default=8080, help="port to bind")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = load_config(args.config)
    target_name, upstream = resolve_upstream(args, cfg)

    if not INDEX_PATH.exists():
        print(f"[error] index.html not found at {INDEX_PATH}", file=sys.stderr)
        return 2

    handler = make_handler(upstream, target_name)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print("Nexus web client server")
    print(f"  serving      : {INDEX_PATH}")
    print(f"  brainstem    : {target_name}  ->  {upstream}")
    print(f"  bound to     : {args.host}:{args.port}")
    print(f"  open locally : http://localhost:{args.port}/")
    hints = local_addresses()
    if hints:
        print("  from a phone : " + ", ".join(
            f"http://{a}:{args.port}/" for a in hints))
    print("  Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
