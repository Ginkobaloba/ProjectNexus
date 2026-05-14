# bench/ - Phase 0 metric harness and load tooling for Project Nexus.
#
# probes.py  - probe helper + JSONL sink (the data layer)
# stats.py   - shared percentile/summary stats
# analyze.py - read a metrics JSONL and print per-stage stats
# latency_bench.py - fire N /generate requests and report the envelope
