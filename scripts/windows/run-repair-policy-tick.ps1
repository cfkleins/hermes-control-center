param(
  [string]$WslDistro = '',
  [string]$ProjectPathWsl = '/mnt/c/Users/cfkle/custom-web-ui',
  [string]$BaseUrl = 'http://127.0.0.1:8000',
  [string]$Username = 'admin',
  [string]$Pin = '',
  [switch]$Force
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

wsl.exe ${wslPrefix}-e bash -lc "$bashCmd"
