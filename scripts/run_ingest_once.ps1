# Single-shot ingest runner -- called by Windows Task Scheduler.
# Scheduler retriggers every 10 min; this script:
#   - skips if Python already running (avoid overlap)
#   - skips if ChromaDB has reached target count (done)
#   - otherwise runs one pipeline.ingest pass

$root = "D:\other\cat\meo-chatbot"
$env:HF_HOME = "D:\hf-cache"
$py = "$root\.venv\Scripts\python.exe"
$log = "$root\data\scheduler.log"
$target = 75264

function Log-Msg {
    param([string]$Msg)
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg" | Out-File -FilePath $log -Append -Encoding UTF8
}

# Skip if a Python is already busy (avoid concurrent ingest)
if (Get-Process python -ErrorAction SilentlyContinue) {
    Log-Msg "Python already running, skipping this tick"
    exit 0
}

# Check ChromaDB count -- skip if already done
$count = & $py -c "import chromadb; print(chromadb.PersistentClient(r'$root\data\chromadb').get_collection('meo_kb').count())" 2>$null
if (-not ($count -match '^\d+$')) {
    Log-Msg "Could not read ChromaDB count, aborting"
    exit 1
}
$count = [int]$count

if ($count -ge $target) {
    Log-Msg "Done: $count >= $target chunks. Scheduler can be removed."
    exit 0
}

# Run one ingest pass
Log-Msg "Starting ingest pass (current=$count / target=$target)"
Push-Location $root
& $py -u -m pipeline.ingest *>> "$root\data\ingest-restart.log"
$exitCode = $LASTEXITCODE
Pop-Location

# Re-check count after run
$newCount = & $py -c "import chromadb; print(chromadb.PersistentClient(r'$root\data\chromadb').get_collection('meo_kb').count())" 2>$null
if ($newCount -match '^\d+$') {
    $added = [int]$newCount - $count
    Log-Msg "Ingest finished (exit=$exitCode), +$added chunks, now $newCount / $target"
} else {
    Log-Msg "Ingest finished (exit=$exitCode), could not re-read count"
}
