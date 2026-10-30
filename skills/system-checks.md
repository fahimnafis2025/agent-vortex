# system-checks

Read-only status checks. Run, read, answer in one or two lines.

- Disk space:
  `Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}`
- Top memory users:
  `Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 Name, @{n='MB';e={[int]($_.WorkingSet64/1MB)}}`
- Top CPU users (cumulative CPU seconds, not live %):
  `Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 Name, CPU`
- Uptime:
  `(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime`
- GPU (NVIDIA):
  `nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv`
- Network addresses:
  `Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress`
- Internet reachable:
  `Test-Connection 1.1.1.1 -Count 1 -Quiet`
- Defender status:
  `Get-MpComputerStatus | Select-Object AntivirusEnabled, AntivirusSignatureLastUpdated, RealTimeProtectionEnabled`
- Windows Update pending (can take over a minute, needs a longer timeout) — prefer the typed tool `windows_update_status()`:
  `$r = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0"); "$($r.Updates.Count) pending"; $r.Updates | ForEach-Object Title`

## Rules
- Report numbers exactly as returned. Do not round up or guess.
- CPU temperature is not available from these commands. Say so instead of estimating.
- Starting a Defender scan (Start-MpScan) changes state. Ask first.
