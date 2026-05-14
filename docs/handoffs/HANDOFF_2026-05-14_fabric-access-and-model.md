# Handoff: 2026-05-14 — Fabric access established, model staged

This handoff compacts a long working session. A fresh session should
be able to pick up from here without the back-and-forth context.

## Where we are

The Nexus fabric's two-box infrastructure is set up and the inference
model is downloaded and verified. We have NOT yet brought vLLM up with
the new model or wired the two boxes' services together. That is the
next step.

## Project framing (the why)

Nexus is the digital-autonomy substrate. The near-term goal is to make
a locally hosted LLM, augmented by the fabric (orchestration, memory,
callback-capable inference), outperform the bare base model running
alone on the 4090. The longer arc: Nexus becomes the brain that Vector
(the embodied, physical-world platform) plugs into. End goal is AGI;
this is a deliberate early step, not a moonshot sprint.

We are treating this as a research artifact. Experiment 1 is a
systems-characterization paper: characterize the fabric's performance
envelope so we know whether the system itself is the bottleneck before
running any inference-quality experiment. Design doc lives at
`docs/experiments/experiment-1-pipeline-characterization.md`. It has
Phase 0 (minimum viable fabric build) and Phase 1 (characterization).

The MVP we are building toward, "Option B": a local assistant with
persistent memory across sessions, reachable from any node. Text-only
first. Jetsons and Vector vision are deliberately out of scope for the
MVP. The MVP validates the brain so Vector can later plug into it.

## Hardware and topology

Two Windows Pro boxes, same LAN (192.168.1.0/24), both also on
Tailscale (stable mesh addresses that survive DHCP changes).

| Role | Hostname | LAN IP | Tailscale IP |
|------|----------|--------|--------------|
| Heavy inference (4090, 24GB) | DREWSPC | 192.168.1.140 | 100.78.100.97 |
| Orchestrator (4070 Super, 12GB) | BROOKFIELD_PC | 192.168.1.251 | 100.89.210.52 |

The architecture is a heterogeneous compute fabric, not a linear
pipeline. The 4070 orchestrates (routing, memory retrieval, prep) and
the 4090 does heavy inference. Critically, the 4090 can call BACK to
the 4070 mid-inference for additional context. That bidirectional
callback is meant to be implemented as a tool the 4090's model can
call, using vLLM's tool-calling support.

NVMe (1TB Gen 2) is destined for the 4090 box for model weights. The
Chroma DB stays on the 4070's local SSD, since the 4070 is the heavy
DB reader and we don't want every retrieval crossing the LAN.

Jetsons: 4x Jetson Nano (2x 2GB, 2x 4GB), Maxwell-era. These are edge
perception nodes for the eventual Vector phase, NOT LLM nodes, and are
out of scope for the MVP.

## Access (how to drive both boxes)

SSH key-based auth is working from the 4090 to the 4070.

- Private key (4090 only): `C:\Users\Drama\.ssh\nexus_4070_ed25519`
- SSH config entry `nexus-4070` points at 192.168.1.251
- The 4070's `setup-4070-host.ps1` (in `scripts/setup/`) installed
  OpenSSH Server, opened the firewall, and dropped the 4090's public
  key into both `administrators_authorized_keys` and the user
  `authorized_keys`. The script is idempotent.

IMPORTANT QUIRK: the Windows native `ssh.exe`
(`C:\Windows\System32\OpenSSH\ssh.exe`) returns exit 255 with no output
in the automation/PowerShell context used this session. Git for
Windows' ssh works fine. Use:
`C:\Program Files\Git\usr\bin\ssh.exe`
Example that works:
`& "C:\Program Files\Git\usr\bin\ssh.exe" -o BatchMode=yes -i C:\Users\Drama\.ssh\nexus_4070_ed25519 Drama@192.168.1.251 "<cmd>"`

Also: the HF private-key file needs locked-down ACLs or ssh refuses
it silently. It is already locked to `DREWSPC\Drama:(F)` only.

## Model status

DOWNLOADED AND VERIFIED on the 4090:
`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`
- 16.87 GB in the HF cache at `C:\Users\Drama\.cache\huggingface`
- All 4 safetensors shards + tokenizer + config present
- Format: `compressed-tensors`, 4-bit pack-quantized, group_size 32,
  MoE gates and lm_head left unquantized (standard, good for quality)
- Architecture: `Qwen3MoeForCausalLM` (30B total, 3B active MoE)

This is plug-and-play with vLLM. vLLM auto-detects `compressed-tensors`
from `config.json`. CORRECTION to an earlier note: do NOT pass
`--quantization awq_marlin`. This is compressed-tensors format, not
classic AWQ. Either omit `--quantization` entirely (vLLM auto-detects)
or pass `--quantization compressed-tensors`.

Why this model: Qwen3-30B-A3B is the strongest option in the 24GB
tier per the HF survey. MoE design gives 30B-class capability at
3B-active inference speed. Has a VLM sibling (Qwen3-VL-30B-A3B) for
the eventual Vector phase. Same family as the recommended 4070
orchestrator model, so tokenizers line up.

The OLD model that was running, `Qwen3-Coder-30B-A3B-Instruct-FP8`,
does NOT fit. FP8 of a 30B model is ~30GB and the 4090 has 24GB. The
`qwen-vllm` container crashed on engine init because of this. It needs
to be reconfigured to point at the AWQ model above.

## Docker state (4090)

Containers present (all stopped unless noted):
- `qwen-vllm` — vLLM, was running the too-big FP8 coder model, crashed.
  Reconfigure this to the AWQ model.
- `cortex` — older vLLM (v0.15.1), exited.
- `trtllm` — TensorRT-LLM container, never got working. High-value
  future work: TRT-LLM compiles to the actual CUDA kernel topology,
  big perf upside. Deferred to Phase 1 inference optimization.
- `n8n`, `traefik`, `cloudflared` — the automation stack, stopped.

HF cache is bind-mounted: `C:\Users\Drama\.cache\huggingface` ->
`/root/.cache/huggingface` inside `qwen-vllm`. The new model is
already visible to the container through this mount.

## Repo state

`github.com/Ginkobaloba/ProjectNexus`, branch `foundation/consolidation`.
Both boxes synced at commit `0d9c6b8`. Working trees clean.

Commits this session:
- `7274ee0` Experiment 1 design doc into `docs/experiments/`
- `b66fa38` archived vendored n8n-mcp, tracked cortex compose + paper
  draft, documented the direction shift
- `398608c` added `scripts/setup/setup-4070-host.ps1`
- `0d9c6b8` fixed the setup script's pre-commit step

The vendored `n8n-mcp` clone is gitignored with a graceful archive
note at `docs/archived/n8n-integration.md`. Nothing was deleted. The
direction going forward is native LLM tool-calling against our own
services, not an external workflow engine.

Pre-commit hooks are active on this repo (secrets scan, large files,
end-of-file-fixer, trailing whitespace). They auto-fix files and then
the commit needs a re-stage + re-commit. Budget for one retry.

## Key decisions and why

- Heterogeneous compute fabric, not a linear pipeline. The 4090 can
  call back to the 4070 for context mid-inference.
- No learned-compression sub-experiment on the 4070<->4090 link. PCIe
  is the hard physical floor and the data is already tokenized;
  software effort there would be fighting a hardware ceiling.
- vLLM for the MVP (we have a working image and the AWQ model it
  wants). TRT-LLM deferred to Phase 1 perf optimization.
- "Punch above weight class" dropped as a thesis. Experiment 1 is a
  plain systems-characterization paper.
- DB on the 4070's local SSD, not the 4090 NVMe, because the 4070 is
  the heavy DB reader.

## Next steps (pick up here)

1. Reconfigure and start the `qwen-vllm` container on the 4090 with
   the AWQ model. Suggested vLLM args: `--model
   cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`, no explicit
   `--quantization` (auto-detect), `--gpu-memory-utilization 0.90`,
   `--max-model-len 8192`, `--enable-auto-tool-choice
   --tool-call-parser hermes` for the bidirectional callback. Bind to
   `0.0.0.0:8000` so the 4070 can reach it.
2. Verify the 4090 endpoint serves: `GET /v1/models` should report the
   AWQ model, and a `/v1/chat/completions` call should return text.
3. Bring up the brainstem service on the 4070 (code is in the repo).
4. Wire brainstem's HTTP client to the 4090's vLLM endpoint over LAN
   (`192.168.1.140:8000`).
5. Milestone: a request to the 4070 brainstem returns generated text
   that came from the 4090. That is "the two boxes can talk."
6. Then Phase 0 MVP proper: persistent memory via Chroma on the 4070,
   multi-node client access, the rolling characterization harness.

## Open questions still unanswered

- Whether to download the 4070 orchestrator models now
  (`Qwen3-4B-Instruct-2507` + `Qwen3-Embedding-0.6B` per the HF survey).
- Exact wire format between brainstem and the 4090.
- Clock sync between the two boxes for the Phase 1 measurement work.
- Whether implementing the missing fabric pieces (router, cache,
  callback channel) is in scope for Experiment 1's Phase 0 or a
  separate effort.
