# setup-4070-host.ps1
#
# Bootstraps the Nexus 4070 Super host so it can:
#   1. Hold a local mirror of the project at C:\dev (matching the 4090 box).
#   2. Accept SSH connections from the 4090 box using a key-based auth
#      pair generated on the 4090 side (no passwords, no remembering
#      the local Windows password).
#
# Run on the 4070 from an ELEVATED PowerShell (right-click -> Run as
# Administrator). The script will refuse to run unelevated because it
# needs to install OpenSSH Server, add firewall rules, and write into
# the administrators' authorized_keys file.
#
# Idempotent: safe to re-run. Each step checks state before acting.

[CmdletBinding()]
param(
    [string]$GitHubUser   = 'Ginkobaloba',
    [string]$DevRoot      = 'C:\dev',
    [string]$GitUserName  = 'Drew Mattick',
    [string]$GitUserEmail = 'Dramattick1@gmail.com'
)

$ErrorActionPreference = 'Stop'

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor Cyan
}

function Test-Admin {
    $id  = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p   = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ----------------------------------------------------------------------
# 0. Preflight
# ----------------------------------------------------------------------
Write-Section "0. Preflight"

if (-not (Test-Admin)) {
    Write-Error "This script must run elevated. Right-click PowerShell -> Run as Administrator, then re-run."
    exit 1
}
Write-Host "Running elevated. OK."

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is not installed or not on PATH. Install Git for Windows (https://git-scm.com/download/win) and re-run."
    exit 1
}
Write-Host "git: $(git --version)"

# Python (needed for pre-commit hooks)
$pyOk = $false
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyOk = $true
    Write-Host "python: $(python --version 2>&1)"
} else {
    Write-Warning "python not on PATH. pre-commit hooks will be skipped. Install Python 3.11+ if you want commit-time linting."
}

# ----------------------------------------------------------------------
# 1. C:\dev structure
# ----------------------------------------------------------------------
Write-Section "1. C:\dev structure"

if (-not (Test-Path $DevRoot)) {
    New-Item -ItemType Directory -Path $DevRoot -Force | Out-Null
    Write-Host "Created $DevRoot"
} else {
    Write-Host "$DevRoot already exists"
}

# ----------------------------------------------------------------------
# 2. Git identity
# ----------------------------------------------------------------------
Write-Section "2. Git identity"

$existingName  = git config --global user.name  2>$null
$existingEmail = git config --global user.email 2>$null

if (-not $existingName)  { git config --global user.name  $GitUserName;  Write-Host "Set git user.name = $GitUserName" }  else { Write-Host "git user.name already set: $existingName" }
if (-not $existingEmail) { git config --global user.email $GitUserEmail; Write-Host "Set git user.email = $GitUserEmail" } else { Write-Host "git user.email already set: $existingEmail" }

# Quality-of-life: stop the line-ending dance on Windows
git config --global core.autocrlf true | Out-Null

# ----------------------------------------------------------------------
# 3. Clone the repos
# ----------------------------------------------------------------------
Write-Section "3. Clone repos"

$repos = @(
    @{ Name = 'project-nexus';  Url = "https://github.com/$GitHubUser/ProjectNexus.git";  Branch = 'foundation/consolidation' },
    @{ Name = 'project-vector'; Url = "https://github.com/$GitHubUser/project-vector.git"; Branch = 'main' }
)

foreach ($r in $repos) {
    $target = Join-Path $DevRoot $r.Name
    if (Test-Path "$target\.git") {
        Write-Host "$($r.Name) already cloned, pulling latest"
        Push-Location $target
        try {
            git fetch origin --quiet
            git checkout $r.Branch --quiet
            git pull --ff-only origin $r.Branch
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "Cloning $($r.Url) -> $target"
        git clone --branch $r.Branch $r.Url $target
    }
}

# ----------------------------------------------------------------------
# 4. pre-commit hooks (project-nexus)
# ----------------------------------------------------------------------
Write-Section "4. pre-commit hooks"

if ($pyOk) {
    $nexus = Join-Path $DevRoot 'project-nexus'
    if (Test-Path "$nexus\.pre-commit-config.yaml") {
        Write-Host "Installing pre-commit (pip)"
        python -m pip install --quiet --user pre-commit
        Push-Location $nexus
        try {
            pre-commit install
            Write-Host "pre-commit hooks installed in $nexus"
        } catch {
            Write-Warning "pre-commit install failed: $_"
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "No .pre-commit-config.yaml in project-nexus, skipping"
    }
} else {
    Write-Host "Skipping pre-commit (python not available)"
}

# ----------------------------------------------------------------------
# 5. OpenSSH Server
# ----------------------------------------------------------------------
Write-Section "5. OpenSSH Server"

$capability = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'OpenSSH.Server*' }
if ($capability -and $capability.State -ne 'Installed') {
    Write-Host "Installing OpenSSH Server capability"
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
} else {
    Write-Host "OpenSSH Server capability: $($capability.State)"
}

# Service start + autostart
Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') {
    Start-Service sshd
    Write-Host "Started sshd"
} else {
    Write-Host "sshd already running"
}

# Firewall rule (the OpenSSH install usually creates this, but make sure)
$rule = Get-NetFirewallRule -Name 'sshd' -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name 'sshd' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Write-Host "Created firewall rule 'sshd' for TCP/22"
} else {
    Write-Host "Firewall rule 'sshd' already present"
}

# ----------------------------------------------------------------------
# 6. authorized_keys for key-based login
# ----------------------------------------------------------------------
Write-Section "6. authorized_keys (4090 public key)"

# Public key generated on the 4090 box for THIS specific link.
# Private key never leaves the 4090.
$publicKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHChMJY7a8UdCjCGN6zKOywOIi3vGPMeZ3Xy6TebWFBV nexus-4090-to-4070'

# On Windows, OpenSSH Server reads administrators' keys from
# %ProgramData%\ssh\administrators_authorized_keys for any user in
# the Administrators group. Using the user-level ~/.ssh/authorized_keys
# is also fine for non-admin users, but admins are a different code
# path. We write to both to be safe.

$adminKeysPath = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
$userKeysPath  = Join-Path $env:USERPROFILE '.ssh\authorized_keys'

function Add-Key([string]$Path, [string]$Key) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    if (Test-Path $Path) {
        if (Select-String -Path $Path -Pattern ([Regex]::Escape($Key)) -Quiet) {
            Write-Host "Key already present in $Path"
            return
        }
    }
    Add-Content -Path $Path -Value $Key
    Write-Host "Appended key to $Path"
}

Add-Key -Path $adminKeysPath -Key $publicKey
Add-Key -Path $userKeysPath  -Key $publicKey

# Fix permissions on administrators_authorized_keys (sshd is picky)
if (Test-Path $adminKeysPath) {
    icacls $adminKeysPath /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    Write-Host "Locked down permissions on $adminKeysPath"
}

# ----------------------------------------------------------------------
# 7. Quick summary
# ----------------------------------------------------------------------
Write-Section "7. Done"

$ip = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notmatch '^169\.' } |
       Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host "Hostname:  $env:COMPUTERNAME"
Write-Host "LAN IP:    $ip"
Write-Host ""
Write-Host "On the 4090 box, you can now reach this machine with:"
Write-Host "  ssh -i C:\Users\Drama\.ssh\nexus_4070_ed25519 Drama@$ip"
Write-Host "or (after the 4090-side ssh config entry is in place):"
Write-Host "  ssh nexus-4070"
Write-Host ""
Write-Host "Repos cloned under $DevRoot. SSH key-based access is set up."
