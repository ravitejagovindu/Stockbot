# Start the StockBot paper BFF in a NEW detached, minimized window (like the scheduler service). Read-only service; safe to kill at any time.
#
#   powershell -ExecutionPolicy Bypass -File F:\Projects\Ravi\StockBot\bff\start_bff.ps1
#
# It finds the laptop's Tailscale IPv4 address and MagicDNS name itself, binds ONLY to that address (never all interfaces), allows the Host headers
# <tailscale ip>, <magicdns name>, localhost, 127.0.0.1, and refuses to start a second copy. The token is read by run.py from STOCKBOT_BFF_TOKEN or
# F:\Projects\Ravi\StockBotData\bff\token.txt; this script never reads or prints it.
# Exit codes: 0 started (or printed the running one's details with -Status), 1 Tailscale missing/not running, 2 already running, 3 port in use, 4 did not come up.
param([switch]$Status)

$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe'
$ts     = 'C:\Program Files\Tailscale\tailscale.exe'
$port   = if ($env:STOCKBOT_BFF_PORT) { $env:STOCKBOT_BFF_PORT } else { '8765' }

function Get-BffProcess {
    Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'bff\\run\.py' }
}

$running = @(Get-BffProcess)
if ($Status) {
    if ($running) { $running | ForEach-Object { "running: pid $($_.ProcessId)" } } else { 'not running' }
    exit 0
}
if ($running) {
    Write-Output "REFUSED: the BFF is already running (pid $(($running | ForEach-Object { $_.ProcessId }) -join ', ')). Stop it first with stop_bff.ps1."
    exit 2
}

if (-not (Test-Path $ts)) { Write-Output 'REFUSED: tailscale.exe not found.'; exit 1 }
$ip = (& $ts ip -4 2>$null | Select-Object -First 1)
if (-not $ip -or $ip -notmatch '^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}$') {
    Write-Output 'REFUSED: Tailscale has no IPv4 address (is Tailscale running and signed in?).'
    exit 1
}
$ip = $ip.Trim()
$dns = ''
try { $dns = ((& $ts status --json | ConvertFrom-Json).Self.DNSName).TrimEnd('.') } catch { }

if (Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "REFUSED: port $port is already in use by another program (set STOCKBOT_BFF_PORT to a free port)."
    exit 3
}

$hosts = @($ip)
if ($dns) { $hosts += $dns }
$hosts += @('localhost', '127.0.0.1')
$env:STOCKBOT_BFF_HOST          = $ip
$env:STOCKBOT_BFF_PORT          = $port
$env:STOCKBOT_BFF_ALLOWED_HOSTS = ($hosts -join ',')

$p = Start-Process -FilePath $python -ArgumentList 'bff\run.py' -WorkingDirectory $repo -WindowStyle Minimized -PassThru
for ($i = 0; $i -lt 40; $i++) {                      # run.py loads the signal-day function first (about 10 s)
    Start-Sleep -Milliseconds 1000
    if ($p.HasExited) { Write-Output "FAILED: run.py exited with code $($p.ExitCode) (no token? see its window output)."; exit 4 }
    if (Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue) { break }
}
if (-not (Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue)) { Write-Output 'FAILED: the BFF did not start listening.'; exit 4 }
Write-Output "STARTED: pid $($p.Id)  http://${ip}:${port}  (allowed hosts: $($hosts -join ', '))  log: F:\Projects\Ravi\StockBotData\logs\bff.log"
exit 0
