# End-to-end test: POST to Test.Orchestrator webhook -> Nexus.Orchestrator -> Cortex routing -> Web.SearchNews
Write-Host "=== Nexus.Orchestrator End-to-End Test ===" -ForegroundColor Cyan
Write-Host ""

$body = '{"request": "Search for recent news about artificial intelligence"}'

Write-Host "Request: $body"
Write-Host "Sending to: https://n8n.projectnexuscode.org/webhook/test-orchestrator"
Write-Host "(This will take ~15-30 seconds: Cortex routing + RSS fetch)" -ForegroundColor Yellow
Write-Host ""

try {
    $r = Invoke-RestMethod -Method POST `
        -Uri 'https://n8n.projectnexuscode.org/webhook/test-orchestrator' `
        -ContentType 'application/json' `
        -Body $body `
        -TimeoutSec 90

    Write-Host "=== RESULT ===" -ForegroundColor Green
    Write-Host "Status:   $($r.status)"
    Write-Host "Action:   $($r.action)"
    Write-Host "Workflow: $($r.workflowName)"
    Write-Host ""
    if ($r.result) {
        Write-Host "=== SUB-WORKFLOW OUTPUT ===" -ForegroundColor Cyan
        $r.result | ConvertTo-Json -Depth 5 | Write-Host
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        Write-Host "Status code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host "Body: $($reader.ReadToEnd())" -ForegroundColor Red
    }
}
