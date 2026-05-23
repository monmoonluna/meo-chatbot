# Full Phase 2 pipeline: crawl (auto-restart) -> chunk -> classify -> ingest -> eval
# Can run unattended; safe to relaunch (every step is idempotent).
#
# Usage:
#   .\scripts\run_phase2_pipeline.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$env:HF_HOME = "D:\hf-cache"
$py = Join-Path $root ".venv\Scripts\python.exe"
$summary = Join-Path $root "data\phase2-summary.txt"

function Log-Step {
    param([string]$Title)
    Write-Host ""
    Write-Host ""
    Write-Host "################################################################"
    Write-Host "  $Title"
    Write-Host "################################################################"
    Add-Content -Path $summary -Value "`n[$([DateTime]::Now.ToString('HH:mm:ss'))] $Title"
}

Add-Content -Path $summary -Value "==== Phase 2 pipeline started: $([DateTime]::Now) ===="

# ---------- Step 1: Crawl with auto-restart ----------
Log-Step "Step 1/5: Crawl mochicat (auto-restart wrapper)"
& "$PSScriptRoot\crawl_with_restart.ps1" -Source mochicat -TargetCount 2480

$crawlCount = (Get-ChildItem (Join-Path $root "data\raw\mochicat") -Filter *.json -ErrorAction SilentlyContinue).Count
Add-Content -Path $summary -Value "  mochicat raw files: $crawlCount"

# ---------- Step 2: Chunker (dedupe URLs) ----------
Log-Step "Step 2/5: Chunk all sources"
Push-Location $root
& $py -m pipeline.chunker --source all
Pop-Location

# ---------- Step 3: Classifier ----------
Log-Step "Step 3/5: Classify metadata"
Push-Location $root
& $py -m pipeline.classifier
Pop-Location

# ---------- Step 4: Ingest (incremental) ----------
Log-Step "Step 4/5: Ingest to ChromaDB (incremental: embed new + update metadata)"
Push-Location $root
& $py -m pipeline.ingest
Pop-Location

# ---------- Step 5: Eval (retrieval-only, no quota burn) ----------
Log-Step "Step 5/5: Eval 30-query suite (retrieval-only)"
Push-Location $root
& $py scripts\eval_queries.py
Pop-Location

# ---------- Final summary ----------
Log-Step "DONE"
Add-Content -Path $summary -Value "==== Phase 2 pipeline finished: $([DateTime]::Now) ===="
Write-Host ""
Write-Host "Full summary log: $summary"
Get-Content $summary -Tail 30
