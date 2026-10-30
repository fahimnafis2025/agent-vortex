# launch-games

Use for "open <game>", "what games do I have", "launch <game> on Steam/Epic".

See `windows-games.md` for the full strategy. The Steam specifics below are
the parts that skill does not spell out.

## Steam
1. Steam folder: `(Get-ItemProperty 'HKCU:\Software\Valve\Steam').SteamPath`
2. Library folders: `Get-Content "<SteamPath>\steamapps\libraryfolders.vdf" | Select-String '"path"'`
3. Installed games per library (name + appid):
   `Get-ChildItem "<library>\steamapps" -Filter appmanifest_*.acf | ForEach-Object { $t = Get-Content $_.FullName -Raw; [pscustomobject]@{AppId=[regex]::Match($t,'"appid"\s+"(\d+)"').Groups[1].Value; Name=[regex]::Match($t,'"name"\s+"([^"]+)"').Groups[1].Value} }`
4. Launch: `Start-Process "steam://rungameid/<AppId>"`
5. Only Steam itself: `Start-Process "steam://open/main"` (or the typed tool `launch_app("steam")`)

## Epic Games
- Manifests: `C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item` (JSON: DisplayName, InstallLocation, AppName)
- Launch: `Start-Process "com.epicgames.launcher://apps/<AppName>?action=launch&silent=true"`
- Verify the exact URI form once on this PC before relying on it.

## Rules
- Match the game by name from the manifest list. If 2+ names match, list them and ask once.
- Games may live on a second drive. Always read libraryfolders.vdf instead of assuming C:\.
- Launching a game is an "opens something" action. Do not run a pre-check first.
