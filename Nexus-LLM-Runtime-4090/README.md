# Nexus-LLM-Runtime-4090

Inference runtime for the 4090 host. As of Sprint 5, the runtime direction is
**llama.cpp (`llama-server`)**, not vLLM/TensorRT-LLM — see
`docs/architecture_v2_family_of_models.md` Section 6. `compose.yaml` (the
trtllm setup) stays in this directory as historical reference until Drew
retires it; do not use it for new deployments.

## Two ways to run the runtime

**A. Model manager spawns llama-server natively (V1 default).**
`nodes/model_manager_4090` (`manager.py`) owns weights tiering, the
llama-server process lifecycle, and presence reporting to the hub. It calls
`llama-server` as a plain subprocess with the flags below — no Docker
involved. This is the default because the manager needs direct control over
staging weights onto the hot tier (`ensure_hot()`) before each spawn, and
needs to poll `/health` and manage SIGTERM/SIGKILL directly. Use this path
whenever the model manager service is running.

**B. `compose.llamacpp.yaml` (standalone / manual bring-up).**
Use this compose file when you need to run llama-server by hand — the model
manager isn't running, you're debugging a GGUF outside the manager's
lifecycle, or you want a quick manual smoke test. It runs the official CUDA
server image (`ghcr.io/ggml-org/llama.cpp:server-cuda`), mounts the hot tier
at `/models`, and passes the same flags the manager would pass for family
member #1 ("vera"). It does **not** do tiering or presence reporting — those
only happen when the manager is in the loop (path A).

## Model manager environment variables

The manager reads settings via `MODELMGR_`-prefixed env vars
(`nodes/model_manager_4090/config.py`):

| Variable | Purpose |
|---|---|
| `MODELMGR_HOT_DIR` | Hot tier path (2 TB Gen4 NVMe) — active/loadable weights. |
| `MODELMGR_WARM_DIR` | Warm tier path (1 TB Gen2 NVMe) — occasional members. |
| `MODELMGR_COLD_DIR` | Cold tier path (6 TB HDD/NAS) — archive. |
| `MODELMGR_HUB_URL` | Hub base URL the manager reports presence to. |
| `MODELMGR_HUB_TOKEN` | Bearer token for the hub's presence endpoint. |
| `MODELMGR_LLAMA_SERVER_BIN` | Path/name of the `llama-server` binary the manager spawns. |

## Weights filename convention

`weights_filename()` in `nodes/model_manager_4090/manager.py` builds the
on-disk filename as `<source repo tail>.<quant>.<format>`, where the source
tail is the last path segment of `model.source` from `family/registry.yaml`.

For family member #1 ("vera": `hf:Qwen/Qwen3-30B-A3B-Instruct-2507`, quant
`Q4_K_M`, format `gguf`), the exact expected filename is:

```
Qwen3-30B-A3B-Instruct-2507.Q4_K_M.gguf
```

Download tooling, the hot/warm/cold tier directories, and both runtime paths
above (A and B) must all agree on this name.

## Why tiering exists: don't mmap off the cold tier

`llama.cpp` does not tier weights for us — `mmap` will happily page a GGUF
straight off the HDD/cold tier, and it works, but page-in latency makes
inference miserable. That's the exact failure mode
`nodes/model_manager_4090`'s tiering (`ensure_hot()`) exists to avoid: it
stages weights onto the hot NVMe tier *before* starting llama-server, so the
model only ever loads/mmaps from fast storage. If you bring the runtime up
by hand (path B), make sure the file under `D:/family_weights/hot` is
actually there and not a broken symlink back to cold storage.
