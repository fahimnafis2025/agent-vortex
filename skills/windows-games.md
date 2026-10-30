# Windows Games and Launchers

## Use when
The user asks to open a game, find a game's installation, open Steam/Epic/Xbox/another launcher, or troubleshoot a game that appears installed but cannot be found.

## Preferred strategy
1. Identify the game title and, when relevant, its launcher. Do not infer an executable name from the game's display name.
2. Check whether the launcher or game process is already running.
3. Search Start-menu registrations and registered launcher entries.
4. For Steam, try the registered Steam URI handler for opening the client (for example, `steam://open/main`) if appropriate. If the client opens but a specific game is requested, discover its actual Steam AppID from a reliable local record before forming a game-launch URI.
5. If needed, inspect Steam's own installation registration and `libraryfolders.vdf` to find library roots, then inspect matching `appmanifest_*.acf` files for the installed game metadata. Treat these as discovery sources, not guaranteed proof a game will launch.
6. For Epic/Xbox/other launchers, use their registered app/shortcut/protocol and verified metadata. Do not assume Steam-style URI conventions apply to other launchers.
7. Prefer launching through the normal game launcher. Games can depend on launch arguments, services, runtime components, or anti-cheat startup that may not be reproduced by opening a random executable directly.
8. Verify whether the launcher/game process started. If native window tools are not available, do not claim that the game window is visible or focused.

## Rules
- Never say “not installed” after checking only one default path.
- Do not recursively scan every drive as the first step. Search known registrations and expected library locations first.
- Do not install a missing launcher or game, change account settings, accept purchases, or disable anti-cheat/security software without explicit user authorization.
- Do not force-kill a game process to close it unless the user explicitly requests termination and the consequences are clear. Prefer the game's own exit path or a normal window-close request when native window tools exist.
- If several editions or launchers match, ask the user to choose or report the candidates.

## Honest completion states
Use exact distinctions such as `launcher_found`, `launcher_started`, `game_manifest_found`, `game_process_started`, `launch_failed`, and `window_not_verified`. An installed manifest is not proof the game works; a running process is not proof that the game is responsive.
