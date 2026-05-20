# Handoff: Stage transition (2026-05-15)

This is the transition handoff. It ties together where Nexus stands, what is planned, and the open decisions, so the next session walks in with a complete runway. The detailed plans live in their own docs, linked below; this doc is the index and the current-state snapshot.

## What just happened

Stage 0 Sprint 1 is complete. A build task established the round trip (the 4070 brainstem relays to the 4090 vLLM and returns generated text), built the Phase 0 metric harness, built a self-refreshing dashboard, fixed the slow Docker build, and brought up the full containerized stack (brainstem plus the NAS memory service, both containers, both auto-restart). All verified end to end.

Real finding already in hand: end-to-end latency is p50 around 217 ms, but the decomposition shows brainstem orchestration overhead at roughly 0.004 ms, microseconds. The orchestration layer is a near-zero-cost relay. Essentially all latency is the Cortex inference round trip. That is a genuine Phase 0 result. Caveat: it was measured on the stub path with no memory retrieval in the loop, so it is the starting hypothesis for Stage 1 characterization, not a settled fact.

## The honest sequencing

Stage 0 is NOT complete. Sprint 1 is done. Sprints 2 through 5 are still open: persistent memory wired into the flow, multi-node client access, the bidirectional callback, and the Phase 0 close (soak test, decision record, reproducibility manifest, release tag). These are hard dependencies for Stage 1.

The next session begins by finishing Stage 0. Stage 1 does not start until Stage 0's release tag exists.

## Where the plans live

- `docs/experiments/experiment-1-pipeline-characterization.md` is the Experiment 1 design doc (Phase 0 and Phase 1 framing, hypothesis, IVs and DVs, gating).
- `docs/experiments/experiment-1-sprint-plan.md` is the Stage 0 completion plan: Sprints 2 through 5 with done-criteria and locked decisions.
- `docs/experiments/experiment-1-stage1-roadmap.md` is the Stage 1 roadmap: the 6-month, five-sprint-group plan produced by two-Opus triangulation, execution-ready.
- `docs/handoffs/HANDOFF_2026-05-15_containerized-stack-and-harness.md` is the build task's own handoff, with the deepest detail on what is running and the immediate Stage 0 next steps.

## Open decisions awaiting the builder

From the cleanup audit:
- Branch merge. `foundation/consolidation` is 21 commits ahead of `main`, 0 behind, a clean fast-forward. Ripe to merge to `main` whenever. Builder's call.
- Plaintext secrets on disk. Three credential files sit in the working folder in plaintext. All are gitignored and untracked, nothing leaked to git. `SECRETS.md` recommends rotation. Worth doing.

From the Stage 1 roadmap:
- The eval workload for Group A. Recommendation: a portfolio-legible general eval for the headline, plus a multi-session memory-dependent domain suite as the real thesis instrument.
- How smart Thalamus is. Recommendation: start as a small fast classifier-style router, measure 4070 headroom before considering a heavier one.
- The Group C edge-perception fallback. Recommendation: approve the reduced-scope fallback now and pre-commit the trigger date so it is automatic.
- 4070 resource contention. Recommendation: profile the 4070 under combined load during Group A so contention is a known budget, not a later surprise.

## Hardware and access reference

Two Windows Pro boxes, one LAN (192.168.1.0/24), both on Tailscale.

- 4090 box, hostname DREWSPC, LAN 192.168.1.140, Tailscale 100.78.100.97. Runs Cortex: the qwen-vllm container serving Qwen3-30B-A3B AWQ on port 8000, vLLM with enforce-eager, auto-restart. Docker Desktop AutoStart now enabled.
- 4070 box, hostname BROOKFIELD_PC, LAN 192.168.1.251, Tailscale 100.89.210.52. Runs the compose stack: brainstem on port 5001 (Cortex relay, metric harness, dashboard), nas_memory on port 5002 (Chroma plus episodic log). Docker Desktop AutoStart already enabled. Note: Docker Desktop's WSL2 backend needs an interactive login session to start; a reboot with nobody logged in leaves Docker down. Fix is a login (the builder, his mother who is borrowing the box, or auto-login).
- Dashboard: reachable at port 5001 path /dashboard on the 4070, via the LAN address on the home network or the Tailscale address from anywhere.

Jetson Nanos (edge perception, out of MVP scope, in scope for Stage 1 Group C):
- Link: 4GB, MAC 48:B0:2D:3D:32:F8, at 192.168.1.221. SSH key access from the 4090 established.
- sync: MAC 00:04:4B:E6:10:F7, at 192.168.1.209. SSH key access established. Previously flapping due to a duplicate-hostname conflict, resolved by the rename, stable since.
- Two more Nanos exist: one likely dead, one with an oem-config first-boot hang that needs the USB device-mode serial fix or a reflash.

SSH from the 4090: use Git for Windows ssh (the ssh.exe under Program Files Git), not the native Windows ssh.exe, which fails silently in the automation context. The SSH config defines aliases nexus-4070, Link, and sync, each pointing at its host with the correct key. Two ed25519 keypairs live in the 4090 user's .ssh directory, one for the 4070 and one shared by the Jetsons, with both private keys locked to owner-only ACLs.

## Repo state

`github.com/Ginkobaloba/ProjectNexus`, branch `foundation/consolidation`, both boxes and origin synced and clean. Pre-commit hooks active (secrets scan, large files, end-of-file-fixer, trailing whitespace); they auto-fix and may abort the first commit attempt, budget a re-stage and retry. The secrets scan (gitleaks) is sensitive to high-entropy tokens, so avoid putting key filenames or token-like strings verbatim in tracked docs. Stale `.git` lock files appear occasionally from Windows git maintenance; safe to remove when no git process is running.

## Immediate next step

Start Stage 0 Sprint 2: persistent memory. Chroma plus Embedder, write-on-turn and retrieve-before-generate in the brainstem, extend the metric harness with embedding and retrieval probes. The NAS memory service is already containerized and healthy, so the substrate is in place; the work is wiring the write and retrieve paths into the request flow. See `experiment-1-sprint-plan.md` for the full Sprint 2 definition.
