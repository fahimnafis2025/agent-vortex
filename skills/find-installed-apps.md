# find-installed-apps

Use when you need an app's launch method or location. Stop at the first method that works.

Prefer the typed tool `find_app(name)` — it runs methods 1–4 below
deterministically. The PowerShell is the fallback.

1. Start Menu / Store apps (best, gives a launchable ID) — see `windows-apps.md`:
   `Get-StartApps | Where-Object Name -like '*NAME*'`
   Launch: `Start-Process "shell:AppsFolder\<AppID>"`
2. Already on PATH:
   `Get-Command NAME -ErrorAction SilentlyContinue | Select Source`
3. App Paths registry (many desktop apps) — see `windows-apps.md`:
   `(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\NAME.exe').'(default)'`
4. Installed-programs registry (gives InstallLocation):
   `Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*,HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*,HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue | Where-Object DisplayName -like '*NAME*' | Select-Object DisplayName, InstallLocation`
5. Last resort: search likely folders only (Program Files, Program Files (x86), %LOCALAPPDATA%\Programs, E:\ top level). Never search all of C:\ in one command: it exceeds the shell time limit.

## Notes
- "Not found by method 1" does not mean "not installed". Try the next method.
- Only say an app is missing after methods 1-4 all came back empty, and list what you tried.
- Portable apps may not appear anywhere. Ask the user for the folder.
