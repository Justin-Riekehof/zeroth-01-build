#Requires -Version 5.1
<#
One-command deploy of the Pi intent service to the robot.

    .\src\pi_service\deploy\deploy_pi.ps1                 # full deploy
    .\src\pi_service\deploy\deploy_pi.ps1 -SkipService    # code only, no sudo

Ships zbot_core + pi_service + calibration (servo_ids/joint_limits/
joint_offsets) + demos to justin@pixel.local:~/zbot, installs both packages
editable into ~/venv, refreshes the systemd unit and health-checks /status.
connection.json is deliberately NOT shipped: it is host-specific — the Pi
falls back to port "auto" until you pin /dev/serial/by-id/... there.
#>
param(
    [string]$PiHost = "justin@pixel.local",
    [switch]$SkipService
)

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

Step "staging (source + calibration + demos, no venvs)"
$Stage = Join-Path $env:TEMP "zbot_deploy_stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force "$Stage\src" | Out-Null
Copy-Item -Recurse (Join-Path $RepoRoot "src\zbot_core") "$Stage\src\zbot_core"
Copy-Item -Recurse (Join-Path $RepoRoot "src\pi_service") "$Stage\src\pi_service"
Get-ChildItem $Stage -Recurse -Force -Directory |
    Where-Object { $_.Name -in ".venv", "__pycache__", ".pytest_cache" } |
    Remove-Item -Recurse -Force
New-Item -ItemType Directory -Force "$Stage\hardware" | Out-Null
foreach ($f in "servo_ids.json", "joint_limits.json", "joint_offsets.json") {
    $p = Join-Path $RepoRoot "hardware\$f"
    if (Test-Path $p) { Copy-Item $p "$Stage\hardware\$f" }
}
Copy-Item -Recurse (Join-Path $RepoRoot "demos") "$Stage\demos"

$Tgz = Join-Path $env:TEMP "zbot_deploy.tgz"
if (Test-Path $Tgz) { Remove-Item -Force $Tgz }
tar -czf $Tgz -C $Stage src hardware demos
if ($LASTEXITCODE -ne 0) { Fail "tar failed" }

Step "copying to ${PiHost}:/tmp"
scp -q $Tgz "${PiHost}:/tmp/zbot_deploy.tgz"
if ($LASTEXITCODE -ne 0) {
    Fail ("scp failed - robot off, or ProtonVPN blocking LAN " +
          "(enable 'Allow LAN connections')?")
}

Step "unpacking to ~/zbot + installing into ~/venv"
ssh $PiHost ("mkdir -p ~/zbot && tar -xzf /tmp/zbot_deploy.tgz -C ~/zbot && " +
    "rm /tmp/zbot_deploy.tgz && " +
    "~/venv/bin/pip install -q -e ~/zbot/src/zbot_core -e ~/zbot/src/pi_service")
if ($LASTEXITCODE -ne 0) { Fail "remote install failed" }

if ($SkipService) {
    Step "done (systemd step skipped)"
    exit 0
}

Step "systemd unit install/restart (may prompt for the sudo password)"
ssh -t $PiHost ("sudo install -m 644 " +
    "~/zbot/src/pi_service/deploy/zbot-pi.service " +
    "/etc/systemd/system/zbot-pi.service && " +
    "sudo systemctl daemon-reload && sudo systemctl enable --now zbot-pi && " +
    "sudo systemctl restart zbot-pi")
if ($LASTEXITCODE -ne 0) {
    Fail "systemd step failed (use -SkipService to deploy code only)"
}

Start-Sleep -Seconds 2
Step "health check"
ssh $PiHost "curl -s http://localhost:8460/status"
if ($LASTEXITCODE -ne 0) {
    Fail "service not answering - inspect: ssh $PiHost journalctl -u zbot-pi -n 50"
}
Write-Host ""
Step "done - service at http://pixel.local:8460 (GET /status)"
