# scripts/setup/refresh-tailscale-bind.ps1
#
# Sprint 3c: refresh docker/.env with the host's current Tailscale IPv4
# address so the brainstem's published port stays bound to the right
# interface across Tailscale IP rotations. Run this on the 4070 host
# (the brainstem's home) before a `docker compose up -d`.
#
# Behavior:
#   1. Query `tailscale ip -4` for the host's Tailscale address.
#   2. Replace or append BRAINSTEM_BIND_HOST=... in docker/.env.
#   3. Print the resolved address.
#
# No-op fallback: if `tailscale` is not on PATH or returns nothing
# parseable, the script prints a warning and exits non-zero without
# touching .env. The operator can still write the value by hand.

[CmdletBinding()]
param(
    [string]$EnvPath = "$(Split-Path -Parent $PSScriptRoot)\..\docker\.env"
)

$ErrorActionPreference = "Stop"

function Get-TailscaleIPv4 {
    try {
        $raw = & tailscale ip -4 2>$null
    } catch {
        return $null
    }
    if (-not $raw) { return $null }
    # `tailscale ip -4` prints one IPv4 per line. Take the first that
    # looks like a Tailscale CGNAT address (100.x.x.x) to avoid picking
    # up any noise.
    foreach ($line in ($raw -split "`n")) {
        $candidate = $line.Trim()
        if ($candidate -match "^100\.\d+\.\d+\.\d+$") {
            return $candidate
        }
    }
    return $null
}

$ip = Get-TailscaleIPv4
if (-not $ip) {
    Write-Warning "Could not resolve a Tailscale IPv4 address via `tailscale ip -4`. Leaving $EnvPath untouched."
    exit 1
}

$envDir = Split-Path -Parent $EnvPath
if (-not (Test-Path $envDir)) {
    New-Item -ItemType Directory -Path $envDir -Force | Out-Null
}

$existing = if (Test-Path $EnvPath) { Get-Content $EnvPath } else { @() }
$kept = @($existing | Where-Object { $_ -notmatch "^BRAINSTEM_BIND_HOST=" })
$kept += "BRAINSTEM_BIND_HOST=$ip"
Set-Content -Path $EnvPath -Value $kept -Encoding ASCII

Write-Host "BRAINSTEM_BIND_HOST set to $ip in $EnvPath"
