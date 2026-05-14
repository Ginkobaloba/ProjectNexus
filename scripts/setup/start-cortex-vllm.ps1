# start-cortex-vllm.ps1
# Brings up the Cortex inference service on the 4090 box (DREWSPC, 192.168.1.140).
#
# Serves cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit via vLLM in the
# `qwen-vllm` Docker container, OpenAI-compatible API on 0.0.0.0:8000.
#
# The model is already in the HF cache at C:\Users\Drama\.cache\huggingface,
# which is bind-mounted into the container. This script does NOT download it.
#
# Format note: the model is compressed-tensors 4-bit. vLLM auto-detects this
# from config.json, so we pass NO explicit --quantization flag. Do not pass
# --quantization awq_marlin (that is for classic AWQ, not this format).
#
# Memory note: the handoff suggested --gpu-memory-utilization 0.90, but the
# first bring-up crashed with "No available memory for the cache blocks"
# (Available KV cache memory: -2.05 GiB). Measured on this 24 GB 4090:
#   model weights      16.95 GiB
#   non-KV overhead    ~6.7  GiB  (CUDA graphs + torch.compile + activations)
# That overhead does not fit alongside the weights even at util 1.0. We add
# --enforce-eager to drop the CUDA-graph/compile overhead (~4-5 GiB) and bump
# util to 0.92. Inference is a little slower without CUDA graphs; that is fine
# for this milestone, and perf optimization (incl. TRT-LLM) is a later phase.
#
# Idempotent: removes any existing `qwen-vllm` container first.

$ErrorActionPreference = "Stop"

$ContainerName = "qwen-vllm"
$Image         = "vllm/vllm-openai:latest"
$Model         = "cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit"
$HfCache       = "C:\Users\Drama\.cache\huggingface"

Write-Host "[cortex-vllm] Removing any existing '$ContainerName' container..."
docker rm -f $ContainerName 2>$null | Out-Null

Write-Host "[cortex-vllm] Starting '$ContainerName' with model: $Model"
docker run -d `
    --name $ContainerName `
    --gpus all `
    --ipc=host `
    --restart no `
    -p 8000:8000 `
    -v "${HfCache}:/root/.cache/huggingface" `
    $Image `
    $Model `
    --gpu-memory-utilization 0.92 `
    --max-model-len 8192 `
    --enforce-eager `
    --enable-auto-tool-choice `
    --tool-call-parser hermes `
    --host 0.0.0.0 `
    --port 8000

if ($LASTEXITCODE -ne 0) {
    Write-Error "[cortex-vllm] docker run failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[cortex-vllm] Container started. The AWQ model loads in ~2-5 min."
Write-Host "[cortex-vllm] Watch progress:  docker logs -f $ContainerName"
Write-Host "[cortex-vllm] Check readiness: Invoke-RestMethod http://localhost:8000/v1/models"
Write-Host ""
Write-Host "[cortex-vllm] Once /v1/models responds, harden the restart policy:"
Write-Host "[cortex-vllm]   docker update --restart unless-stopped $ContainerName"
