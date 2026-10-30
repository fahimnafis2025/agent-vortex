# Skill: security-audit (deep audit)

Adapted from Cloudflare's `security-audit` skill (MIT — see NOTES.md).
Original: https://github.com/cloudflare/security-audit-skill
Trimmed for a 14B model with an 8192-token window: this core file is the
only file that loads by default. Phase detail lives in the companion files
listed at the bottom and loads on demand, one phase at a time.

## Which skill? Read this first

- "Check this repo", pasted code, or a quick local-folder review — use the
  existing `security-review` skill (single pass, prose report). NOT this one.
- "Security audit this codebase", full / comprehensive / end-to-end review,
  pen-test request, or requested report artifacts (`REPORT.md`,
  `findings.json`) — use THIS skill, full audit mode.
- Security questions, one focused finding, methodology, triage — guidance
  mode below. Do not start the full workflow.
- If the request could mean either mode, ask ONE focused question before
  creating files or starting phases.

## Modes

- **Guidance mode** (default): use only the relevant parts of this skill.
  Do not run all six phases, create an output directory, or write audit
  artifacts. Focused delegates return results to the current task.
- **Full audit mode**: all six phases, in order, to a terminal state
  (see Phase 6). Loading this skill does not by itself authorize it.

## Role map — Cloudflare terms translated to this agent

| Cloudflare term | Here |
| --- | --- |
| Parent (coordinates, owns shared state) | Core, the head-chef orchestrator. Core is the ONLY writer of shared run files. |
| Task tool (delegation mechanism) | `delegate()` tickets. |
| `research` agent (focused source exploration) | Researcher specialist. Returns facts to Core. Writes nothing shared. |
| `general` agent (broad investigation) | Coder specialist. Source inspection ONLY in audit mode — it must NEVER modify target source. The audit describes fixes; it does not apply them. |

Independence rule (no exceptions): the delegate that verifies a finding is
never the one that found it. Phase 5 uses a third fresh delegate.

Approval note: the full-audit request itself authorizes creating the run
output directory. Reads are free. `run_shell` still asks per the standing
rule (cloning a repo, running a validator) — expect approval cards.

## Full audit setup (Core does this first, before any delegate)

- **Skill dir**: the folder containing this `SKILL.md`.
- **Target**: the absolute repository root under review.
- **Repo name**: stable identifier from the directory or local Git remote.
- **Output dir**: a NEW folder OUTSIDE the target. Default:
  `E:\AGENT\agent-lab\audits\<repo-name>\run-<N>` where `<N>` is the next
  unused integer. A folder inside the target ONLY if Fahim explicitly
  selects it AND Core verifies version control ignores the whole folder.
  Otherwise stop and ask for an external path.
- **Source ref**: the reviewed commit, plus dirty/clean. Never treat
  generated or modified files as another revision.
- **run-metadata.json** (Core writes first): `run_id`, `repo`, `target`,
  `source_ref`, `profile`, `scope_paths`, `budget` (null if unset),
  `execution_policy: "source-inspection-only"`, selected companion files,
  prior-run paths, `run_status: "in_progress"`. Update only when those
  facts change; candidate state belongs in the ledger and `findings.json`.
- **Agent scratch**: `<output-dir>\agents\<agent-id>\` with `scratch\` and
  `artifacts\` subdirs. Agent IDs match `^[a-z0-9][a-z0-9_-]{0,63}$`,
  lowercase, and must NOT be a Windows device name (`con`, `prn`, `aux`,
  `nul`, `com1`–`com9`, `lpt1`–`lpt9`) — on Windows such a folder name
  breaks. Workers write ONLY to their own scratch dir. Core alone copies
  the minimum non-secret text from a worker result into shared files.
- **Paths**: Windows paths for folders. All RECORDS use repository-relative
  paths — never absolute, never `..` traversal.

## SOURCE INSPECTION ONLY — no sandbox exists on this PC

This is the biggest change from the original, and it is non-negotiable:

- NEVER execute target builds, tests, processes, browsers, emulators, or
  fuzzers. NEVER install or fetch dependencies for the target.
- Every check that would need execution becomes `needs_validation` with the
  EXACT missing fact and a safe validation plan: a bounded local fixture
  the owner can run, or an owner-observed configuration check. Never a
  live probe.
- NEVER probe deployed endpoints, production, other users' data, live
  control planes, or shared services. NEVER publish artifacts, alter
  releases, or spend paid quota.
- Defensive review only: no exploits, no payloads, no malware. Reproduction
  is described in target-neutral terms (input shape + source path), never
  as a weaponized payload chain.
- **Confirmed bar (adapted)**: a complete source trace PLUS a violation
  fully decidable from source — e.g. a privileged route with no auth
  check, a real secret committed in source, untrusted input reaching a
  dangerous sink with no control on the path. Anything needing runtime
  behavior, parser differentials, or deployment facts is
  `needs_validation`, not `confirmed`.
- **Secrets**: findings name file:line plus secret TYPE only. Never copy a
  secret value into findings, reports, or chat. This matches the standing
  rule: secret values are never pasted anywhere.

## Profiles (record in run-metadata.json; default is standard)

- **quick** — small targets, re-runs, fast first look. Coarse ledger units
  (surface x boundary x attack class; subsystem uses the fixed identifier
  `profile/quick/all-in-scope-subsystems`). Exactly ONE hunter wave
  followed by exactly ONE final critic pass. One fresh verifier per
  candidate covers BOTH Phase 3 and Phase 5. No second wave: the critic's
  new work becomes `deferred`.
- **standard** — the workflow as written.
- **deep** — high-stakes or large targets. Units split per subsystem AND
  lifecycle mode; critic waves run to a clean pass; Phase 3 and Phase 5
  verifiers are separate fresh delegates; prior same-source covered units
  get a second independent pass.
- **Scoped run** — named paths, one subsystem, one domain, or a diff
  between two refs. Seed ONLY in-scope units; everything else is
  `out_of_scope` — never `covered`. A quick or scoped run must present
  itself as partial coverage.
- Profiles change breadth and redundancy, NEVER the evidence bar, the
  candidate gate, or independent verification of `confirmed` records.

## Budget (counted in delegate() tickets)

- `budget` = max delegate() tickets across all phases. Record it.
- BEFORE any recon delegate, reserve: 4 baseline recon calls + 1 final
  critic (quick: its single final critic; standard/deep: 1 post-wave
  critic + 1 DISTINCT final-clean critic) + at least 1 verifier call.
  If the budget cannot fund that minimum: launch nothing, set
  `run_status: "incomplete"` with
  `incomplete_reason: "budget_cannot_fund_reconnaissance_and_reserves"`,
  and report that no audit pass ran.
- BEFORE each hunter wave, reserve: its post-wave critic + the final-clean
  critic + a verifier reserve (about 1–2 delegates per expected candidate;
  when in doubt reserve 30% of the balance after critic reservation).
  NEVER assign hunters into reserves. If reserves do not fit: launch no
  hunters that wave, mark its planned units `deferred` with reason
  `budget_cannot_reserve_critics_and_validation`.
- If surviving candidates exceed the validation reserve: stop hunting,
  validate in fingerprint order while budget permits, set
  `run_status: "incomplete"` with
  `incomplete_reason: "validation_budget_exhausted"`, and keep
  unvalidated candidates as ledger candidates ONLY — never in
  `findings.json`, never relabeled `needs_validation`, never reported as
  complete. A partial report is allowed only if its first section states
  validation is incomplete and lists every affected fingerprint and unit.
  Never exceed a user-set budget silently.

## The six phases (full audit mode, in order)

1. **Reconnaissance** — `RECONNAISSANCE.md`. Four researcher briefs
   (product/stack, principals/controls, entry surfaces/sinks, execution +
   deployment visibility) plus focused extras for materially distinct
   subsystems. Core synthesizes `architecture.md` (hard cap ~1000 words)
   and `coverage-ledger.json`.
2. **Coverage-led hunting waves** — `HUNTING.md` + `ATTACK-CLASSES.md` +
   selected companion docs. Coder delegates own ledger units and return
   ONE structured JSON result each. A fresh researcher post-wave critic
   runs after every wave; a DISTINCT fresh researcher final-clean critic
   runs before coverage closes (quick: exactly one wave + one critic).
3. **Candidate validation** — `VALIDATION-AND-REPORTING.md`. Every unique
   candidate (consolidated by fingerprint) goes to a fresh coder verifier
   that did NOT hunt it. The verifier re-reads every cited source
   location and tries to REFUTE the candidate.
4. **Structured output** — Core writes `findings.json` (sorted by
   fingerprint) per `report-schema.json`. Run the validators IF node and
   the original validator files are present (see Validators); otherwise
   skip with a note. Fix every error before continuing.
5. **Independent record verification** — a fresh researcher per final
   `confirmed` and `needs_validation` record (quick: merged with Phase 3).
   A MATERIAL replacement (promotion to `confirmed`, or a change to root
   cause, trace, execution, impact, or severity) goes to ANOTHER fresh
   verifier before it may be applied.
6. **Target-neutral report** — derive `REPORT.md`, `FINDINGS-DETAIL.md`,
   and `NEEDS-VALIDATION.md` from final records, the ledger, and retained
   hardening notes. Prose never changes a verdict, severity, blocker, or
   demonstrated impact. Terminal states ONLY: (a) all artifacts written
   and validators passed (or skipped-with-note), or (b)
   `run_status: "incomplete"` with its exact reason and the gap disclosed
   in the report. Never stop mid-phase.

## Verdicts and severity

- **confirmed** — a source-grounded vulnerability with a complete trace
  and a source-decidable boundary violation. Only `confirmed` records get
  severity, and overall severity never exceeds demonstrated impact.
- **needs_validation** — a source-grounded candidate with an EXACT
  unresolved blocker and at least one applicable validation-plan step
  (`local` = bounded fixture the owner can run, `deployment` =
  owner-observed configuration/identity/route/policy/runtime check).
  NO severity. It is not a low-confidence confirmed finding, and never a
  parking place for a speculative idea.
- **rejected** — a candidate disproved during validation, retained so
  future runs do not repeat the unsupported claim without changed
  evidence.
- Severity anchors: **critical** = unauthenticated actor gains code
  execution, full data-store access, or takeover of arbitrary accounts.
  **high** = an actor fully defeats an explicit security control with real
  consequences (auth bypass, cross-tenant read/write, stored script
  execution affecting other users, authenticated code execution,
  unauthenticated remote stop of a shared service). **medium** = a real
  boundary violation with limited blast radius, uncommon preconditions,
  or consequences confined to a narrow resource set. **low** =
  disclosure of non-secret internals, or an effect needing sustained
  effort for minimal gain. **informational** = a confirmed but
  minimal-impact observation, useful mainly as a prerequisite inside a
  larger finding.
- The high/medium test: does the demonstrated result FULLY defeat an
  explicit control for an action with real consequences, or only weaken
  it? If you cannot state the concrete damage, the severity is lower than
  it feels.
- Fingerprint rule (all verdicts): `^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$`.
  The same root cause keeps the same fingerprint across every state.
  Never include a line number, wave, agent, severity, or verdict in it.
- Record field lists per verdict, trace shape (entrypoint →
  propagation* → sink), and condition kinds live in
  `VALIDATION-AND-REPORTING.md`. Core reads `report-schema.json`
  immediately before writing `findings.json`. The schema uses
  `additionalProperties: false` — never carry hunter wrapper fields into
  a record.

## Candidate gate (every candidate must pass; detail in HUNTING.md)

1. Complete repo-relative source trace and evidence, including the
   strongest source-visible control on the path.
2. A proposed `confirmed` record needs a source-decidable violation,
   meaningful impact across a stated boundary, complete conditions, and
   no visible preventing layer.
3. Never strengthen a crash into code execution, ordinary work into
   shared availability, or a same-principal action into privilege gain.
4. A fact that is not source-visible means `needs_validation` with the
   exact blocker — no severity, no speculative completion.
5. A missing best practice with no affected principal or resource is a
   hardening note, not a finding. A candidate disproved by source is
   `rejected`, not `needs_validation`.
6. Return an empty candidate array when nothing survives. A clean run may
   have zero confirmed records — say so. Never invent LOW findings.

## Core principles (from the original, kept verbatim in spirit)

- Require a boundary AND a result: for every candidate, name the
  lower-trust principal, accepted input or action, intended control,
  crossed boundary, affected principal or resource, and concrete
  source-decidable result. No concrete affected principal, resource, or
  security outcome = no confirmed finding.
- Respect source visibility: deployment controls, proxy behavior,
  provider settings, browser headers, identity policy, broker ACLs,
  packaging, and topology are real controls. If they are required and
  absent from the repository, assume neither presence nor absence — use
  `needs_validation` with the exact missing fact.
- Separate priority from certainty: likelihood and impact must reflect
  demonstrated conditions and result.
- Recommend the smallest effective source fix: the invariant the code
  must enforce, and the narrowest source change enforcing it at the last
  trusted decision point. Prefer specific repo-relative changes and a
  regression test over generic hardening advice. The audit describes
  fixes; it does not modify target source.
- Defense-in-depth gaps are not vulnerabilities: if Layer A prevents the
  attack, the absence of Layer B is a hardening note.
- Multiple runs improve coverage: one run is never presented as
  exhaustive. Prior runs are additive (see RECONNAISSANCE.md).

## Anti-patterns (never do these)

1. Checklist deviations presented as vulnerabilities.
2. Defense-in-depth advice with no reachable boundary violation.
3. Live or shared-environment testing where bounded local evidence is
   insufficient — here: ANY execution of target code.
4. Guessing provider, proxy, browser, identity, or deployment behavior
   not present in source.
5. Treating intended same-principal authority or self-impact as a
   cross-boundary result.
6. Reporting an effect stronger than the observed effect.
7. Emitting prose-only hunter results that cannot be deduplicated or
   verified.
8. Re-reporting carried same-source prior confirmed records, or using
   them as exemplars that anchor the hunt.
9. Assigning severity to `needs_validation` records.
10. Writing the report before independent verification, or letting prose
    and JSON disagree.

## Validators (OPTIONAL — read before Phase 4)

The originals are `validate-findings.cjs` and
`validate-coverage-ledger.cjs`: zero-dependency Node scripts, MIT,
Cloudflare. They are NOT transcribed in this pack — the upstream repo is
the canonical source, and a hand transcription risks a subtly broken
validator. If you want them, copy them from
`https://github.com/cloudflare/security-audit-skill`
(`skills/security-audit/`).

- Run, when available: `node <skill-dir>/validate-findings.cjs
  <output-dir>/findings.json` and `node
  <skill-dir>/validate-coverage-ledger.cjs
  <output-dir>/coverage-ledger.json` — after seeding the ledger, after
  every ledger update, in Phase 4, after every Phase 5 replacement, and
  before Phase 6. Fix every error before continuing. Validator success
  proves format and ledger consistency ONLY.
- Node.js is UNVERIFIED on this PC. If `node` is absent, SKIP both
  validation steps, note the skip in REPORT.md section 1, and continue:
  `findings.json` is still written, still schema-shaped per the contracts
  in `VALIDATION-AND-REPORTING.md`. A Python equivalent is a possible
  future addition — it is NOT built here.

## Load on demand — do NOT load all of these into context at once

- `RECONNAISSANCE.md` — Phase 1 briefs, architecture rules, ledger
  schema, state table, prior-run rules. Core loads it in Phase 1.
- `HUNTING.md` — hunter prompt assembly, hunting method, candidate gate,
  structured result contract, consolidation, critic waves. Core loads it
  in Phase 2.
- `ATTACK-CLASSES.md` — the 9 ordinary attack classes plus the
  domain-routing table. Core loads it in Phase 2. Hunters receive ONLY
  their selected blocks, never the whole file.
- Companion docs — load ONLY the selected domain file for the hunters
  that need it: `MEMORY-SAFETY-AND-BINARY.md`, `AI-AND-LLM.md`,
  `WEB-PROTOCOL-AND-AUTH.md`, `CLIENT-SIDE.md`,
  `SUPPLY-CHAIN-AND-RELEASE.md`, `CLOUD-AND-DEPLOYMENT.md`,
  `PROTOCOLS-RPC-AND-MESSAGING.md`,
  `RESOURCE-EXHAUSTION-AND-AVAILABILITY.md`,
  `DATA-ISOLATION-AND-LIFECYCLE.md`,
  `DESKTOP-MOBILE-AND-LOCAL-IPC.md`.
- `VALIDATION-AND-REPORTING.md` — Phases 3–6: verifier prompts, findings
  contracts, record verification, report contents. Core loads it in
  Phase 3.
- `report-schema.json` — field contracts for `findings.json`. Core reads
  it immediately before writing `findings.json`.
- `NOTES.md` — trimming decisions, role mappings, and what did not map
  cleanly. Read it once when installing; it is not needed during a run.
