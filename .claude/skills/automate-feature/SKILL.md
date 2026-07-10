---
name: automate-feature
description: Run one iteration of the design-automation feature loop — give a UI-only / API-less NADOC operation a programmatic (headless) entry point AND a reusable validation oracle. Use when the user invokes `/automate-feature` (optionally `/automate-feature AF-N`) or asks to "work the next AF item", "run a design-automation loop", or "add a headless wrapper for X". Builds toward automated validation + eventual text-to-DNA-origami. NOT a god-file carve-up (that's /carve-router) and NOT a bug fix (that's issues_ledger).
---

# automate-feature

Run **one iteration** of the design-automation backlog loop: take one operation that today is GUI-only or
has a REST route but no programmatic entry, give it a **headless wrapper** (or a new headless module / a
`backend/core` service), and ship a **reusable validation augment** that proves it correct. Optional
argument names the item (`AF-3`); otherwise take the handoff's next.

The full protocol, target shapes, anti-shovel metric, and ranked backlog live in
**`design_automation_backlog.md`** (repo root). The oracle catalog, lessons, and difficulties ledger live in
**`design_automation_log.md`**. Two read-on-demand siblings (split out 2026-06-25 to keep the per-loop read
small): **`design_automation_harness.md`** (do-not-rebuild wrapper signatures + banked gotchas — open only the
block for the item you're extending) and **`design_automation_metrics.md`** (per-item metrics rows + data fits).
This skill is the thin driver that loads them and runs one pass.

**Context economy (2026-07-09).** The backlog and log were split into a lean *head* + a `*_archive.md`
holding shipped items, full oracle prose, and per-loop history. Each head carries a one-line index with a
hook for every oracle / lesson / backlog item. **Never read `design_automation_backlog_archive.md` or
`design_automation_log_archive.md` in a routine loop** — open one only to mine a specific past decision.
Append new rows to the *head*. See `memory/project_context_economy_split.md`.

## The bright line (read first)

This loop exists to **stop passthrough-shipping.** A `headless_build.foo()` that just forwards to
`POST /design/foo` with no new validation power is worthless — it lengthened the call chain and proved
nothing. So:

- **"A wrapper exists" is never the pass criterion.** It's narrative only.
- The pass criterion is **a reusable validation augment** (round-trip equality / inverse-pair invariant /
  geometric oracle / `validate_design` gate / JS↔Python parity) that asserts a *property of the result*.
  Every item logs which oracle it shipped and ends with the one-sentence justification:
  **"Validation gained, not just a passthrough: ___."** No honest justification → it was a passthrough → revert.
- This is **feature work**, so it obeys `FEATURE_DEVELOPMENT.md`: new code lands in `headless_build.py` /
  a new `headless_*_build.py` / `backend/core` — **never** in `crud.py` / `assembly.py` / `main.js`
  (those god-files end flat-or-lower).

## Steps

1. **Resolve the item.** Argument `AF-N` → that backlog entry. No argument → the handoff's `▶ NEXT`.
2. **Load context:** read `design_automation_backlog.md` (protocol + backlog + the ≤8-line living
   `## Next-session handoff`) and `design_automation_log.md` (conventions + oracle catalog + lessons +
   difficulties). Read `FEATURE_DEVELOPMENT.md` (module-first law). Skim the area's `memory/project_*.md`
   (e.g. `headless_build`, `assembly_overhaul`). Open `design_automation_harness.md` /
   `design_automation_metrics.md` ONLY for the specific item you're extending — never wholesale.
3. **Re-derive the surface (cheap, do it):** confirm the REST route still exists + what it expects
   (`rg "<url>" backend/api/`) and is still UI-wired (`rg "<fn>" frontend/src/api/`). Dead route → propose
   deleting it via `issues_ledger.md`, don't wrap it.
4. **Decide the shape** — headless wrapper (in `headless_build.py`) / new headless module
   (`headless_assembly_build.py`) / service+oracle push (`backend/core/<area>.py`) — and **pick the
   validation form** from the oracle catalog BEFORE coding. Write the oracle first where practical (it
   should fail until the wrapper works).
5. **Build** the wrapper/module/service + the validation augment (direct unit/integration test in `tests/`).
   The wrapper runs the *same* service the route runs; it does not re-implement logic. No god-file growth.
   - **Topology/geometry/directionality (esp. AF-6 deformation): ASK THE USER FIRST** per `CLAUDE.md` —
     don't reason out bend/twist sign or frame conventions.
6. **Gate:** `just test-smart` green — cite its decision + pass count, flag any *drop*. `just lint` clean on touched files. (Full `just test` is the pre-push gate, not this loop.)
   A feature without its validation augment does not ship.
7. **Commit** (one item): `feat(automation): headless <op> + <oracle>`. Only when the user has asked, per
   CLAUDE.md git rules.
8. **Update the ledgers:** check the box in the backlog; add a metrics row to `design_automation_metrics.md`
   **with the mandatory justification line**; if you shipped a reusable wrapper, add one block to
   `design_automation_harness.md` (+ its index line) and an oracle-catalog row to the log; **overwrite** the
   backlog's `## Next-session handoff` (≤8 lines) with the next item + any gotcha — do NOT append harness
   blocks to the handoff. Bank a new `## Lessons` entry in the log if you hit a class of problem.
9. **Route findings:** bug → `issues_ledger.md` (+ `issues_fix_log.md` if fixed). A genuinely un-headless-able
   pixel-gesture op → push an `MV-N` row to `manual_validation_debt.md` (hand-validated, not automated).
   Stuck item → the log's difficulties ledger with *why*.

## Don't

- Don't ship a passthrough — chase the validation augment, not "a wrapper exists."
- Don't add operation logic to `crud.py` / `assembly.py` / `main.js`.
- Don't change a route URL, touch `_PHASE_*`, or alter `mutate_and_validate` / `set_design_silent` /
  `snapshot` usage.
- Don't let `backend/core` import from `backend/api`.
- Don't reason geometrically about crossover placement (mechanical rules only).
