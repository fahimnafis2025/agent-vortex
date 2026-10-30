# desktop-tasks-router

Use first for any "do something on my PC" request. Pick the right skill, then act.

## Pick a skill
- open/launch an app or folder -> launch-and-open, find-installed-apps
- launch a game -> launch-games
- find a file or folder -> find-files
- close/minimize/focus a window, what is running -> window-control
- disk, RAM, CPU, GPU, network, Defender status -> system-checks
- settings pages, links, screenshot, volume -> settings-and-shortcuts
- tool failed or was blocked -> honest-failure

## Risk tiers
- Read-only (just do it): list, find, status checks.
- Opens something (do it, one command): launch app/folder/URL, open a settings page.
- Changes state (ask the user first, say what will happen): close with unsaved-work risk, Stop-Process, delete, move, install, uninstall, lock, volume/system settings, starting a scan.
- Never without an explicit request: shutdown, restart, sleep, deleting outside the project folder, editing the registry.

## Habits
1. Do the action the user asked for. A check is not the action.
2. One command per step. Do not stack unrelated operations.
3. Read the result before the next step. Quote it if it fails.
4. Ambiguous target ("open the game") with several matches: list the matches and ask once.
5. Report in one line: what you did and what you saw.
