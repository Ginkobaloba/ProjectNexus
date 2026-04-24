$apiKey = (Get-Content "C:\Users\Drama\Desktop\Nexus-Automation-Node\.mcp.json" | ConvertFrom-Json).mcpServers.'n8n-mcp'.env.N8N_API_KEY
$headers = @{ 'X-N8N-API-KEY' = $apiKey; 'Content-Type' = 'application/json' }

$ids = @(
  'Rxo8RN4rSosx0QNo',  # Web.Fetch
  'eZtKmzDQyOEd52mY',  # Web.SearchNews
  'nETvnAa8IhtssieI',  # Web.Search
  'q4N1ka1pYIsQM4hA'   # Web.SearchJobs
)

foreach ($id in $ids) {
  $r = Invoke-RestMethod -Method POST -Uri "https://n8n.projectnexuscode.org/api/v1/workflows/$id/activate" -Headers $headers -Body '{}'
  Write-Host "Activated $($r.name) ($($r.id)) active=$($r.active)"
}
