# Windows Application Discovery and Launch

## Use when
The user asks to open an application, asks where an app is installed, says an app is installed but the agent cannot find it, or asks to start a Windows utility.

## Required behavior
1. Load the `shell` tool with `get_tool("shell")` if it is not available.
2. Identify the exact application name from the user's request. Do not assume the executable name or default install directory.
3. Discover in this order, using the least expensive method first:
   - Check whether a matching process is already running and inspect its executable path when available.
   - Query Start-menu registrations with `Get-StartApps -Name '*name*'`.
   - Check the current-user and machine `App Paths` registry locations and the application's own known registry registration.
   - Inspect likely Start Menu/Desktop shortcuts and common install roots.
   - Try a documented URI/protocol handler when the app has one and it is relevant.
   - Search additional drives only if the earlier approaches fail; limit the search to likely directories first.
4. Validate every discovered executable or shortcut before launching it. Do not treat one missing default path as proof the app is not installed.
5. Launch through the app's registered shortcut, verified executable, or registered protocol handler. Prefer the normal launcher over running an arbitrary file found under a game or application folder.
6. Verify separately: whether a process started, whether the executable path is known, and whether a visible window is confirmed. The current agent does not have native window enumeration, so do not claim the visible-window part is verified unless an appropriate tool is added.

## Discovery examples
Read-only PowerShell queries can include:

```powershell
Get-StartApps -Name '*steam*' | Select-Object Name, AppID
Get-Process -Name '*steam*' -ErrorAction SilentlyContinue |
    Select-Object ProcessName, Id, Path
Get-Command steam.exe -ErrorAction SilentlyContinue |
    Select-Object Name, Source
```

Adapt the search term to the app. These examples are discovery, not a universal launch command.

For registered applications, inspect both current-user and machine App Paths entries when appropriate. A missing result from one registry hive is not proof that no installation exists.

## Launching
- For a known, user-requested application, use its verified shortcut, registered AppID, executable path, or protocol.
- `Start-Process` returning is only evidence that Windows accepted the launch request. Verify by checking the relevant process, and report if visible-window verification is unavailable.
- Do not install, update, run as administrator, accept an installer prompt, or disable security controls unless explicitly requested and approved.
- If more than one app matches (for example, multiple editors or versions), show concise candidates instead of guessing.

## Common folders
To open the user's Downloads folder, prefer the Windows shell namespace rather than assuming Downloads is physically under the profile:

```powershell
Start-Process -FilePath 'explorer.exe' -ArgumentList 'shell:Downloads'
```

This is a proposed action to test on the current PC, not proof that it worked. Do not confuse `shell:Personal` with Downloads; it represents Documents.

## Failure report
State the real result, for example: “Start-menu entry found, launch attempted, process not observed.” Never report “security policy blocked it” unless the tool returns evidence supporting that exact explanation.
