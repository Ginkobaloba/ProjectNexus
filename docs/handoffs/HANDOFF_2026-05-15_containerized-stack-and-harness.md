# Handoff: 2026-05-15, containerized stack + Phase 0 metric harness

Supersedes `HANDOFF_2026-05-14_two-boxes-can-talk.md`. The fabric is now
running as a containerized stack with a live metric harness and dashboard.

## What is running and verified

**4090 (DREWSPC), Cortex inference:**

- `qwen-vllm` Docker container, vLLM 0.15.1, serving
  `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` on `0.0.0.0:8000`,
  `--enforce-eager`, `--gpu-memory-utilization 0.92`, restart policy
  `unless-stopped`. `GET /v1/models` and `POST /v1/chat/completions`
  both verified serving.
- Launch script: `scripts/setup/start-cortex-vllm.ps1`.

**4070 (BROOKFIELD_PC), the containerized fabric stack:**

- `brainstem_4070` container: FastAPI on `0.0.0.0:5001`. Cortex relay
  (`/generate`, `/cortex/health`), the Phase 0 metric harness,
  `/fabric/status`, and the `/dashboard` page.
- `nas_memory` container: FastAPI on `0.0.0.0:5002`, Chroma semantic
  store + JSONL episodic log, `data/nas` volume on the 4070 SSD.
- Both built via `docker compose -f docker/docker-compose.yml up -d --build`,
  `restart: unless-stopped`, on the `nexusnet` bridge network so the
  brainstem reaches NAS by compose DNS.
- The brainstem Docker build is fast now: `brainstem.Dockerfile` installs
  the CPU-only torch wheel before sentence-transformers (the multi-GB
  CUDA wheel was the 20-minute build killer), and the source COPY is last
  so code edits do not bust the dependency layers. Full build of both
  images is ~80 seconds.

**The round trip, verified end to end:**

- `POST http://localhost:5001/generate` on the 4070 returns text produced
  by the 4090's model, through the containers. Confirmed with a sentinel
  prompt and on both sides' logs.

## The metric harness and dashboard (Phase 0 Component G, minimal slice)

- `bench/probes.py`: monotonic-clock probes, append-only JSONL sink, the
  stable per-record schema from the experiment design doc section 2.2.
- `bench/stats.py`: shared p50/p95/p99 summaries.
- `bench/analyze.py`: offline analysis over the full JSONL log.
- `bench/latency_bench.py`: sequential closed-loop `/generate` load probe
  (stdlib only, runs from any node).
- The brainstem `/generate` path is instrumented. Every call is timed and
  decomposed into brainstem overhead vs the Cortex round trip, written to
  `/data/metrics/brainstem_metrics.jsonl` (the `data/metrics` volume).
- `/fabric/status` returns a live snapshot: both nodes, the 4070->4090
  link, NAS reachability, and the rolling latency stats. `/dashboard`
  serves a self-refreshing browser view of it (`/` points at it).

**First numbers (4 round trips, small prompts):** end-to-end p50 ~217 ms
/ p95 ~331 ms; the split shows brainstem overhead at p50 ~0.004 ms, i.e.
the orchestration cost is negligible and essentially all latency is the
Cortex round trip (LAN hop + 4090 generation). Generation throughput
~25 tok/s with `--enforce-eager`. These are Phase 0 rolling numbers, not
a Phase 1 characterization.

The metric is set: round-trip latency on `/generate`, decomposed, p50/p95/
p99 + tokens/s, persisted to JSONL. The formal Phase 1 budget (`L`) and
headroom (`K`) are deliberately NOT set yet; they need a real downstream
workload to anchor to and the design doc flags them for a cross-check.

## Environmental gotchas (these bit hard this session)

- **Docker Desktop needs an interactive session.** Mid-session Docker
  Desktop went down on both boxes at once (likely an update or reboot
  cycle). The 4090 was recoverable from its console session. The 4070
  could NOT be recovered remotely: `quser` showed no interactive session,
  and Docker Desktop's WSL2 backend will not start without one.
  `docker desktop start`, an interactive scheduled task, and
  `Start-Service com.docker.service` were all insufficient. The user had
  to log into the 4070. Recommended: set Docker Desktop to start on login
  on the 4070, or this recurs on every reboot.
- **Docker credential helper fails in non-interactive sessions on the
  4070.** `docker build`/`pull` over SSH fails with "A specified logon
  session does not exist". Workaround in use: `DOCKER_CONFIG` points at
  `~/nexus_docker_cfg` whose `config.json` is `{"credsStore":"","auths":{}}`,
  which disables the helper so anonymous pulls of public images work.
- **Processes started over SSH die when the session closes.** Use
  `Invoke-CimMethod Win32_Process Create` to launch anything that must
  outlive the SSH session (used for the container build worker, etc.).
- The 4070's SSH/LAN was intermittently dropping connections this session
  (timeouts, "connection abort"). Retries got through; worth watching.

## Repo state

Branch `foundation/consolidation`, both boxes and origin synced at
`512376d`, working trees clean. Commits since the prior handoff:

- `f1ab5ce` build(docker): CPU-only torch, full compose stack, metrics volume
- `7c6c36e` bench(harness): Phase 0 metric harness + live fabric dashboard
- `512376d` fix(brainstem): short timeout for Cortex health checks
- (`8cee0b3`, `b962f4c` earlier: Experiment 1 sprint plan, prior handoff)

## Next steps

1. Phase 0 Component D depth: NAS write-path probes and a committed
   `nodes/nas_memory/schema.md`, so `/embed` and `/stm/write` latency
   also lands in the harness.
2. The bidirectional callback channel: the 4090 model already has
   tool-calling enabled (`--enable-auto-tool-choice --tool-call-parser
   hermes`); the 4070 needs a tool endpoint the model can call back into.
3. Wire the 4070 orchestrator models (already staged in the HF cache:
   `Qwen3-Embedding-0.6B`, `Qwen3-4B-Instruct-2507`) into the brainstem.
4. Anchor the Phase 1 numbers (`L`, `K`, `T_offered`) to a real downstream
   workload, then run the canonical characterization sweep.
5. Set Docker Desktop to auto-start on the 4070 so a reboot does not take
   the fabric down.

## Reachability note

Both Jetson Nanos are now reachable after the user fixed a duplicate
hostname conflict: `192.168.1.221` (stable) and `192.168.1.209` (the
previously-flapping one). They are edge perception nodes for the later
Vector phase, not part of the current fabric milestone.
