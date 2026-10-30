# Skills index

Skills are markdown playbooks in this folder. Load one with `use_skill("<name>")`.
The head chef puts the right skill in each ticket — chefs load it first.

## Lab 12 specialist packs (head-chef chefs)

| Skill | Specialist | When to use |
|---|---|---|
| `researcher` | researcher | Research / verify / compare tickets. 3+ independent sources, preferred+fallback, never surrender on one error. |
| `coder` | coder | Build / fix / write-code tickets. Targeted edits, verify with list_files + py_compile + a real behaviour check. |
| `browser_op` | browser_op | Browser tickets. Read state before touching, never loop a failing action, video toggle-trap + bot-block rules. |

## Review packs

| Skill | When to use |
|---|---|
| `security-review` | "check this repo <url>, security-review it" — severity-ranked findings + fixes. |
| `windows-system` | "check my Windows update" / "open Discord / Steam" / "start my Watch Dogs" / "scan this file/folder for viruses" / "check this hash in VirusTotal" — Windows Update (COM), Defender scans, app/game launch (find exe first, Steam protocol), file hash + VT / AbuseIPDB. Never say "cannot open apps / cannot check updates". |

## v14.5 desktop + review packs (merged Claude + ChatGPT reviews, 2026-10-14)

| Skill | When to use |
|---|---|
| `computer-operator` | Everyday Windows tasks: one observable goal, observe → act → verify, never claim success from a bare exit code. Load first for ordinary computer tasks. |
| `desktop-tasks-router` | FIRST for any "do something on my PC" request — picks the right skill below, then act. |
| `windows-apps` | Finding + launching Windows apps (Start Menu / App Paths / registry / protocol). |
| `windows-games` | Finding + launching games via Steam / Epic / Xbox launchers. |
| `launch-and-open` | "open <app>" / "open my <folder>" / "launch <game>" — one command first, no Test-Path preamble. |
| `find-installed-apps` | Need an app's launch method or location — Start Menu → PATH → App Paths → Uninstall registry. |
| `launch-games` | Steam/Epic specifics: libraryfolders.vdf + appmanifest .acf parsing, rungameid launch. |
| `local-search` | Finding files / folders / apps / processes / content — scope first, cap results. |
| `find-files` | "where is my <file>" — by name / type / recency / content, bounded. |
| `file-operations` | Opening / copying / moving / renaming / deleting files + folders, verify source + destination. |
| `window-control` | What's running / focus / minimize / maximize / close a window (typed tools + PowerShell fallback). |
| `browser-operator` | Browser tasks in the shared Playwright browser — snapshot → act → fresh snapshot. |
| `desktop-troubleshooting` | After a failure — classify from the real error, recover differently, honest status. |
| `honest-failure` | Whenever a tool fails / blocked / timeout / denied — quote the exact result, never invent a cause. |
| `cve-advisory-lookup` | "known CVEs in <product>" — IDs only from advisory_lookup / fetched records, never from memory. |
| `soc-alert-triage` | L1 triage of Wazuh / Sentinel / Defender alerts — evidence-only verdict. |
| `system-checks` | Read-only status: disk / RAM / CPU / GPU / network / Defender / Update pending. |
| `settings-and-shortcuts` | Open a settings page / link / built-in tool, volume keys, lock screen. |

Note (v14.5): `window-control.md` is ChatGPT's file with Claude's
PowerShell fallback merged in (not two files). Claude's
`launch-and-open` / `find-installed-apps` / `launch-games` are kept but
trimmed to pointers + their unique parts — the full procedures live in
`windows-apps` / `windows-games` / `windows-system` so the same
PowerShell command is not duplicated across three files.

Note (2026-10-14): the LinkedIn pack (`linkedin-*`) is NOT installed in
`E:\AGENT\agent-lab\skills` — only `security-review.md` was there before
Lab 12. Do not offer LinkedIn skills until they are actually installed.

## Rules
- Content skills are pure prompts (free / local / safe). Anything that posts or acts externally is NOT a skill — the agent drafts, Fahim posts.
- Every skill file starts with frontmatter: name, specialist (if any), when_to_use. If a skill has no frontmatter, treat it as legacy and follow its body.
- If a skill name is unknown, `use_skill` tells you to run `list_files("skills")` — use this index.
