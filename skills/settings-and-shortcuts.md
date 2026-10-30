# settings-and-shortcuts

Opens a settings page, a link, or a built-in tool. Each is one Start-Process call.

## Settings pages
`Start-Process "ms-settings:windowsupdate"`
Other pages: ms-settings:display, ms-settings:sound, ms-settings:network-status, ms-settings:bluetooth, ms-settings:appsfeatures, ms-settings:defaultapps, ms-settings:privacy
(Opening a page does not change anything. Changing a setting needs approval.)

## Links and tools
- Website in the default browser: `Start-Process "https://example-site"`
- Screenshot tool: `Start-Process "ms-screenclip:"` (or the typed tool `desktop_screenshot()` for a real capture)
- Task Manager: `Start-Process taskmgr`
- Calculator / Notepad / Paint: `Start-Process calc / notepad / mspaint`

## Volume (no built-in cmdlet; keys via SendKeys)
```
$w = New-Object -ComObject WScript.Shell
$w.SendKeys([char]175)   # volume up (about 2% per press)
$w.SendKeys([char]174)   # volume down
$w.SendKeys([char]173)   # mute toggle
```
- Changes state: tell the user what you pressed. Report that it was sent, not the resulting level, because you cannot read it back.

## Lock screen (ask first)
`rundll32.exe user32.dll,LockWorkStation`

## Never
- Shutdown, restart, sleep, sign out: only if the user explicitly asks, and confirm once.
