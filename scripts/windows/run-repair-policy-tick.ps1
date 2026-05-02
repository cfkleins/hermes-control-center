# Run from elevated Task Scheduler action:
# Program/script: wsl.exe
# Add arguments: -e bash -lc "cd /mnt/c/Users/cfkle/custom-web-ui && CUSTOM_UI_PIN='<PIN>' python3 scripts/run_repair_policy_tick.py"

$ErrorActionPreference = 'Stop'
wsl.exe -e bash -lc "cd /mnt/c/Users/cfkle/custom-web-ui && python3 scripts/run_repair_policy_tick.py"