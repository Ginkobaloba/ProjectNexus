$r = Invoke-RestMethod -Method POST `
  -Uri 'https://n8n.projectnexuscode.org/webhook/sms-test-now' `
  -ContentType 'application/json' `
  -Body '{}'
Write-Host "SMS trigger result: $($r | ConvertTo-Json -Compress)"
