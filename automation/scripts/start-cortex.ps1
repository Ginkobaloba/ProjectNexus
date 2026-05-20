# Start Cortex vLLM in WSL2 if not already running
$running = wsl -d Ubuntu-22.04 bash -lc "ps aux | grep 'vllm serve' | grep -v grep | wc -l"
if ($running.Trim() -eq "0") {
    Write-Host "Starting Cortex vLLM..."
    wsl -d Ubuntu-22.04 bash -lc "nohup ~/cortex-llm/bin/vllm serve nm-testing/Qwen3-Coder-30B-A3B-Instruct-W4A16-awq --max-model-len 32768 --gpu-memory-utilization 0.90 --served-model-name cortex --port 8001 --host 0.0.0.0 > ~/cortex-llm/vllm.log 2>&1 &"
    Write-Host "Cortex launching - model loads in ~2-3 min. Tail logs: wsl -d Ubuntu-22.04 bash -lc 'tail -f ~/cortex-llm/vllm.log'"
} else {
    $model = try { (Invoke-RestMethod 'http://localhost:8001/v1/models' -TimeoutSec 5).data[0].id } catch { "loading..." }
    Write-Host "Cortex already running: $model"
}
