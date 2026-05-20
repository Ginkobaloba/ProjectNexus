# bench/analyze.py
"""
Read a Phase 0 metrics JSONL file and print per-stage latency stats.

Usage:
    python -m bench.analyze [path-to-jsonl]

This is the offline counterpart to the live dashboard. The dashboard
reads a rolling in-process window; analyze.py reads the full persistent
log, so it is the source of truth for "what did the envelope look like
over the whole run".
"""
import json
import sys

from bench.stats import summarize

DEFAULT_PATH = "/data/metrics/brainstem_metrics.jsonl"


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # tolerate a torn last line
    return rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    try:
        rows = load(path)
    except FileNotFoundError:
        print(f"no metrics file at {path}")
        return 1
    if not rows:
        print(f"{path}: empty")
        return 0

    ok = [r for r in rows if r.get("ok")]
    fail = [r for r in rows if not r.get("ok")]
    runs = sorted({r.get("run_uuid", "?") for r in rows})
    builds = sorted({r.get("build_state", "?") for r in rows})

    print(f"metrics file : {path}")
    print(f"records      : {len(rows)} ({len(ok)} ok, {len(fail)} fail)")
    print(f"runs         : {', '.join(runs)}")
    print(f"build states : {', '.join(builds)}")
    print()

    fields = [
        ("total_ms", "end to end (ms)"),
        ("cortex_roundtrip_ms", "cortex round trip (ms)"),
        ("brainstem_overhead_ms", "brainstem overhead (ms)"),
        ("tokens_per_s", "throughput (tok/s)"),
    ]
    hdr = (f"{'metric':<26}{'count':>7}{'min':>10}{'p50':>10}"
           f"{'p95':>10}{'p99':>10}{'max':>10}")
    print(hdr)
    print("-" * len(hdr))
    for key, label in fields:
        vals = [
            r[key] for r in ok
            if isinstance(r.get(key), (int, float))
            and (key != "tokens_per_s" or r[key])
        ]
        s = summarize(vals)
        print(f"{label:<26}{s['count']:>7}{s['min']:>10.2f}{s['p50']:>10.2f}"
              f"{s['p95']:>10.2f}{s['p99']:>10.2f}{s['max']:>10.2f}")

    if fail:
        print()
        print(f"{len(fail)} failed call(s); most recent error:")
        print("  " + str(fail[-1].get("error")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
