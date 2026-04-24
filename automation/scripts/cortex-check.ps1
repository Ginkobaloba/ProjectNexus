try {
    $r = Invoke-RestMethod 'http://localhost:8001/v1/models' -TimeoutSec 8
    Write-Host "CORTEX OK via localhost: $($r.data[0].id)"
} catch {
    Write-Host "localhost:8001 FAILED: $($_.Exception.Message)"
    try {
        $r2 = Invoke-RestMethod 'http://192.168.62.195:8001/v1/models' -TimeoutSec 8
        Write-Host "CORTEX OK via WSL2 IP 192.168.62.195: $($r2.data[0].id)"
    } catch {
        Write-Host "WSL2 IP also failed: $($_.Exception.Message)"
    }
}

# Check Brainstem
try {
    $b = Invoke-RestMethod 'http://192.168.1.251:8000/v1/models' -TimeoutSec 8
    Write-Host "BRAINSTEM OK: $($b.data[0].id)"
} catch {
    Write-Host "BRAINSTEM FAILED: $($_.Exception.Message)"
}

# Check WSL2 port forwarding state
$proxy = netsh interface portproxy show all 2>$null
if ($proxy) { Write-Host "Port proxies: $proxy" } else { Write-Host "No port proxies configured" }
