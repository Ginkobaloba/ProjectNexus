param([string]$WorkflowId = "BC1BTyaMKAtYAkoc", [int]$Limit = 3)
$apiKey = (Get-Content "C:\Users\Drama\Desktop\Nexus-Automation-Node\.mcp.json" | ConvertFrom-Json).mcpServers.'n8n-mcp'.env.N8N_API_KEY
$headers = @{ 'X-N8N-API-KEY' = $apiKey }

$execs = Invoke-RestMethod -Uri "https://n8n.projectnexuscode.org/api/v1/executions?workflowId=$WorkflowId&limit=$Limit&includeData=true" -Headers $headers
Write-Host "Recent executions for workflow $WorkflowId :"
foreach ($ex in $execs.data) {
    Write-Host "`n--- Execution $($ex.id) | Status: $($ex.status) | Started: $($ex.startedAt) ---"
    if ($ex.data.resultData.error) {
        Write-Host "ERROR: $($ex.data.resultData.error | ConvertTo-Json -Depth 3)"
    }
    if ($ex.data.resultData.runData) {
        foreach ($node in $ex.data.resultData.runData.PSObject.Properties) {
            $lastRun = $node.Value[-1]
            $errMsg = $lastRun.error.message
            if ($errMsg) {
                Write-Host "Node '$($node.Name)' ERROR: $errMsg"
            } else {
                $outData = $lastRun.data.main[0][0].json | ConvertTo-Json -Depth 2 -Compress
                Write-Host "Node '$($node.Name)' OK: $outData"
            }
        }
    }
}
