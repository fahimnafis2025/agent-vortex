;; AutoHotkey v2 script for moving windows between two monitors

; Get primary monitor dimensions
primaryWidth := A_ScreenWidth
primaryHeight := A_ScreenHeight

; Get secondary monitor position (assuming it's to the right of primary)
; Adjust these values based on your actual setup
secondaryX := primaryWidth
secondaryY := 0

; Hotkey to move active window to secondary monitor
^!m::
    WinGet, activeWin, ID, A
    WinGetPos, x, y, w, h, % "ahk_id " activeWin
    
    ; Move window to secondary monitor
    WinMove, % "ahk_id " activeWin, , % secondaryX, % secondaryY, % w, % h
return

; Hotkey to move active window back to primary monitor
^!n::
    WinGet, activeWin, ID, A
    WinGetPos, x, y, w, h, % "ahk_id " activeWin
    
    ; Move window to primary monitor
    WinMove, % "ahk_id " activeWin, , 0, 0, % w, % h
return