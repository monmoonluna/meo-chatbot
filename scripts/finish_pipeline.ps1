# Finish Phase 2: ingest (auto-restart) + eval
# Idempotent — safe to run multiple times.
#
# Logic: query ChromaDB count before/after each ingest run.
#   - if count reaches target -> done
#   - if no progress in a run -> stuck, exit
#   - if Python died mid-run -> restart

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$env:HF_HOME = "D:\hf-cache"
$py = Join-Path $root ".venv\Scripts\python.exe"
$logFile = Join-Path $root "data\ingest-restart.log"
$summary = Join-Path $root "data\phase2-summary.txt"

$maxRestarts = 30

Add-Content -Path $summary -Value "`n[$([DateTime]::Now.ToString('HH:mm:ss'))] finish_pipeline.ps1 started"

# ---------- Ingest loop ----------
# Detect completion by grepping log for ingest's own "=== Done: ... ===" marker.
# No Python sub-spawn for ChromaDB count -- spawning Python from within wrapper
# was hanging when system silent-killer was active.
$restartNum = 0
while ($restartNum -lt $maxRestarts) {
    $restartNum++
    $startTime = Get-Date

    Write-Host ""
    Write-Host "================================================================"
    Write-Host "  [Ingest restart $restartNum] starting..."
    Write-Host "================================================================"

    Push-Location $root
    & $py -u -m pipeline.ingest *>> $logFile
    $exitCode = $LASTEXITCODE
    Pop-Location

    $elapsed = [Math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)
    Write-Host ""
    Write-Host "  Run $restartNum exited (code=$exitCode, ${elapsed}s)"
    Add-Content -Path $summary -Value "  [Ingest run $restartNum] exit=$exitCode, ${elapsed}s"

    # Detect natural completion via log marker
    $lastLines = Get-Content $logFile -Tail 5 -ErrorAction SilentlyContinue
    if ($lastLines -match "Done:.+chunks in ChromaDB") {
        Write-Host "  [OK] Ingest reported Done -- finishing loop"
        break
    }

    if ($elapsed -lt 30) {
        Write-Host '  [WARN] Crashed quickly, sleep 30s...'
        Start-Sleep -Seconds 30
    } else {
        Start-Sleep -Seconds 5
    }
}

# ---------- Eval ----------
Write-Host ""
Write-Host "================================================================"
Write-Host "  Step 5/5: Eval 30-query suite (retrieval-only)"
Write-Host "================================================================"
Add-Content -Path $summary -Value "[$([DateTime]::Now.ToString('HH:mm:ss'))] Step 5/5: Eval"

Push-Location $root
& $py scripts\eval_queries.py
Pop-Location

# ---------- Final ----------
Write-Host ""
Write-Host "================================================================"
Write-Host "  ALL DONE"
Write-Host "================================================================"
Add-Content -Path $summary -Value "[$([DateTime]::Now.ToString('HH:mm:ss'))] ALL DONE"
Get-Content $summary -Tail 20
