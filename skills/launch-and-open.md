# launch-and-open

Use for "open <app>", "open my <folder>", "launch <game>". One command first. No Test-Path preamble.

Prefer the typed tools: `open_known_folder` for folders, `launch_app` for
Steam/Discord, `find_app` for discovery. The PowerShell below is the
fallback when a typed tool cannot do the job.

## Folders (one command, no $env: paths)
See `windows-system.md` (folder map) and `file-operations.md` for the full
procedure. In short: `Start-Process explorer.exe shell:Downloads` for
Downloads, `shell:Personal` for Documents, `shell:Desktop` for Desktop,
`shell:My Pictures` for Pictures. If Downloads may be relocated, resolve
it first:
`(New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path`

## Apps (order matters)
See `windows-apps.md` for the full discovery procedure. In short:
1. Protocol handler, no path needed: Steam: `Start-Process "steam://open/main"`
2. Start Menu entry: `Get-StartApps | Where-Object Name -like '*<name>*'`, then `Start-Process "shell:AppsFolder\<AppID>"`
3. Registry (Steam): `(Get-ItemProperty 'HKCU:\Software\Valve\Steam').SteamExe`
4. Disk search only as a last resort, and only inside likely folders.

## Notes
- Success = the command returned without an error. Do not run a second command just to "verify" a launch.
- If a command comes back "Blocked by safety rule", follow honest-failure. The block is about the command text, not the app.
- Prefer typed tools (open_known_folder, launch_app) when they exist.
