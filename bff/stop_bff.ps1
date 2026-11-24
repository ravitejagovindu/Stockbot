# Stop the StockBot paper BFF: only the python process whose command line is "bff\run.py". Nothing else is touched (not the scheduler service, not a job).
#
#   powershell -ExecutionPolicy Bypass -File F:\Projects\Ravi\StockBot\bff\stop_bff.ps1
#
# Exit codes: 0 stopped (or nothing was running), 1 a BFF process could not be stopped.
$ErrorActionPreference = 'Stop'
$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'bff\\run\.py' })
if (-not $procs) { Write-Output 'The BFF is not running.'; exit 0 }
$failed = $false
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force; Write-Output "Stopped the BFF (pid $($p.ProcessId))." }
    catch { Write-Output "Could not stop pid $($p.ProcessId): $($_.Exception.Message)"; $failed = $true }
}
if ($failed) { exit 1 }
exit 0
