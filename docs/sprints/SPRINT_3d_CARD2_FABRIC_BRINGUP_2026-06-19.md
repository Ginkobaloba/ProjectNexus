# Sprint 3d: Card 2 fabric bring-up via Tailscale + Docker on the 4070

Date: 2026-06-19
Author: Card 2 Fabric Bring-Up Agent (Sonnet), under Drew's direction
Scope: Sprint 3d Card 2 acceptance. Brings the 4070 brainstem, NAS, and embedder back online over Tailscale, with end-to-end cross-host health verified from the 4090.

Companion to: `docs/sprints/SPRINT_3d_PLAN_2026-06-18.md` (the plan of record), `docs/sprints/SPRINT_3d_INTEGRATION_RESULTS_2026-06-18.md` (Card 3 acceptance), and `NEXUS_STATE_AUDIT_2026-06-16.md` (which calls `scripts/setup/refresh-tailscale-bind.ps1` the highest-leverage single action).

## 1. Headline

The fabric is up. From the 4090:

```
$ curl -s http://100.89.210.52:5001/health
{"status":"ok","embedder_reachable":true,"stm_size":0}
```

That is a brainstem on the 4070 (Tailscale IP 100.89.210.52), answering on its Tailscale-bound port, reporting the embedder reachable and the per-session STM live. The closed loop that the 2026-06-16 audit called "no closed loop today" is closed.

What changed since the 2026-06-16 audit and the 2026-06-18 Card 3 hand-off:

| Surface | Before (2026-06-18) | After (this PR) |
|---|---|---|
| 4070 Tailscale | Daemon stuck in `NoState`, offline 6 days | Online, IP 100.89.210.52, hostname `brookfield-4070`, unattended-mode |
| 4070 Docker Desktop | Off, no daemon | Running, Engine 28.5.1, Compose v2.40.3 |
| `docker/.env` | Missing | Present, `BRAINSTEM_BIND_HOST=100.89.210.52` |
| brainstem container | Down | Up, healthy, published on Tailscale IP only |
| nas container | Down | Up |
| embedder container | Down | Up, embedder reachable from brainstem |
| Cross-host `/health` | Blocked | 200 OK over Tailscale from 4090 |

This PR documents the steps. No source under `nodes/`, `clients/`, `core/`, `tests/`, or `docker/` is modified. The only repo additions are this results doc.

## 2. Phase 1: Tailscale recovery on the 4070

### 2.1 What was broken

The 4070's `tailscaled` was Running but parked in `NoState` ("Tailscale is starting. Please wait."). The IPN backend was tied to user `lilly`'s interactive console session (session 1), so `tailscale` CLI calls from drama's SSH session returned `401 Unauthorized: Tailscale already in use by Brookfield_PC\lilly`. Logout + Restart-Service moved the daemon to `NeedsLogin` briefly, but any `tailscale up` without `--unattended` immediately retreated to `NoState` because the daemon ties `WantRunning` to whoever opened the IPN socket. The log line that gave it away:

```
client disconnected (Brookfield_PC\Drama): disconnecting Tailscale
Switching ipn state NeedsLogin -> NoState (WantRunning=false, nm=false)
```

When our SSH-spawned PowerShell process exited (which it does the instant the SSH command returns), the IPN backend tore the session down with it.

### 2.2 What fixed it

The working command, run as drama (Administrators, elevated) over SSH:

```powershell
tailscale up `
    --authkey=<value from _secrets/tailscale_auth_token.local.txt> `
    --reset `
    --unattended `
    --hostname=brookfield-4070 `
    --accept-routes `
    --timeout=120s
```

The unlock was `--unattended`. With that flag the daemon stays `WantRunning=true` even after the user that ran `up` disconnects, which is exactly the headless-server semantics we want on the 4070.

Notes on getting there:

- `--operator=<user>` is NOT a valid flag on `tailscale up` for Windows 1.98.4. Passing it aborts the command before the authkey is consumed (which, on the bright side, saved the key for the retry).
- The authkey is single-use. We treated it like a password: piped through SSH stdin into a PowerShell that reads from `[Console]::In.ReadLine()` before invoking `tailscale.exe`. The remote command-line shows only `powershell -EncodedCommand <wrapper that reads stdin>`; the key is never in argv. All printed output is scrubbed (`-replace [regex]::Escape($key), '[REDACTED]'`) before being returned over SSH.
- The "Failed to set the network category to private on the Tailscale adapter" health warning on Windows is non-fatal; the tunnel comes up regardless.

### 2.3 Verification

From the 4090:

```
> tailscale status | findstr brookfield-4070
100.89.210.52  brookfield-4070  dramattick1@  windows  -

> ping -n 3 100.89.210.52
Reply from 100.89.210.52: bytes=32 time=5ms TTL=128
Reply from 100.89.210.52: bytes=32 time=8ms TTL=128
Reply from 100.89.210.52: bytes=32 time=56ms TTL=128

avg 23ms, 0 percent loss
```

## 3. Phase 2: Docker Desktop on the 4070

### 3.1 What was broken

The `com.docker.service` Windows service was Stopped, no `dockerd`/`Docker Desktop`/`com.docker.backend` processes were running, and the `dockerDesktopLinuxEngine` named pipe did not exist. The CLI was installed at `C:\Program Files\Docker\Docker\resources\bin\docker.exe` and the GUI at `C:\Program Files\Docker\Docker\Docker Desktop.exe`, both reachable.

The naive fix (`Start-Service com.docker.service; Start-Process "Docker Desktop.exe"` from SSH) brought the daemon up briefly, but Docker Desktop is a per-user GUI app that needs an interactive desktop. Spawning it from drama's services-session SSH connection caused it to exit the moment the SSH command returned. That is the same Windows session-binding pattern that bit Tailscale in Phase 1, in a different costume.

### 3.2 What fixed it

A scheduled task running as lilly (the user with an active console session at qwinsta ID 1, State=Active), invoked via a tiny `.bat` to avoid `schtasks` quote handling for paths with spaces:

```cmd
:: C:\dev\_resume_4070\start-docker-desktop.bat
@echo off
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

```powershell
Start-Service com.docker.service
schtasks /Create /TN NexusDockerDesktopOneShot `
    /TR "C:\dev\_resume_4070\start-docker-desktop.bat" `
    /SC ONCE /ST 23:59 /RL HIGHEST `
    /RU "BROOKFIELD_PC\lilly" /IT /F
schtasks /Run /TN NexusDockerDesktopOneShot
```

The `/IT` flag means "only when the user is logged on", and lilly is logged on, so the task launches Docker Desktop inside her session 1. The process survives our SSH session.

Earlier attempts that failed and why, captured for future-us:

- `schtasks ... /RU "BROOKFIELD_PC\drama" /IT` returned Last Result `267011` (`SCHED_E_USER_NOT_LOGGED_ON`). drama only has the SSH services session, not an interactive desktop.
- `schtasks ... /TR "\"C:\Program Files\Docker\Docker\Docker Desktop.exe\""` (direct path with embedded quotes) returned Last Result `-2147024894` (`ERROR_FILE_NOT_FOUND`). schtasks's argument parser does not handle nested quotes consistently. The `.bat` wrapper sidesteps this entirely.

### 3.3 Verification

```
> docker version --format '{{.Server.Version}}'
28.5.1

> docker info --format '{{.OperatingSystem}} / {{.OSType}}/{{.Architecture}} {{.ServerVersion}}'
Docker Desktop / linux/x86_64 28.5.1

> docker compose version
Docker Compose version v2.40.3-desktop.1
```

## 4. Phase 3: docker/.env refresh

### 4.1 What was broken

`docker/.env` was missing on the 4070. The compose file falls back to `${BRAINSTEM_BIND_HOST:-127.0.0.1}` without it, which means a brainstem that binds only to localhost is invisible to Tailscale peers, which makes the entire off-LAN access promise of Sprint 3c silently false.

### 4.2 What fixed it

`scripts/setup/refresh-tailscale-bind.ps1` queries `tailscale ip -4`, filters for a `100.x.x.x` Tailscale CGNAT address, and writes `BRAINSTEM_BIND_HOST=<that ip>` into `docker/.env`. After Phase 1, `tailscale ip -4` returns `100.89.210.52`, so the script produces:

```
# docker/.env (35 bytes)
BRAINSTEM_BIND_HOST=100.89.210.52
```

### 4.3 Gotcha: param default

The script's param default is

```powershell
[string]$EnvPath = "$(Split-Path -Parent $PSScriptRoot)\..\docker\.env"
```

Under our SSH-driven `powershell -NoProfile -File <script>` invocation `$PSScriptRoot` evaluated to empty and `Split-Path -Parent ""` threw. Workaround for this PR: pass `-EnvPath C:\dev\project-nexus\docker\.env` explicitly. Suggested follow-up hygiene PR: change the default to use `$PSCommandPath` or compute it inside the body once `$PSScriptRoot` is bound:

```powershell
param([string]$EnvPath)
if (-not $EnvPath) {
    $EnvPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) "..\docker\.env"
}
```

That makes the script robust to non-interactive invocation patterns including `powershell -File` from SSH.

## 5. Phase 4: docker compose up + healthcheck

### 5.1 Bring-up sequence

```powershell
Set-Location C:\dev\project-nexus\docker
docker compose up -d --build
```

First-time build is heavy because the embedder Dockerfile installs torch (CPU wheel) + sentence-transformers + chromadb, and all three services pull `python:3.11-slim` and run `apt-get install build-essential` (~82 MB of debian packages). Total build wall time on this run was approximately five minutes from cold cache to all-containers-running. Subsequent rebuilds should be quick because layer cache is warm. Image sizes after the build:

| Image | Size |
|---|---|
| docker-embedder:latest | 2.75 GB |
| docker-nas:latest | 1.18 GB |
| docker-brainstem:latest | 690 MB |
| python:3.11-slim (base) | 186 MB |

### 5.2 Running as a scheduled task

Same trick as Docker Desktop in Phase 2 and for the same reason. The compose build was attempted twice from a backgrounded PowerShell launched via `Start-Process` from an SSH session, and both times the build either stalled silently (Tee-Object buffering masked progress for minutes) or the parent shell collapsed and the build process disappeared. Switching to a scheduled task running as lilly made the build complete cleanly.

```powershell
# C:\dev\_resume_4070\wrap_compose_up.ps1 (rough shape)
$ErrorActionPreference = 'Continue'
Set-Location 'C:\dev\project-nexus\docker'
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose up -d --build *>> 'C:\dev\_resume_4070\compose_up.log'
'LASTEXITCODE=' + $LASTEXITCODE | Out-File -FilePath 'C:\dev\_resume_4070\compose_up.log' -Append -Encoding UTF8
'done' | Out-File -FilePath 'C:\dev\_resume_4070\compose_up.done' -Force
```

```powershell
schtasks /Create /TN NexusComposeUp `
    /TR 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\dev\_resume_4070\wrap_compose_up.ps1"' `
    /SC ONCE /ST 23:59 /RL HIGHEST `
    /RU "BROOKFIELD_PC\lilly" /IT /F
schtasks /Run /TN NexusComposeUp
```

This is fully repeatable. Re-firing the task is the standard way to retry a build after a transient failure on this host.

### 5.3 Verification

From the 4070:

```
> docker compose ps
NAME             SERVICE     STATUS                    PORTS
brainstem_4070   brainstem   Up 26 seconds (healthy)   100.89.210.52:5001->5001/tcp
embedder_4070   embedder    Up 26 seconds             0.0.0.0:5003->5003/tcp, [::]:5003->5003/tcp
nas_memory       nas         Up 26 seconds             0.0.0.0:5002->5002/tcp, [::]:5002->5002/tcp

> docker logs --tail 10 brainstem_4070
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:5001 (Press CTRL+C to quit)
INFO:     127.0.0.1:33178 - "GET /health HTTP/1.1" 200 OK
```

The "(healthy)" status on brainstem_4070 is the compose-defined healthcheck (a Python `urllib.request.urlopen('http://127.0.0.1:5001/health', timeout=3)` that demands HTTP 200) succeeding.

The Tailscale-bound publish (`100.89.210.52:5001->5001/tcp`) is exactly what Sprint 3c's exposure design intended: only Tailscale peers can reach :5001. The brainstem is not accidentally publishing on `0.0.0.0`.

From the 4090, over Tailscale:

```
> Invoke-WebRequest http://100.89.210.52:5001/health -UseBasicParsing
StatusCode        : 200
Content           : {"status":"ok","embedder_reachable":true,"stm_size":0}
```

That is the actual cross-host smoke test the audit said the fabric had never passed. It has now passed.

## 6. What this unblocks

| Item | Status before | Status now |
|---|---|---|
| Audit blocker 1 (no running fabric) | Open | Closed |
| Audit blocker 3 (4070 offline on Tailscale) | Open | Closed |
| HANDOFF Section A (laptop browser) | BLOCKED-ON-CARD-2 | Ready to run |
| HANDOFF Section B (phone browser) | DEFERRED-ON-TAILSCALE | Ready to run |
| HANDOFF Section C (CLI) | BLOCKED-ON-CARD-2 | Ready to run |
| HANDOFF Section D (Cortex-down) | BLOCKED-ON-CARD-2 | Ready to run |
| HANDOFF Section E (token revocation) | BLOCKED-ON-CARD-2 | Ready to run |
| HANDOFF Section F (cross-device continuity) | DEFERRED-ON-TAILSCALE | Ready to run |
| `pytest` `tests/integration/` live-smoke (NEXUS_LIVE_URL=http://100.89.210.52:5001) | DEFERRED-ON-TAILSCALE-AND-FABRIC | Ready to run |

The four `test_live_smoke.py` tests that PR #8 marked SKIPPED for lack of a live wire can now be run by exporting `NEXUS_LIVE_URL=http://100.89.210.52:5001` and a valid `NEXUS_LIVE_TOKEN` and re-running `python -m pytest tests/integration/test_live_smoke.py -v`. That is a separate card; this PR just unblocks it.

## 7. If it breaks again: the runbook

The full re-bring-up from a cold 4070 (Tailscale offline, Docker off, no `.env`) is, in order:

```
# 1. Tailscale (as drama via SSH, elevated)
Stop-Service Tailscale -Force
Get-Process tailscale-ipn -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Service Tailscale
# wait for BackendState=NeedsLogin
tailscale up --authkey=<value> --reset --unattended --hostname=brookfield-4070 --accept-routes --timeout=120s

# 2. Docker Desktop (scheduled task as lilly, the interactive user)
Start-Service com.docker.service
schtasks /Create /TN NexusDockerDesktopOneShot /TR <bat that "start"s Docker Desktop> /SC ONCE /ST 23:59 /RL HIGHEST /RU "BROOKFIELD_PC\lilly" /IT /F
schtasks /Run /TN NexusDockerDesktopOneShot
# poll: docker version --format '{{.Server.Version}}' until non-empty

# 3. .env refresh
powershell -ExecutionPolicy Bypass -File C:\dev\project-nexus\scripts\setup\refresh-tailscale-bind.ps1 -EnvPath C:\dev\project-nexus\docker\.env

# 4. Compose (scheduled task as lilly, see Section 5.2)
schtasks /Create /TN NexusComposeUp /TR <ps wrapper that runs docker compose up -d --build> /SC ONCE /ST 23:59 /RL HIGHEST /RU "BROOKFIELD_PC\lilly" /IT /F
schtasks /Run /TN NexusComposeUp
# poll: presence of C:\dev\_resume_4070\compose_up.done

# 5. Verify from the 4090
ping 100.89.210.52
Invoke-WebRequest http://100.89.210.52:5001/health -UseBasicParsing
```

The authkey itself should never be logged, never written to a committed file, and only ever read from `C:\dev\_secrets\tailscale_auth_token.local.txt` at the moment of use.

## 8. Known sharp edges

1. The Tailscale GUI binding race (Phase 1) and the Docker Desktop session-binding (Phases 2 and 4) are both consequences of Windows tying user-mode services to the user that opened them. Anything we drive from SSH-as-drama that needs an interactive desktop will hit this same wall. The scheduled-task-as-lilly pattern in this PR is the workaround. A cleaner long-term answer is either to put the 4070 fully headless under a SYSTEM-mode Docker (Windows containers) or to set the relevant services to auto-start at logon for a permanently-logged-on operator account.
2. `refresh-tailscale-bind.ps1` has the `$PSScriptRoot`-empty-on-`-File` bug noted in Section 4.3. Not fatal once you know to pass `-EnvPath`, but worth one line of repair in a follow-up.
3. The Tailscale "set network category to private" health warning on Windows is cosmetic on this build (1.98.4 on Windows 10.0.26200) but is the kind of warning that becomes load-bearing on a later Tailscale release. Worth keeping an eye on if the fabric goes flaky.
4. Docker Desktop 4.50.0 sometimes shows `wsl --list --verbose` reporting `docker-desktop` as Stopped while the engine is actually running under Hyper-V isolation. Reading WSL state alone is not a reliable Docker-up indicator. Use `docker version --format '{{.Server.Version}}'` as the truth.

## 9. References

- `NEXUS_STATE_AUDIT_2026-06-16.md`: section 4 "Active blockers", items 1 and 3.
- `docs/sprints/SPRINT_3d_PLAN_2026-06-18.md`: Card 2 specification.
- `docs/sprints/SPRINT_3d_INTEGRATION_RESULTS_2026-06-18.md`: Card 3 hermetic results (the PR this builds on).
- `docs/exposure_and_cortex_down.md`: original Sprint 3c design that the Tailscale-only bind implements.
- `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md`: the manual test plan now unblocked by Section 6.
- `scripts/setup/refresh-tailscale-bind.ps1`: the .env refresher invoked in Phase 3.
- `docker/docker-compose.yml`, `docker/brainstem.Dockerfile`, `docker/nas.Dockerfile`, `docker/embedder.Dockerfile`: the build inputs.
