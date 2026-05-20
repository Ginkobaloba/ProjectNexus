# Activate Test.Builder, then use Cortex to generate all 6 Calendar workflows.
# This script costs ZERO Claude API tokens — everything runs on local Cortex GPU.

$apiKey = (Get-Content "C:\Users\Drama\Desktop\Nexus-Automation-Node\.mcp.json" | ConvertFrom-Json).mcpServers.'n8n-mcp'.env.N8N_API_KEY
$headers = @{ 'X-N8N-API-KEY' = $apiKey; 'Content-Type' = 'application/json' }

# Activate Test.Builder
$r = Invoke-RestMethod -Method POST -Uri "https://n8n.projectnexuscode.org/api/v1/workflows/9FPP8XeBy9t6iW33/activate" -Headers $headers -Body '{}'
Write-Host "Test.Builder activated: $($r.active)" -ForegroundColor Green

# Calendar workflow specs pulled from workflow-registry.json
$calendarWorkflows = @(
  @{
    name = "Calendar.ListCalendars"
    description = "List all Google Calendars the authenticated user has access to"
    domain = "calendar"
    required_inputs = @{
      showHidden = @{ type = "boolean"; required = $false; description = "Include hidden calendars (default false)" }
    }
    expected_outputs = @{
      calendars = @{ type = "array"; description = "Array of {calendarId, name, description, timezone, accessRole, primary, backgroundColor}" }
      count = @{ type = "number"; description = "Total number of calendars returned" }
    }
  },
  @{
    name = "Calendar.List"
    description = "List upcoming Google Calendar events with optional date range and text filters"
    domain = "calendar"
    required_inputs = @{
      calendarId = @{ type = "string"; required = $false; description = "Calendar ID (default: primary)" }
      timeMin = @{ type = "string"; required = $false; description = "ISO 8601 lower bound for event start (default: now)" }
      timeMax = @{ type = "string"; required = $false; description = "ISO 8601 upper bound (default: now + 7 days)" }
      query = @{ type = "string"; required = $false; description = "Free-text search across title, description, location" }
      limit = @{ type = "number"; required = $false; description = "Max events to return (default 10)" }
    }
    expected_outputs = @{
      events = @{ type = "array"; description = "Array of {eventId, calendarId, title, start, end, location, description, status, attendeeCount, isRecurring, htmlLink}" }
      count = @{ type = "number"; description = "Total events returned" }
    }
  },
  @{
    name = "Calendar.Get"
    description = "Get a single Google Calendar event by ID"
    domain = "calendar"
    required_inputs = @{
      eventId = @{ type = "string"; required = $true; description = "Google Calendar event ID" }
      calendarId = @{ type = "string"; required = $false; description = "Calendar containing the event (default: primary)" }
    }
    expected_outputs = @{
      eventId = @{ type = "string"; description = "Event ID" }
      title = @{ type = "string"; description = "Event title" }
      start = @{ type = "string"; description = "ISO 8601 start datetime" }
      end = @{ type = "string"; description = "ISO 8601 end datetime" }
      location = @{ type = "string"; description = "Event location" }
      description = @{ type = "string"; description = "Event description" }
      attendees = @{ type = "array"; description = "Array of {email, displayName, responseStatus}" }
      htmlLink = @{ type = "string"; description = "URL to open in Google Calendar" }
    }
  },
  @{
    name = "Calendar.Create"
    description = "Create a new Google Calendar event"
    domain = "calendar"
    required_inputs = @{
      title = @{ type = "string"; required = $true; description = "Event title" }
      start = @{ type = "string"; required = $true; description = "ISO 8601 start datetime" }
      end = @{ type = "string"; required = $true; description = "ISO 8601 end datetime" }
      calendarId = @{ type = "string"; required = $false; description = "Target calendar ID (default: primary)" }
      description = @{ type = "string"; required = $false; description = "Event description" }
      location = @{ type = "string"; required = $false; description = "Event location" }
      attendees = @{ type = "array"; required = $false; description = "Array of attendee email address strings" }
    }
    expected_outputs = @{
      eventId = @{ type = "string"; description = "Newly created event ID" }
      calendarId = @{ type = "string"; description = "Calendar where event was created" }
      title = @{ type = "string"; description = "Event title" }
      start = @{ type = "string"; description = "ISO 8601 start datetime" }
      end = @{ type = "string"; description = "ISO 8601 end datetime" }
      htmlLink = @{ type = "string"; description = "URL to open event in Google Calendar" }
      status = @{ type = "string"; description = "confirmed" }
    }
  },
  @{
    name = "Calendar.Update"
    description = "Modify fields on an existing Google Calendar event (patch semantics - only provided fields change)"
    domain = "calendar"
    required_inputs = @{
      eventId = @{ type = "string"; required = $true; description = "Event ID to update" }
      calendarId = @{ type = "string"; required = $false; description = "Calendar containing the event (default: primary)" }
      title = @{ type = "string"; required = $false; description = "New event title" }
      start = @{ type = "string"; required = $false; description = "New ISO 8601 start datetime" }
      end = @{ type = "string"; required = $false; description = "New ISO 8601 end datetime" }
      description = @{ type = "string"; required = $false; description = "New description" }
      location = @{ type = "string"; required = $false; description = "New location" }
    }
    expected_outputs = @{
      eventId = @{ type = "string"; description = "Event ID" }
      title = @{ type = "string"; description = "Updated title" }
      start = @{ type = "string"; description = "Updated start datetime" }
      end = @{ type = "string"; description = "Updated end datetime" }
      htmlLink = @{ type = "string"; description = "URL to open event in Google Calendar" }
      updated = @{ type = "string"; description = "ISO 8601 timestamp of this update" }
    }
  },
  @{
    name = "Calendar.FindFreeSlot"
    description = "Find available time slots of a specified duration within a search window using Google Calendar free/busy API"
    domain = "calendar"
    required_inputs = @{
      durationMinutes = @{ type = "number"; required = $true; description = "Required slot length in minutes (e.g. 30, 60, 90)" }
      searchStart = @{ type = "string"; required = $false; description = "ISO 8601 start of search window (default: now)" }
      searchEnd = @{ type = "string"; required = $false; description = "ISO 8601 end of search window (default: now + 7 days)" }
      calendarId = @{ type = "string"; required = $false; description = "Calendar to check (default: primary)" }
      workdayStartHour = @{ type = "number"; required = $false; description = "Working day start hour (default 9)" }
      workdayEndHour = @{ type = "number"; required = $false; description = "Working day end hour (default 17)" }
    }
    expected_outputs = @{
      slots = @{ type = "array"; description = "Array of {start, end, durationMinutes} representing available time slots" }
      count = @{ type = "number"; description = "Number of free slots found" }
      searched = @{ type = "object"; description = "{from, to} the window that was searched" }
    }
  }
)

$results = @()
$builderUrl = 'https://n8n.projectnexuscode.org/webhook/test-builder'

foreach ($wf in $calendarWorkflows) {
  Write-Host "`n========================================" -ForegroundColor Cyan
  Write-Host "Building: $($wf.name)" -ForegroundColor Yellow
  Write-Host "(Cortex generating workflow JSON — may take 30-60 seconds...)"

  $payload = @{
    description = $wf.description
    domain = $wf.domain
    required_inputs = $wf.required_inputs
    expected_outputs = $wf.expected_outputs
  } | ConvertTo-Json -Depth 6 -Compress

  try {
    $resp = Invoke-RestMethod -Method POST -Uri $builderUrl -ContentType 'application/json' -Body $payload -TimeoutSec 300
    $results += [PSCustomObject]@{
      name = $wf.name
      status = $resp.status
      workflowId = $resp.workflowId
      workflowName = $resp.workflowName
      error = $resp.error_code
    }
    if ($resp.status -eq 'success') {
      Write-Host "SUCCESS: $($wf.name) -> n8nId: $($resp.workflowId)" -ForegroundColor Green
      # Save registry entry to file for manual registration
      $entryFile = "scripts\calendar-built-$($wf.name -replace '\.', '_').json"
      $resp.registryEntry | ConvertTo-Json -Depth 6 | Out-File $entryFile -Encoding utf8
      Write-Host "Registry entry saved to: $entryFile"
    } else {
      Write-Host "FAILED: $($wf.name) -> $($resp.error_code)" -ForegroundColor Red
    }
  } catch {
    Write-Host "HTTP ERROR building $($wf.name): $($_.Exception.Message)" -ForegroundColor Red
    $results += [PSCustomObject]@{
      name = $wf.name; status = 'http_error'; workflowId = ''; workflowName = ''; error = $_.Exception.Message
    }
  }

  # Brief pause between builds to avoid hammering Cortex
  Start-Sleep -Seconds 5
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "BUILD SUMMARY:" -ForegroundColor Cyan
$results | Format-Table -AutoSize

Write-Host "`nNext step: Run scripts\register-calendar-workflows.ps1 to update workflow-registry.json"
