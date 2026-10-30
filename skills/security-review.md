# Skill: security-review

Hunt for security vulnerabilities in a codebase. Fahim's flow:
"check this repo <url>" or pasted code or a local folder. You clone
(or read), you review, you report — ranked by severity, with fixes.

## Phase 0 — get the code
- GitHub URL: `git clone --depth 1 <url>` via run_shell (shallow =
  fast, you don't need history). Work inside the cloned folder.
- Pasted code: review it directly.
- Local folder: list_files first, never guess paths.

## Phase 1 — recon (2 minutes, don't skip)
- list_files the repo root. Identify the stack: package.json,
  requirements.txt, go.mod, composer.json, *.sln, etc.
- Find entry points: routes, API handlers, auth code, DB queries.
- Note what's sensitive: payments, passwords, tokens, PII, file uploads.

## Phase 2 — secrets (grep first, it's fast)
Run these via run_shell (git grep -n -i) on the cloned repo:
- `password|passwd|secret|api[_-]?key|token|private[_-]?key`
- `aws_|sk-|ghp_|xoxb-|BEGIN PRIVATE KEY`
- Check for `.env` files actually committed, and config files with
  real credentials (not placeholders).
Anything that looks like a REAL secret (not `password = "..."` placeholder)
is a finding. Tell Fahim to rotate it — committed secrets stay in git
history even after deletion.

## Phase 3 — injection & input handling
- SQL: string-concatenated queries, f-strings / % formatting into SQL.
  (Parameterized queries = fine, say so.)
- Command injection: shell=True, os.system, exec with user input.
- XSS: unescaped user data rendered into HTML (innerHTML, dangerouslySetInnerHTML, Jinja |safe).
- Template/SSTI, LDAP, XPath: same pattern — user input into interpreters.
- Deserialization: pickle.loads, yaml.load (not safe_load), eval().

## Phase 4 — auth & sessions
- Hardcoded credentials, default admin/admin logins.
- Passwords stored plain or with weak hashing (md5/sha1, no bcrypt/argon2).
- Missing auth on routes that should have it (compare route list vs
  auth middleware).
- JWT: none-algorithm acceptance, missing expiry, weak secrets.
- CORS: `*` with credentials.

## Phase 5 — dependencies & config
- Flag obviously ancient majors (e.g. lodash 3.x, jquery 1.x) — say
  "check for CVEs", don't invent CVE numbers.
- Debug mode on in production, verbose error pages leaking stack traces.
- Missing security headers is a note, not a finding.

## Phase 6 — report
Rank every finding: **CRITICAL / HIGH / MEDIUM / LOW**. For each:
- file:line, what's wrong (one line), why it matters (one line),
  the fix (concrete — show the corrected pattern, don't just say "sanitize").
End with: total counts per severity, and the honest line — "this is a
first-pass review, not a guarantee; run your test suite and consider a
dedicated SAST scan for anything handling money or PII."

## Rules
- Every finding needs a file:line and a code path — no vibes-only findings.
- If you can't confirm exploitability, say "potential" and explain
  what would make it real.
- Don't rewrite the whole repo. Report first; fix only what Fahim asks for.
- Keep the report tight. Criticals first, always.
