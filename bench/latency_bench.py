# bench/latency_bench.py
"""
Phase 0 latency bench: fire N /generate requests at the brainstem and
report the round-trip envelope.

Usage:
    python -m bench.latency_bench [--url URL] [--n N] [--warmup W]
                                  [--max-tokens M] [--prompt TEXT]

This is a sequential, closed-loop probe (one request at a time). It
measures the single-stream latency envelope, not saturation throughput;
a concurrent emitter for the offered-rate sweeps is a later piece per the
experiment design doc. Uses only the standard library so it can run from
any node without installing dependencies.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from bench.stats import summarize


def call(url, prompt, max_tokens, timeout):
    body = json.dumps(
        {"prompt": prompt, "max_tokens": max_tokens, "temperature": 0.1}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        usage = payload.get("usage", {}) or {}
        return {
            "ok": True,
            "client_ms": (time.monotonic() - t0) * 1000.0,
            "completion_tokens": usage.get("completion_tokens", 0) or 0,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "client_ms": (time.monotonic() - t0) * 1000.0,
            "error": str(exc),
        }


def main():
    ap = argparse.ArgumentParser(description="Brainstem /generate latency bench")
    ap.add_argument("--url", default="http://localhost:5001/generate")
    ap.add_argument("--n", type=int, default=20, help="measured requests")
    ap.add_argument("--warmup", type=int, default=2, help="discarded warmup requests")
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--prompt", default="Name three primary colors in one short line.")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    print(f"target   : {args.url}")
    print(f"requests : {args.n} measured (+{args.warmup} warmup), "
          f"max_tokens={args.max_tokens}")
    print()

    for i in range(args.warmup):
        r = call(args.url, args.prompt, args.max_tokens, args.timeout)
        print(f"  warmup {i + 1}: {'ok' if r['ok'] else 'FAIL'}  "
              f"{r['client_ms']:.0f} ms")

    samples, fails = [], 0
    for i in range(args.n):
        r = call(args.url, args.prompt, args.max_tokens, args.timeout)
        if r["ok"]:
            samples.append(r)
        else:
            fails += 1
            print(f"  req {i + 1}: FAIL  {r.get('error')}")
    print()

    client_ms = [s["client_ms"] for s in samples]
    tokens = [s["completion_tokens"] for s in samples]
    tps = [
        s["completion_tokens"] / (s["client_ms"] / 1000.0)
        for s in samples
        if s["client_ms"] > 0 and s["completion_tokens"]
    ]
    cs = summarize(client_ms)
    ts = summarize(tps)

    print(f"ok / fail        : {len(samples)} / {fails}")
    print(f"client latency ms: p50 {cs['p50']:.0f}  p95 {cs['p95']:.0f}  "
          f"p99 {cs['p99']:.0f}  max {cs['max']:.0f}")
    print(f"throughput tok/s : p50 {ts['p50']:.1f}  p95 {ts['p95']:.1f}  "
          f"max {ts['max']:.1f}")
    print(f"tokens generated : {sum(tokens)} over {len(samples)} calls")
    print()
    print("Server-side decomposition (brainstem overhead vs cortex round trip)")
    print("is in the brainstem metrics log; run  python -m bench.analyze  for it.")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
