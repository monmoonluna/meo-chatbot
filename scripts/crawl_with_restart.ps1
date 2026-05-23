# Auto-restart wrapper for crawler -- handles silent OS kills (Defender etc).
#
# Usage:
#   .\scripts\crawl_with_restart.ps1 mochicat
#   .\scripts\crawl_with_restart.ps1 mochicat 2480
#
# Crawler is idempotent: each restart skips cached files.

param(
    [Parameter(Mandatory=$true)]
    [string]$Source,

    [int]$TargetCount = 0,

    [int]$MaxRestarts = 50
)

$root = Split-Path $PSScriptRoot -Parent
$rawDir = Join-Path $root "data\raw\$Source"
$logFile = Join-Path $root "data\crawl-restart-$Source.log"

function Get-Count {
    if (Test-Path $rawDir) {
        return (Get-ChildItem $rawDir -Filter *.json -ErrorAction SilentlyContinue).Count
    }
    return 0
}

$restartNum = 0

while ($restartNum -lt $MaxRestarts) {
    $restartNum++
    $startCount = Get-Count
    $startTime = Get-Date

    Write-Host ""
    Write-Host "================================================================"
    Write-Host "  [Restart $restartNum] $Source -- starting (currently $startCount files)"
    Write-Host "================================================================"

    Push-Location $root
    & .\.venv\Scripts\python.exe -u -m crawler.crawl --source $Source 2>&1 | Tee-Object -Append $logFile
    $exitCode = $LASTEXITCODE
    Pop-Location

    $endCount = Get-Count
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $added = $endCount - $startCount

    Write-Host ""
    Write-Host "  Run $restartNum done: exit=$exitCode, elapsed=${elapsed}s, +$added files (total=$endCount)"

    if ($TargetCount -gt 0 -and $endCount -ge $TargetCount) {
        Write-Host "  [OK] Reached target $TargetCount"
        break
    }

    if ($added -eq 0 -and $elapsed -gt 60) {
        Write-Host "  [OK] No new files added -- likely complete"
        break
    }

    if ($elapsed -lt 30) {
        Write-Host "  [WARN] Crashed in <30s, sleep 30s before retry..."
        Start-Sleep -Seconds 30
    } else {
        Write-Host "  Waiting 5s before next restart..."
        Start-Sleep -Seconds 5
    }
}

Write-Host ""
Write-Host "Done. Final: $(Get-Count) files in $rawDir after $restartNum restarts."
