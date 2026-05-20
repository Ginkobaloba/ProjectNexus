$apiKey = (Get-Content "C:\Users\Drama\Desktop\Nexus-Automation-Node\.mcp.json" | ConvertFrom-Json).mcpServers.'n8n-mcp'.env.N8N_API_KEY
$headers = @{ 'X-N8N-API-KEY' = $apiKey; 'Content-Type' = 'application/json' }

$r = Invoke-RestMethod -Method POST -Uri "https://n8n.projectnexuscode.org/api/v1/workflows/BC1BTyaMKAtYAkoc/activate" -Headers $headers -Body '{}'
Write-Host "Activated: $($r.name) active=$($r.active)"
