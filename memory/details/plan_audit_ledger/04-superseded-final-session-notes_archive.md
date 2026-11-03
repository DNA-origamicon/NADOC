# Superseded final-session notes — historical evidence

[Topic head](../../plan_audit_ledger.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

Third: **doc-in-code drifts independently of doc-in-memory, and the memory file usually wins.** The
ledger recorded on 07-30 that direct relax is the 07-01 linker-bridge method and **not** a swing;
`_onSecondary`'s own docstring (`overhang_connections_panel.js:429-437`) still tells the next reader
it swings the duplex about its root. **Tell: whenever a memory doc says "claim X is superseded",
grep X's own module for the same claim in a docstring.** The correction almost always landed in
prose and never in the code comment, and the code comment is what a session reads first.

(The carried-in "imported is not called" tell paid again immediately: `patchOverhang` is imported at
`overhang_connections_panel.js:40` and never invoked anywhere in the file.)

*(Its `▶ NEXT: project_ux_overhaul` was executed 07-31 — UNFINISHED-ACTIVE, P2. Its three opening
moves all paid: the `ls`-and-diff found two SHIPPED modules deleted, the argument-diff found 3
`showConfirm` sites missing `danger`, and the test count found `confirm.js` at zero. The
"watch for declined items" warning did **not** fire — this plan's declined items are correctly
segregated under "Deferred indefinitely".)*

Carry into it:

- **The overhang band is now fully closed** — `duplex_foundation` (P1), `duplex_cluster` (P2),
  `subdomains` (P2), `connections_panel` (P2), `sequence_display` (P2) all probed and mutually
  reconciled. Do not re-derive any of it; the sequence assembler's contract lives in
  `project_overhang_sequence_display.md` and the Connect/Apply truth table in
  `project_overhang_connections_panel.md`.

- **The duplex-sibling band is now closed.** `overhang_duplex_foundation` (P1),
  `overhang_duplex_cluster` (P2), `overhang_subdomains` (P2) and `overhang_connections_panel` (P2)
  have all been probed and reconciled against each other; their fork tables agree. Do not re-derive
  the Connect/Apply pipeline — read the truth table in `project_overhang_connections_panel.md`.
- **Deferrals a user explicitly declined must be labelled, not carried.** "Retire the old Overhangs
  Manager modal" sat at the top of this plan's Next-steps list looking like unfinished work; the
  body recorded, 380 lines away, that the user chose "keep modal live too". A ranked open-items list
  that silently contains a declined item invites a session to do the one thing the user refused.
  **Tell: when striking a deferral, say WHO declined it and keep the row as a "not an open item"
  note.**
- **Filing the owed rows in the other ledgers is part of the terminal state.** This plan admitted
  "NOT hand-driven" twice and had filed nothing; `MV-OCONN-1/2/3` now exist. Same miss the
  `duplex_foundation` pass caught. Check every audited plan for un-filed MV / tech-debt / automation
  rows before writing the handoff.
- LESSONS checked: nothing here supersedes an existing entry. The three tells above are audit-loop
  mechanics and belong here; the one code-level finding worth promoting — the frontend-only
  completion of a backend operation — is parked as open item 1 in the plan head, since it is a single
  concrete defect with a known fix rather than a recurring pattern (yet; if a second one turns up,
  promote it).

---

**When a subsystem gets a ground-up rewrite, per-anchor alive/dead stops meaning anything — the only
question is which GENERATION each hit belongs to.** `photo_mode_audit_plan` had two anchors that both
grepped as "live" and were opposite: `ACESFilmicToneMapping` is live because v2 **independently
re-derived** it (the v1 file it came from was never ported), while `FLUORO_EMISSIVE_MAX` is live only
because it sits in one of six sub-modules v2 inherited — with **zero callers under `src/`**. A
prefix-blind grep calls both "shipped". **Tell: the moment a repo has an `archive/` (or `_v1/`,
`legacy/`) copy of the subsystem, make the probe report the path prefix for every hit AND a caller
check for every live one. "Exists in a live directory" is not "wired".**

*(Its `▶ NEXT: project_overhang_duplex_foundation` was executed 07-30 — UNFINISHED-ACTIVE, P1. Both
of its opening moves paid: `OverhangBinding` **is** still the live model, and the sibling diff ran
first and reframed the whole verdict. Its prediction that a same-area doc is "usually a parallel
tier" held for 11 of 14 siblings and broke on one — see the CONTRADICTING PEER lesson above.)*

Carried in from that pass:

- **A plan's ledger rows in OTHER files outlive the plan, and nothing retires them.** This plan pushed
  `MV-PHOTO-1`/`MV-PHOTO-2` into `manual_validation_debt.md` and `AF-PHOTO` into the automation backlog.
  Six weeks later its whole subject was archived — and the two MV rows were still sitting in the live
  PENDING queue telling the user to drive an Exposure slider, a Bloom toggle and a Mirror floor that no
  longer exist. They read as "not yet checked" when the truth is **unrunnable**. **Tell: grep the plan's
  own IDs (`MV-*`, `AF-*`, `ISSUE-*`) across the other ledgers before you delete it — and when the
  subject is gone, mark those rows retired-with-reason rather than leaving them to be hand-driven.**
- **The last surviving copy of a bug's root cause is often a comment inside code nobody calls.** The
  whole mechanism of the yellow/purple wash (bloom samples pre-tone-map, so filmic roll-off can't tame a
  maxed emissive) existed in exactly two places: the plan being deleted, and an 11-line comment above an
  orphaned function. **Tell: grep the plan's SYMPTOM WORDS ("wash", "yellow", "flicker", "garbage
  frame"), not only its symbols — prose-only knowledge doesn't show up in a symbol sweep, and it is
  precisely the part no successor doc inherits.**
- **"Covered by the successor" needs a per-decision check, and the archive can state the OPPOSITE.**
  `project_photo_mode_archive.md` did cover Sun-sole and the composer-rebuild trap — in their
  *pre-supersession* form, one of them asserting exactly the behaviour a later decision reversed. A
  keyword hit in the successor is not coverage. **Tell: enumerate the plan's decisions, grep each one
  individually, and read the hit for vintage — a stale successor section is worse than a missing one,
  because it looks like the migration already happened.**

---

**The rule sweep has changed the base rate.** Three plan passes in: two LIVE-REFERENCE
(`regional_autorefine`, `deformation_cluster_scope`), then the first clean delete
(`cadnano_overhaul`). The variable that decided it was **whether an auto-loaded rule already covers
the plan's subsystem.** Where one does, the plan's architecture half is dead weight by definition
and the whole question collapses to "what does the rule deliberately not carry?" — for
`cadnano_overhaul` that was four behavioural laws (two of them data-loss traps), and once those
moved, delete was unarguable. **Do the rule-vs-plan diff FIRST on any plan whose subsystem has a
rule; it decides the verdict faster than the anchor sweep does.**

**The no-rule prediction held.** `assembly_part_context` was the first plan audited in a subsystem
with **no** auto-loaded rule, and it played out exactly opposite to `cadnano_overhaul`: nothing had
absorbed its architecture content, so the whole verdict came from the anchor sweep, and the doc
stayed. `path_to_thousands` turned out to be no competition at all (render/scale only) and
`assembly_configurations` is a *sibling tier*, not a successor — **"the other doc in the same area"
is usually parallel, not superseding; check what layer each one describes before assuming overlap.**

**The queue itself needs the same skepticism as the plans.** Its next entry,
`memory/trajectory_keyframes`, **does not exist** — no such file, and nothing matching
`traj*`/`*keyfram*` is in `memory/` at all. Struck from the queue. That closes the
"Phase-1-shipped, later-phase-deferred" band; remaining work is the small-tail list.
**Tell: `ls` the next target before writing it into a handoff.** All six small-tail entries were
verified present this pass (line counts in the queue's favour: `assembly_groups` 60,
`pipeline_validation_log` 55, `overhang_sequence_display` 99, `ux_overhaul` 221,
`photo_mode_audit_plan` 268 (root), `overhang_duplex_foundation` 436).

*(Its `▶ NEXT: project_assembly_groups` was executed 07-30 — the "single falsifiable claim" framing
held: Escape is genuinely unwired, and the two-site keybinding check was the right call. What it did
not predict was that the doc's whole file table had gone stale under the carve-ups.)*

Carry from that pass:
