# Sprint 5 bench pre-registration — member #1 baseline (Card 7)

**Date registered:** 2026-07-25 (before any llama.cpp run on the 4090)
**Discipline:** same as Sprint 3d — win conditions declared here, before
the first measured run; bootstrap CIs on latency stats; no retroactive
goalpost moves. This file is the registration; results land in a
separate results doc that links back here.

## What is being measured

The V2 runtime swap: **llama.cpp `llama-server`, Qwen3-30B-A3B GGUF
Q4_K_M** (member #1 "vera", `offload_policy: vram_then_ram`) versus the
Sprint 3d baseline (**vLLM, Qwen3-30B-A3B-AWQ**) on the same 4090 host.

- **Prompt set:** the Sprint 3d bench prompt set, unchanged, same order.
- **Path:** through the hub (`POST /members/vera/chat`), so retrieval,
  scope filtering, and write-on-turn costs are included — this is the
  number Drew actually experiences, not a bare-runtime number.
- **Metrics:** `tokens_per_s`, `total_ms` p50/p95, `cortex_roundtrip_ms`
  p50/p95, plus the new `stage_copy_ms` and `load_ms` for the
  cold-start story (no vLLM comparison for those — vLLM never staged
  from cold tiers).

## Win conditions (declared now)

1. **Quality guard:** the Sprint 3d eval gauntlet regresses by no more
   than the guard tolerance already defined there. A faster runtime
   that answers worse does not ship.
2. **Throughput:** llama.cpp Q4_K_M reaches ≥ 70% of the vLLM AWQ
   `tokens_per_s` median. The swap is motivated by the family
   architecture (offload, GGUF portability, one runtime for every
   member), not raw speed — but below 70% we stop and investigate
   before accepting.
3. **Cold start:** HDD → serving (stage_copy + load) under 5 minutes,
   measured by the Card 4 metrics. This is the "member wakes up"
   budget the inbox UX is designed around.

## What may be tuned before the measured run

Nothing. First measured run is the baseline, as-is from the registry
defaults. `offload_policy` and sampling tuning happen only *after* the
baseline is frozen, each as its own recorded run — that ordering is
the entire point of pre-registering.

## Report card seed

The frozen baseline becomes member #1's first report-card entry
(V2 doc Section 10): the reference every future adapter, quant change,
or self-training experiment must beat on the same gauntlet.
