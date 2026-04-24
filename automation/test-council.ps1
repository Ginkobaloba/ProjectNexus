# test-council.ps1
# Manual smoke test for the LLM.Council webhook endpoint.
# Sends a question to the Council (Claude + Gemini + GPT), prints the consensus result.
#
# Usage:
#   .\test-council.ps1                                    # default question
#   .\test-council.ps1 -Question "Should I use Rust?"     # custom question
#   .\test-council.ps1 -Question "Explain recursion" -Label "T2"

param([string]$Question = "What is the capital of France?", [string]$Label = "T1")

$body = @{question = $Question} | ConvertTo-Json
Write-Host "=== $Label ===" -ForegroundColor Cyan
Write-Host "Question: $Question"
Write-Host "Sending request..."

try {
    $r = Invoke-RestMethod `
        -Uri "https://n8n.projectnexuscode.org/webhook/test-llm-council" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 180

    Write-Host ""
    Write-Host "consensus:        $($r.consensus)"
    Write-Host "rounds_completed: $($r.rounds_completed)"
    Write-Host "confidence:       $($r.confidence)"
    Write-Host "vote_tally:       $($r.vote_tally | ConvertTo-Json -Compress)"
    Write-Host "final_answer:     $($r.final_answer)"
    if ($r.dissent) {
        Write-Host "dissent:          $($r.dissent | ConvertTo-Json -Compress)"
    }
    Write-Host "duration_ms:      $($r.meta.duration_ms)"
    Write-Host "action_items:     $($r.action_items -join '; ')"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $err = $_.ErrorDetails.Message
    if ($err) { Write-Host "BODY: $err" -ForegroundColor Red }
}
