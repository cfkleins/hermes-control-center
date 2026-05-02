param(
  [string]$TaskName = 'CustomWebUI-RepairPolicyTick',
  [ValidateSet('DAILY','HOURLY')][string]$Cadence = 'DAILY',
  [string]$At = '03:10',
  [int]$EveryHours = 6,
  [string]$WslDistro = '',
  [string]$ProjectPathWsl = '/mnt/c/Users/cfkle/custom-web-ui',
  [string]$BaseUrl = 'http://127.0.0.1:8000',
  [string]$Username = 'admin',
  [string]$Pin = '',
  [switch]$Force,
  [switch]$RunNow
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Pin)) {
  throw 'Pin is required. Pass -Pin <PIN>.'
}

$wslPrefix = if ([string]::IsNullOrWhiteSpace($WslDistro)) { '' } else { "-d $WslDistro " }
$forceVal = if ($Force) { 'true' } else { 'false' }

$bashCmd = @"
cd '$ProjectPathWsl' && \
CUSTOM_UI_BASE_URL='$BaseUrl' \
CUSTOM_UI_USERNAME='$Username' \
CUSTOM_UI_PIN='$Pin' \
CUSTOM_UI_FORCE='$forceVal' \
python3 scripts/run_repair_policy_tick.py
"@

$arguments = "${wslPrefix}-e bash -lc \"$bashCmd\""
$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument $arguments

if ($Cadence -eq 'DAILY') {
  $trigger = New-ScheduledTaskTrigger -Daily -At $At
} else {
  $startBoundary = (Get-Date).AddMinutes(2)
  $trigger = New-ScheduledTaskTrigger -Once -At $startBoundary -RepetitionInterval (New-TimeSpan -Hours $EveryHours) -RepetitionDuration ([TimeSpan]::MaxValue)
}

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Installed/updated task: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath | Format-List

if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName
  Start-Sleep -Seconds 2
}

Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
