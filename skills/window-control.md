# Window Control: Focus, Minimize, Maximize, Restore, Close

## Critical capability check
v14.5 added typed native desktop tools: `list_windows`, `focus_window`,
`close_window`, `desktop_screenshot` (via pywinauto + mss). USE THEM.
The browser tools still control only the agent's Playwright browser page.

Do not pretend a general window action succeeded unless a real
window-control tool ran and its result is verified.

## If native window tools are available
1. Enumerate visible top-level windows with title, process name, PID, handle, visibility and minimized state (`list_windows`).
2. Match the user’s target against window title and application. If there are several plausible matches, show candidates rather than guessing.
3. For focus/minimize/maximize/restore, act on the matched window handle and re-read state afterward.
4. For close, send a graceful close request first. Detect and report save prompts or confirmation dialogs; never auto-discard unsaved work.
5. Force termination is a separate, higher-impact action requiring explicit authorization. Never silently substitute it for a normal close.
6. Record the target window and result so the agent can say precisely what changed.

## With the current tools only
- `browser_close` means close the agent's browser; it does not close Steam, Discord, a game, Explorer, or another app. Use `close_window` for that.
- Do not send a blind `Alt+F4`/`SendKeys` to whichever window happens to be active. It may close the wrong app or discard work.
- Do not use `Stop-Process -Force` just because the user says “close that window.” A process may own several windows or contain unsaved state.
- If a native window-control tool fails, explain the precise limitation briefly. Do not invent a security-policy explanation.

## PowerShell fallback (from Claude's review — only when the typed tools are unavailable)
- See what is open: `Get-Process | Where-Object MainWindowTitle | Select-Object Id, ProcessName, MainWindowTitle`
- Gentle close: `(Get-Process -Name NAME | Where-Object MainWindowHandle -ne 0).CloseMainWindow()` — asks the app to close like clicking X; it may show a "save changes?" dialog. Re-check afterwards; do not claim it closed without looking.
- Force close needs user approval, state the risk: `Stop-Process -Id <Id>` (unsaved work is lost). Never stop: explorer, winlogon, csrss, wininit, services, lsass, dwm, svchost, System, or anything the user did not name. Match by exact process name or Id, never by wildcard.
- Minimize / maximize / restore / focus (user32 via Add-Type):
  `Add-Type -Namespace Win -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);'`
  `$p = Get-Process -Name NAME | Where-Object MainWindowHandle -ne 0 | Select-Object -First 1`
  `[Win.U]::ShowWindow($p.MainWindowHandle, 6)` — 6 minimize, 3 maximize, 9 restore
  `[Win.U]::SetForegroundWindow($p.MainWindowHandle)`
  Windows may block focus changes and only flash the taskbar icon. Report what you saw.
- Several matching windows: list them with titles and ask which one.

## Recommended native helpers
The application should expose deterministic tools such as `list_windows`, `focus_window`, `set_window_state`, `close_window`, and `desktop_screenshot`. Use Windows UI Automation (UIA) / a tested wrapper such as pywinauto for controls where possible; use raw keyboard/mouse injection only as a fallback.
