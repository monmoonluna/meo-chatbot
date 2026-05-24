# Register Windows Task Scheduler entry that runs ingest every 10 minutes.
# Per-user task, no admin needed.
#
# To verify:    Get-ScheduledTask -TaskName "MeoBotIngest"
# To check log: Get-Content D:\other\cat\meo-chatbot\data\scheduler.log -Tail 10
# To remove:    Unregister-ScheduledTask -TaskName "MeoBotIngest" -Confirm:$false

$taskName = "MeoBotIngest"
$scriptPath = "D:\other\cat\meo-chatbot\scripts\run_ingest_once.ps1"

# Cleanup any existing task with same name
Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Hours 24)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Auto-run ingest for meo-chatbot every 10 minutes (resilient to OS process kills)"

Write-Host ""
Write-Host "================================================================"
Write-Host "  Scheduled task '$taskName' registered."
Write-Host "  - First run: in 1 minute"
Write-Host "  - Repeat: every 10 minutes"
Write-Host "  - Duration: 24 hours"
Write-Host "  - Max runtime per instance: 30 minutes"
Write-Host "================================================================"
Write-Host ""
Write-Host "Verify status:"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
