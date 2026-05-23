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

function Get-ChromaCount {
    $out = & $py -c "import chromadb; print(chromadb.PersistentClient(r'$root\data\chromadb').get_collection('meo_kb').count())" 2>$null
    if ($out -match '^\d+$') { return [int]$out }
    return -1
}

function Get-TotalChunks {
    $f = Join-Path $root "data\chunks\classified.jsonl"
    return (Get-Content $f | Measure-Object -Line).Lines
}

$target = Get-TotalChunks
$maxRestarts = 20

Add-Content -Path $summary -Value "`n[$([DateTime]::Now.ToString('HH:mm:ss'))] finish_pipeline.ps1 started (target=$target)"

# ---------- Ingest loop ----------
$restartNum = 0
while ($restartNum -lt $maxRestarts) {
    $restartNum++
    $startCount = Get-ChromaCount
    $startTime = Get-Date

    Write-Host ""
    Write-Host "================================================================"
    Write-Host "  [Ingest restart $restartNum] $startCount / $target chunks"
    Write-Host "================================================================"

    Push-Location $root
    & $py -u -m pipeline.ingest *>> $logFile
    $exitCode = $LASTEXITCODE
    Pop-Location

    $endCount = Get-ChromaCount
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $added = $endCount - $startCount

    Write-Host ""
    Write-Host "  Run $restartNum done: exit=$exitCode, elapsed=${elapsed}s, +$added chunks (total=$endCount/$target)"
    Add-Content -Path $summary -Value "  [Ingest run $restartNum] +$added -> $endCount/$target (exit=$exitCode, ${elapsed}s)"

    if ($endCount -ge $target) {
        Write-Host "  [OK] Reached target $target"
        break
    }

    if ($added -le 0 -and $elapsed -gt 60) {
        Write-Host "  [WARN] No progress in this run, stopping"
        break
    }

    if ($elapsed -lt 30) {
        Write-Host "  [WARN] Crashed in <30s, sleep 30s..."
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
Add-Content -Path $summary -Value "[$([DateTime]::Now.ToString('HH:mm:ss'))] ALL DONE. ChromaDB=$(Get-ChromaCount) / $target"
Get-Content $summary -Tail 20
