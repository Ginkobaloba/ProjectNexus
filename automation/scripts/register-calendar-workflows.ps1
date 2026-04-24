# After running activate-and-build-calendars.ps1, this script reads the saved registry
# entry JSON files and updates workflow-registry.json on disk.
# Run this WITHOUT Claude -- zero API tokens needed.

$registryPath = "C:\Users\Drama\Desktop\Nexus-Automation-Node\workflow-registry.json"
$registry = Get-Content $registryPath | ConvertFrom-Json

$builtFiles = Get-ChildItem "C:\Users\Drama\Desktop\Nexus-Automation-Node\scripts\calendar-built-*.json" -ErrorAction SilentlyContinue

if ($builtFiles.Count -eq 0) {
    Write-Host "No calendar-built-*.json files found. Run activate-and-build-calendars.ps1 first." -ForegroundColor Red
    exit 1
}

foreach ($file in $builtFiles) {
    $entry = Get-Content $file.FullName | ConvertFrom-Json
    $workflowName = $entry.n8nId ? $null : $null  # will use registryEntryKey from builder output

    # The builder saves the full registry entry — find its name from the file
    # File pattern: calendar-built-Calendar_ListCalendars.json
    $rawName = $file.BaseName -replace 'calendar-built-', '' -replace '_', '.'
    # rawName will be like "Calendar.ListCalendars"

    Write-Host "Registering: $rawName (n8nId: $($entry.n8nId))" -ForegroundColor Cyan

    # Find which calendar workflow this maps to and update it
    if ($registry.workflows.PSObject.Properties.Name -contains $rawName) {
        $existing = $registry.workflows.$rawName
        $existing.n8nId = $entry.n8nId
        $existing.status = 'active'
        $existing.lastVerified = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
        $registry.workflows.$rawName = $existing
        Write-Host "  Updated $rawName -> n8nId: $($entry.n8nId)" -ForegroundColor Green
    } else {
        # New entry from builder
        $registry.workflows | Add-Member -NotePropertyName $rawName -NotePropertyValue $entry -Force
        Write-Host "  Added new entry: $rawName" -ForegroundColor Yellow
    }
}

$registry.lastUpdated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
$registry | ConvertTo-Json -Depth 10 | Out-File $registryPath -Encoding utf8
Write-Host "`nRegistry updated: $registryPath" -ForegroundColor Green
Write-Host "Next: git add workflow-registry.json && git commit -m 'Add Calendar workflows'"
