# Test Nexus.Orchestrator via a webhook harness
# We'll hit the n8n executions API to trigger a test execution
$apiKey = (Get-Content "C:\Users\Drama\Desktop\Nexus-Automation-Node\.mcp.json" | ConvertFrom-Json).mcpServers.'n8n-mcp'.env.N8N_API_KEY
$headers = @{ 'X-N8N-API-KEY' = $apiKey; 'Content-Type' = 'application/json' }

# Check Cortex is ready
try {
    $model = (Invoke-RestMethod 'http://localhost:8001/v1/models' -TimeoutSec 5).data[0].id
    Write-Host "Cortex ready: $model"
} catch {
    Write-Host "ERROR: Cortex not responding at localhost:8001"
    exit 1
}

# Test Cortex routing directly - ask it to route "search for news about AI"
$messages = @(
    @{ role = "system"; content = "You are the Nexus Orchestrator. Respond with ONLY valid JSON. Available workflows: Web.SearchNews (inputs: query, limit). Route this request to the correct workflow. Format: {`"action`":`"EXECUTE`",`"workflowName`":`"Web.SearchNews`",`"reasoning`":`"brief`",`"inputs`":{`"query`":`"...`"},`"buildSpec`":null}" },
    @{ role = "user"; content = "Search for recent news about artificial intelligence" }
)
$body = @{
    model = "cortex"
    temperature = 0.0
    max_tokens = 512
    chat_template_kwargs = @{ thinking = $false }
    messages = $messages
} | ConvertTo-Json -Depth 10

Write-Host "`nAsking Cortex to route: 'Search for recent news about AI'..."
$r = Invoke-RestMethod -Method POST -Uri 'http://localhost:8001/v1/chat/completions' -ContentType 'application/json' -Body $body
$content = $r.choices[0].message.content
Write-Host "Cortex response: $content"

# Parse the routing decision
try {
    $decision = $content.Trim() | ConvertFrom-Json
    Write-Host "`nRouting decision:"
    Write-Host "  Action: $($decision.action)"
    Write-Host "  Workflow: $($decision.workflowName)"
    Write-Host "  Reasoning: $($decision.reasoning)"
    Write-Host "  Inputs: $($decision.inputs | ConvertTo-Json -Compress)"
} catch {
    Write-Host "Could not parse JSON from Cortex: $content"
}
