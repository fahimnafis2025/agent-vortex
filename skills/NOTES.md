# NOTES — security-audit skill pack (adaptation notes)

Read once when installing. This file is NOT needed during a run.

## Attribution

Adapted from Cloudflare's `security-audit` skill, MIT License:
https://github.com/cloudflare/security-audit-skill
(`skills/security-audit/`). Original files: `SKILL.md` (331 lines),
`RECONNAISSANCE.md` (294), `HUNTING.md` (477),
`VALIDATION-AND-REPORTING.md` (327), `ATTACK-CLASSES.md` (267), ten
companion domain docs, `report-schema.json`, `validate-findings.cjs`
(~1400 lines), `validate-coverage-ledger.cjs`. This pack trims and
re-targets that material; it is not a copy. Keep this attribution with
the pack.

## What this pack is (and is not)

- A SEPARATE deep-audit skill alongside the existing
  `security-review.md`. It does not replace it. Quick "check this repo"
  requests keep using `security-review` (single pass, prose report).
  Explicit "security audit this codebase" / full-audit / pen-test
  requests, or requested report artifacts (`REPORT.md`,
  `findings.json`), use this pack.
- A PROMPT PACK only. No `agent.py` changes, no new tools, no network
  calls from the skill itself. Delivery is files in this folder; nothing
  here is installed on Fahim's PC until he installs it.

## The one big adaptation: SOURCE INSPECTION ONLY

The original skill assumes an OS-enforced sandbox (no external network,
empty allowlisted environment, read-only target, scratch-only writes,
resource limits) and confirms findings with bounded local execution.
Fahim's PC has no sandbox, and his agent runs shell only with approval.
So this pack removes execution entirely:

- No delegate ever executes target builds, tests, processes, browsers,
  emulators, or fuzzers. No dependency installation for the target.
- Every check that would need execution becomes `needs_validation` with
  the exact missing fact and a safe owner-runnable plan (bounded local
  fixture the owner can run, or an owner-observed configuration check).
- The `confirmed` bar is therefore redefined (documented in SKILL.md):
  a complete source trace PLUS a violation fully decidable from source.
  Anything needing runtime behavior, parser differentials, or deployment
  facts is `needs_validation`. Without this redefinition the skill could
  never produce a `confirmed` finding on this machine, which would make
  it useless; with it, the bar stays honest — source-decidable only.
- Consequences to be aware of: availability, race-window, parser-
  differential, and deployment-behavior findings will skew heavily to
  `needs_validation` on this setup. That is correct behavior, not a bug.
  The report must say so (source-inspection-only statement, REPORT.md
  section 1).

## Trimming decisions (for a 14B model, 8192-token window)

The original is ~2,500+ lines of workflow text plus ~2,800 lines of
validators. Pasting that into a 14B's context would crowd out the model
(the Lab 11 diet lesson). Trimming strategy: a tight orchestrator core
that always loads, plus detail that loads ONE PHASE AT A TIME and is
dropped after. Hunters receive only their selected blocks, never whole
files.

What was cut, and why:

1. **The 11-step descriptor-level promotion procedure** (SKILL.md,
   HUNTING.md, VALIDATION-AND-REPORTING.md in the original). It requires
   trusted parent-side code holding non-inheritable directory
   descriptors and no-follow traversal — a harness capability, not a
   prompt. A prompt pack cannot implement it. Replaced with a short
   adapted rule: workers write only to their own ticket scratch dir;
   Core alone copies the minimum non-secret text into shared files.
   The race-safety guarantees of the original are NOT preserved — the
   mitigation is that no target code ever runs here, so scratch content
   is worker prose, not target-controlled output.
2. **Sandbox execution sections.** All sandbox controls, sandbox
   capability checks, loopback fixtures, and "bounded local execution"
   passages were converted to the source-inspection-only rule above.
   Where the original says "run the narrowest local harness", this pack
   says "record it as needs_validation with an owner-runnable plan".
3. **Validator internals and test files.** `validate-findings.test.cjs`
   and `validate-coverage-ledger.test.cjs` are not included (test
   scaffolding, not needed at runtime).
4. **The two validator scripts themselves** — see "Validators" below.
5. **Companion class prose.** Each companion doc keeps its "When to
   use" trigger, Core discipline, every class name, Universal moves,
   and Validation rules — but each class is distilled to 1–3 lines (the
   check + the key trap) instead of the original's full paragraphs.
   Class NAMES are preserved exactly, because the coverage ledger cites
   them as `FILE.md#Class name` block references. Nothing was renamed.
6. **Hunting-method and verifier-prompt prose.** Kept in full where it
   is the actual instruction a delegate receives (HUNTING.md method
   block, Phase 3 verifier prompt), trimmed where SKILL.md only needs a
   summary. Duplication between SKILL.md and phase docs is deliberate:
   SKILL.md is the orchestrator's checklist; phase docs are the text
   Core copies into delegate briefs.
7. **Budget arithmetic detail.** The original's exact reserve percentages
   and pre-recon estimate format are simplified to the reserve rules in
   SKILL.md (reserve critics + verifiers before hunting; ~30% verifier
   reserve guidance kept). The hard-stop rules (incomplete statuses and
   reasons) are kept verbatim.
8. **Prior-run mechanics.** Kept (carry/ revalidate/ suppress rules),
   because Fahim re-runs audits on the same repos (NetRecon) and the
   additive-run design is the point. Wording tightened, rules unchanged.

What was NOT cut: the six-phase order, the candidate gate, the verdict
contracts (field lists match `report-schema.json` exactly), the severity
anchors, the coverage-ledger schema and state table, the coverage_id
encoding rule, the critic-wave loop, the independence rule, the
material-replacement rule, the terminal-state rule, and the anti-patterns.

## Role mappings

| Original | This pack | Notes |
| --- | --- | --- |
| Parent | Core (head-chef orchestrator) | Owns ALL shared run files. Only writer of them. |
| Task tool | `delegate()` tickets | One ticket per hunter/verifier/critic. |
| `research` agent | Researcher specialist | Focused source exploration + Phase 5 record verification. Returns facts; writes nothing shared. |
| `general` agent | Coder specialist | Broad investigation (hunting, Phase 3 verification). SOURCE ONLY in audit mode — must never modify target source, even though its normal instinct is to implement. Core's briefs must say this explicitly. |
| Agent scratch + parent-owned artifacts | `<output-dir>\agents\<agent-id>\scratch\` + `artifacts\` | Windows paths. Agent IDs lowercase, never a Windows device name (a folder literally named `con` or `nul` breaks on Windows — the original's rule matters more here, not less). |
| `~/security-audit-skill/<repo>/run-<N>` | `E:\AGENT\agent-lab\audits\<repo-name>\run-<N>` | His project drive. Override freely per run. |
| `execution_policy: "sandboxed-source-and-local-only"` | `execution_policy: "source-inspection-only"` | The honest label for this setup. |
| `/tmp` / host home as scratch fallback | FORBIDDEN (as in the original) | Scratch lives only under the run output dir. Never the repo, never home. |

## What did not map cleanly

1. **No sandbox → no local checks.** The original's `method: "local"`
   checks (with Core-promoted artifacts) will normally be absent. The
   ledger schema keeps the field for compatibility, but a claimed `local`
   check without a Core-promoted artifact is rejected. Expect
   `local_checks` to stay empty on most runs; that is fine.
2. **No trusted promotion code.** See trimming decision 1. The adapted
   rule is weaker by design; it is safe here ONLY because no target code
   runs. If a sandbox is ever added, restore the original promotion
   procedure before trusting scratch artifacts as evidence.
3. **Coder specialist vs "do not modify target source".** The coder's
   normal job is to write code. In audit mode its briefs must explicitly
   forbid modifying the target; the audit describes fixes only. If a
   coder delegate ever edits target source during an audit, that run's
   results are suspect (the reviewed source changed mid-run) — Core
   should discard and re-run that unit.
4. **Budget counted in delegate tickets, not model calls.** The
   original counts agent invocations; this pack counts `delegate()`
   tickets. Core's own model calls (recon synthesis, ledger updates,
   report writing) are not counted, so a "budget" here is a delegate
   budget, not a token/cost budget. Say so in REPORT.md if a budget was
   set.
5. **The `general` agent's execution role has no equivalent.** In the
   original, `general` agents run bounded local checks. Here they do
   source-only investigation, same as `research` agents but broader.
   The two roles differ in scope (focused vs broad), not in capability.
   Kept as separate roles because Phase 3 (coder verifier) vs Phase 5
   (researcher verifier) independence depends on them being different
   delegates.
6. **Approval cards during an audit.** `run_shell` always asks per
   Fahim's standing rule. Cloning a target repo and running validators
   will each trigger approval cards. The full-audit request authorizes
   the run output directory, but NOT blanket shell execution — Core
   should batch shell needs where possible and expect Fahim to approve
   the clone/validator calls. Reads via `read_file`/`list_files` need no
   approval.
7. **Windows device names in agent IDs.** The original mentions this
   once; on Fahim's Windows PC it is a live footgun (a ticket scratch
   dir named `con` or `aux` fails to create). Core must validate every
   agent ID against the device-name list before creating folders.
8. **Git history review (Wildcard class).** The original's wildcard
   brief suggests reading git history for reverted fixes and removed
   secrets. On a cloned repo this is source review and allowed — but
   any secret found in history is reported as TYPE + location only,
   never the value, per Fahim's standing secrets rule (which is stricter
   than the original's silence on the point).

## Validators — why the .cjs files are not in this folder

`validate-findings.cjs` (~1400 lines) and
`validate-coverage-ledger.cjs` were read but NOT transcribed here. The
source was read through a rendered web view that mangles code
formatting; a hand transcription of ~2,800 lines through that rendering
risks a subtly broken validator, which is worse than no validator —
a validator that passes bad findings (or fails good ones) silently
corrupts the run's trust model. The upstream repo is the canonical
source. The skill treats validation as OPTIONAL (see SKILL.md): if node
and the original files are present, run them; if node is absent
(unverified on this PC), skip both steps, note the skip in REPORT.md,
and continue with schema-shaped `findings.json`. A Python equivalent
validator is a possible future addition — it is NOT built here, per the
brief.

To add validators later, copy from the upstream repo (MIT):

```
skills/security-audit/validate-findings.cjs
skills/security-audit/validate-coverage-ledger.cjs
```

and run:

```
node <skill-dir>/validate-findings.cjs <output-dir>/findings.json
node <skill-dir>/validate-coverage-ledger.cjs <output-dir>/coverage-ledger.json
```

## Install note for Fahim (NOT installed yet — files only)

1. Copy this whole folder (`security-audit/`) into the agent's skills
   directory alongside `security-review.md`. Do not overwrite
   `security-review.md` — the two skills coexist; routing is by request
   wording (see SKILL.md "Which skill?").
2. Optional: copy the two `.cjs` validators from the upstream repo
   into this folder (see "Validators" above). Check whether node exists
   first: `node --version` in PowerShell. If it prints a version, the
   validation steps will run; if not, the skill skips them and notes it.
   Either way the skill works.
3. Nothing else to install. No `agent.py` change, no new tools, no
   packages. The first run to try it on: an explicit
   "security audit this codebase" request on a small repo, `quick`
   profile, so the workflow can be watched end to end before trusting
   it on anything large.
4. Expect approval cards on the first run: repo clone (if the target is
   a URL) and validator runs go through `run_shell`, which always asks.
   The run output directory itself is authorized by the audit request.
