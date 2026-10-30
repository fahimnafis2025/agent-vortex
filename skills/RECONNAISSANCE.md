# Phase 1 — Reconnaissance (trimmed from Cloudflare RECONNAISSANCE.md)

Core loads this file in Phase 1 only. It is not needed in later phases
except for the ledger schema and state table below.

## Before any delegate: the budget gate

Apply the SKILL.md budget gate BEFORE launching any recon delegate. If it
fails, record `run_status: "incomplete"` in run-metadata.json and launch
nothing. Recon reads the target and locally available build/configuration
state only. It never contacts deployed endpoints, external identity
providers, registries, brokers, cloud APIs, or shared services.

## The four recon briefs (researcher specialists, in parallel)

Each returns structured facts to Core and writes NO files. Every claim
carries a repo-relative file:line reference. No network access. Nothing
is executed during recon — build/test commands are LISTED, not run.

### Brief 1a — Product, stack, and local operation

Read the target at `<target>`. Return:

1. Product type, users, operators, and ordinary trust-sensitive actions.
2. Languages, frameworks, build system, runtimes, locally visible
   deployment models.
3. Repo-relative entry points and subsystem boundaries.
4. Exact build and test commands that COULD run offline with local
   dependencies, their expected write locations, and the target-controlled
   inputs they process. Do NOT run them during recon.
5. Comparable software or protocol visible from local documentation and
   dependencies. If no useful comparison is source-grounded, say so.
6. Missing local toolchains or runtime facts that limit bounded
   execution. (On this PC, execution is unavailable entirely — record
   that as the standing limit, not a per-target gap.)

### Brief 1b — Principals, authority, and controls

Read all source that establishes identity, authorization, isolation, and
privilege. Map:

1. Each lower-trust principal and the actions it has by design.
2. Authentication or peer identity at each entry surface.
3. Per-resource authorization and tenant/owner scope.
4. Process, browser, workload, CI, plugin, model/tool, device, or local-IPC
   authority.
5. Privilege changes, confirmation, revocation, recovery, and fallback
   paths.
6. Which controls are source-visible and which depend on an unobserved
   deployment fact. Do not infer live reachability.

### Brief 1c — Entry surfaces, copies, and sinks

Inventory every source-visible place external or lower-trust input enters:
HTTP/browser, RPC/message/protocol, files/archive/document, CLI/env/config,
plugins/dependencies/CI, cloud events/IAM selectors, model context/tool
arguments, mobile/deep-link/webview, local IPC. For each surface, follow
major transformations, stored or derived copies, and security-relevant
sinks. Record source-visible limits and parallel paths to the same effect.
Be complete. Do not execute or send inputs.

### Brief 1d — Execution and deployment visibility (adapted)

Read tests, build definitions, manifests, packaging, and maintained
environment overlays. Return:

1. Offline tests or existing fixtures that COULD validate trust boundaries
   with dummy data — marked as owner-runnable only, since this PC has no
   sandbox and the agent never executes target code.
2. Commands that would fetch dependencies, publish artifacts, contact
   paid/provider APIs, or affect shared state — mark them PROHIBITED for
   this run.
3. Deployed controls and attachments that source cannot establish and
   therefore require `needs_validation` if decisive.
4. The final active source path for each deployment mode, only where the
   repository selects it deterministically.
5. The standing platform fact: no OS-enforced sandbox exists on this PC,
   and the agent runs shell only with approval. Target-controlled
   execution is therefore unavailable for every check in this run.

Add focused recon delegates for materially distinct deployment modes or
subsystems the four briefs do not map. Do not silently omit them: if the
budget gate blocks one, launch nothing for it, seed the unmapped area as
a `deferred` ledger unit with reason
`budget_cannot_reserve_critics_and_validation`, and disclose the gap.

## Prior-run input (Core reads BEFORE selecting work)

Read every available prior `coverage-ledger.json` and `findings.json`
for the same repo:

- Compare source locations, controls, conditions, and source-derived
  identity for every prior record and unit against current source. A
  prior source ref alone is NOT evidence a path is unchanged.
- Carry an unchanged prior `confirmed` record into the current candidate
  set, with the same fingerprint, ONLY when its relevant source,
  conditions, and qualifying evidence still apply. Link it to a current
  `planned` unit with `prior_status: "prior_confirmed_same_source"` and
  put ONLY that root cause on the hunter exclusion list. The Phase 3
  verifier that re-checks it becomes that unit's assignment owner; its
  re-check is the unit's first check and moves the unit to `candidate`.
- Changed source for a prior `confirmed` record → a current planned
  `prior_confirmed_changed_source` revalidation unit. Do NOT exclude that
  root cause from hunting; do not assume the prior verdict still applies.
- Prior `needs_validation`, `deferred`, `blocked`, `out_of_scope`, and
  changed-source units become current work. These states are priority
  input, NEVER deduplication or suppression keys. A still-blocked prior
  `needs_validation` record may be carried only after current source
  supports its trace, linked to a `planned` unit with
  `prior_status: "prior_needs_validation"`; it keeps its unresolved
  blocker and goes through current final verification.
- Prior `rejected` records are stale claims unless current evidence
  changes the failed trace or missing condition. An unchanged rejection
  suppresses only that exact claim, not review of its unit.
- Record missing or incompatible ledgers instead of treating them as
  empty coverage. State paths and source refs used in run-metadata.json;
  summarize only coverage consequences in `architecture.md`.

## architecture.md (Core synthesizes; hard cap ~1000 words)

1. Product, principals, normal authority, protected resources.
2. The comparable-software baseline from Brief 1a, when source-grounded:
   what security trade-offs the comparable accepts. Use it to calibrate
   effort and severity, NEVER to dismiss a demonstrated finding; if the
   comparable shares a defect pattern that has mattered in practice, that
   strengthens the finding. Omit when no meaningful comparable exists.
3. Tech stack, source-visible deployment paths, offline build/test
   limits (here: execution unavailable).
4. Entry surfaces and important source-to-sink or lifecycle paths.
5. Trust boundaries and the strongest source-visible control on each.
6. Repo-relative starting paths.
7. Prior coverage gaps, changed-source and blocked revalidation targets,
   same-source confirmed exclusions.
8. Short companion-selection summary: selected files and the
   source-visible boundaries that require them.

Keep the assignment-level ordinary block, selected companion blocks, and
excluded blocks with reasons in EACH LEDGER UNIT, not in
`architecture.md`. Do not select a companion file merely because a
language or dependency name appears. Select it because recon found the
trust-sensitive boundary described by its "When to use" section. Do not
exclude a visible boundary just because another delegate reviews a
related class.

## coverage-ledger.json (Core owns; top-level JSON array)

One unit per material combination of entry surface, trust boundary,
subsystem, and applicable ordinary or companion attack class, at the
profile's granularity (`quick` uses one all-in-scope subsystem identity;
`deep` adds lifecycle modes). For a scoped run, seed in-scope surfaces
for assignment and retain discovered excluded surfaces as `out_of_scope`
units so later full runs can turn them into current work.

Each dimension has a human label and a stable source-derived value in
`canonical_refs`. Use the SAME canonical reference for the same source
object across runs even if its display label changes. Suitable
references: a repo-relative entry path plus exported scope, a route or
message identity defined in source, the source control defining a
boundary, a repo package path, the exact attack-class block reference.
A block reference is `FILE.md#` plus the exact class name as written in
bold or as a heading in that file. For companion section blocks, use the
heading text before any parenthetical qualifier (e.g. `Core discipline`).
Do NOT derive references by lowercasing or slugging display labels.

Derive `coverage_id` without lossy slugs:

1. Every reference must be Unicode NFC with valid scalar values, visible
   content, no control/format/line/paragraph-separator/default-ignorable
   code points, no surrounding whitespace.
2. Encode its UTF-8 bytes with RFC 3986 percent encoding: leave only
   `A-Z a-z 0-9 - . _ ~` unescaped, uppercase `%HH` for every other byte.
3. Join encoded `surface`, `boundary`, `subsystem`, and `attack_class`
   references with `::`; append encoded `lifecycle` when present.

Use the fixed value `profile/quick/all-in-scope-subsystems` for the quick
profile's coarsened subsystem dimension. Never include wave number,
agent, verdict, severity, or line number in a reference or ID. Sort units
lexicographically by `coverage_id` before each assignment. FAIL on every
duplicate ID. If duplicate IDs have different semantic fields, that is a
canonical identity collision — never merge or silently overwrite.

Each unit records:

```json
{
  "coverage_id": "...",
  "canonical_refs": {
    "surface": "src/router.ts#POST /users/:id",
    "boundary": "src/authz.ts#requireOwner",
    "subsystem": "packages/api",
    "attack_class": "ATTACK-CLASSES.md#Access control"
  },
  "surface": "...",
  "boundary": "...",
  "subsystem": "...",
  "attack_class": "...",
  "starting_paths": ["repo/relative/path"],
  "ordinary_attack_class_block": "ATTACK-CLASSES.md#Access control",
  "selected_companion_blocks": ["FILE.md#section"],
  "excluded_blocks": [{"block": "FILE.md#section", "reason": "..."}],
  "prior_status": "new|prior_confirmed_same_source|prior_confirmed_changed_source|prior_needs_validation|prior_deferred|prior_blocked|prior_out_of_scope|prior_covered_same_source|prior_covered_changed_source|prior_rejected_claim_changed|none",
  "attempts": [],
  "wave": 1,
  "status": "planned",
  "agent_id": null,
  "reviewed_paths": [],
  "local_checks": [],
  "result_fingerprints": [],
  "unresolved": []
}
```

When `lifecycle` is material, add both `canonical_refs.lifecycle` and a
human `lifecycle` field. `ordinary_attack_class_block` is null only when
no ordinary block applies. The selected companion list includes each
applicable class plus its companion `Core discipline`, `Universal
moves`, and `Validation rules`. `excluded_blocks` records every
considered but unselected block and the source fact excluding it. Core
may add bookkeeping fields but keeps the semantic fields above stable.
`new` marks a surface first seen in this run when compatible prior
ledgers exist; `none` marks a unit seeded when no compatible prior ledger
is available. Prior `deferred`, `blocked`, `out_of_scope`, and
changed-source units initialize as current `planned` work when now in
scope. A prior same-source covered unit stays visible in the current
ledger; assign changed source, important lifecycle paths, and exact
conflicts first, then let the coverage critic decide whether it needs
another pass.

`attempts` is an append-only archive for evidence-bearing assignments a
coverage critic reopens. Before reassignment, append the prior unit's
exact `wave`, `status`, `agent_id`, `reviewed_paths`, `local_checks`,
`result_fingerprints`, and `unresolved`, plus the critic's source-backed
`reassignment_reason`. Only `blocked`, `covered`, and `candidate` states
can be archived. Archived attempts keep the same state and evidence
invariants as live units, use strictly increasing waves below the current
wave, and retain their producing owners and artifacts. The next
assignment increments `wave`, uses a fresh owner, and starts with empty
live evidence. If profile or budget prevents another assignment, increment
`wave` and use live `deferred` state with null owner, empty evidence, and
the stop reason. Never copy an archived owner's checks or artifacts into
live state. A later live terminal state contains only the new attempt's
evidence; the archive is unchanged.

Enforce this state table exactly:

| Status | Unit `agent_id` | `reviewed_paths` / `local_checks` | `result_fingerprints` | `unresolved` |
| --- | --- | --- | --- | --- |
| `planned` | null | empty | empty | empty |
| `not_applicable`, `out_of_scope`, `deferred` | null | empty | empty | nonempty reason |
| `in_progress` | canonical owner | empty | empty | empty |
| `blocked` | canonical owner | both nonempty owned partial evidence | empty | nonempty blocker |
| `covered` | canonical owner | both nonempty | empty | empty |
| `candidate` | canonical owner | both nonempty | nonempty | optional |

Canonical agent IDs match `^[a-z0-9][a-z0-9_-]{0,63}$` and are not
Windows device names. Lowercase is mandatory — one ledger cannot contain
case-fold aliases. The unit `agent_id` records the assignment owner.
Every check records its own `agent_id` and nonempty `reviewed_paths`;
the unit-level `reviewed_paths` is exactly their union. A source-only
check uses `artifact: null`. A `local` check requires a regular file
promoted ONLY by Core under exactly
`agents/<check.agent_id>/artifacts/` — on this PC, where no execution
happens, `local` checks will normally be absent; a claimed `local` check
without a Core-promoted artifact is rejected. Scratch paths, output-root
files, symlinks, special files, and another check owner's artifacts are
never evidence.

The ledger IS the coverage claim. An architecture summary, delegate
count, or generic "auth reviewed" sentence is not coverage evidence.
Phase 2 closes units only from the paths and checks in a hunter's
structured result. Run the coverage-ledger validator after seeding, after
every Core update, and before Phase 6 — IF node and the original
validator file are present; otherwise skip with a note and continue.
Fix every validator error before assigning work or making a coverage
claim.
