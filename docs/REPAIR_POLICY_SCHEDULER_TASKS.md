# Repair Policy Scheduler Tasks (Windows + WSL)

This sets up a recurring Windows Task Scheduler job that runs the WSL tick script:

- Python runner: `scripts/run_repair_policy_tick.py`
- Endpoint called: `POST /api/llm-wikis/lint/repair-report/policy/tick`

## 1) Install or update task (recommended)

Run in **elevated PowerShell**:

```powershell
cd C:\Users\cfkle\custom-web-ui\scripts\windows
.\install-repair-policy-tick-task.ps1 -Pin '<PIN>' -Cadence DAILY -At '03:10'
```

Optional hourly mode:

```powershell
.\install-repair-policy-tick-task.ps1 -Pin '<PIN>' -Cadence HOURLY -EveryHours 6
```

Optional distro targeting:

```powershell
.\install-repair-policy-tick-task.ps1 -Pin '<PIN>' -WslDistro 'Ubuntu'
```

## 2) Manual run

```powershell
Start-ScheduledTask -TaskName 'CustomWebUI-RepairPolicyTick'
Get-ScheduledTaskInfo -TaskName 'CustomWebUI-RepairPolicyTick'
```

## 3) Verify output path

The task executes:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/cfkle/custom-web-ui && python3 scripts/run_repair_policy_tick.py"
```

The script prints JSON with run counts and per-wiki results.

## 4) Troubleshooting

- `LastTaskResult != 0`: open Task Scheduler history and verify WSL distro + path.
- If web service just restarted, first tick can fail transiently; rerun task.
- Confirm service health from WSL:

```bash
curl -fsS http://127.0.0.1:8000/api/health
```

## 5) Remove task

```powershell
Unregister-ScheduledTask -TaskName 'CustomWebUI-RepairPolicyTick' -Confirm:$false
```
