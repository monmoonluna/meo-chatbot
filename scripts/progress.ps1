# Hiển thị progress crawl. Chạy bất cứ lúc nào:
#   .\scripts\progress.ps1
$root = Split-Path $PSScriptRoot -Parent
$targets = [ordered]@{
    pethealth      = 130
    mozzi          = 44
    paddy          = 367
    tropicpet      = 539
    champetsfamily = 332
    # Phase 2 — behavior-focused
    petspace       = 25
    petthings      = 82
    kingspet       = 393
    fagopet        = 400
    mochicat       = 2483
}

Write-Host "`n=== Crawl progress ===`n"
$totalDone = 0
$totalTarget = 0
foreach ($s in $targets.Keys) {
    $dir = Join-Path $root "data\raw\$s"
    $n = if (Test-Path $dir) { (Get-ChildItem $dir -Filter *.json).Count } else { 0 }
    $t = $targets[$s]
    $pct = [Math]::Round($n / $t * 100)
    $filled = [Math]::Floor($pct / 5)
    $bar = ('#' * $filled) + ('.' * (20 - $filled))
    $line = "{0,-17}[{1}] {2,3}/{3,-4} {4,3}%" -f $s, $bar, $n, $t, $pct
    Write-Host $line
    $totalDone += $n
    $totalTarget += $t
}

$totalPct = [Math]::Round($totalDone / $totalTarget * 100)
Write-Host ""
Write-Host "TOTAL: $totalDone/$totalTarget ($totalPct%)"

$log = Join-Path $root "data\crawl.log"
if (Test-Path $log) {
    Write-Host "`nLast 3 lines of log:"
    Get-Content $log -Tail 3 -Encoding UTF8
}
