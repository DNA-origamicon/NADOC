---
name: audit-debt
description: Run one iteration of the tech-debt burn-down loop — take one TD-NN item from memory/project_tech_debt.md, probe every bullet against live code, and drive each to a terminal state (stale / fixed / deleted / decided / promoted / accepted). Use when the user invokes `/audit-debt` (optionally `/audit-debt TD-07`) or asks to "work the tech debt", "burn down the debt ledger", "resolve the next tech-debt item", or "clean up the stragglers". NOT a bug fix from user reports (issues_ledger), NOT a stale-plan audit (/audit-plan), NOT manual-validation debt (manual_validation_debt.md).
---

# audit-debt

Run **one iteration** of the tech-debt loop. Each iteration takes ONE `TD-NN` item from
**`memory/project_tech_debt.md`**, probes every bullet in it against the live codebase, and drives
each bullet to one of six terminal states. The item is done when **every** bullet carries one —
then it moves to `project_tech_debt_archive.md` and the handoff points at the next item.

Optional argument is an item id (`/audit-debt TD-07`); no argument → the ledger's `▶ NEXT`.

The queue, terminal-state taxonomy, priority bands, DECISIONS and ACCEPTED lists, and the handoff
all live in the ledger head. This skill is the thin driver — same shape as `/audit-plan` over
`plan_audit_ledger.md`. **Never read `project_tech_debt_archive.md`.**

## The bright line (read first)

**A debt bullet is a claim, not a fact.** Almost every entry was written by an `/audit-plan` sweep on
2026-07-30/31 and has not been re-checked since. Code moved; some bullets were wrong when written.

- **Probe before you touch anything.** A bullet whose anchor no longer exists is **STALE** — strike
  it with the evidence, don't "fix" it.
- **"Decide before deleting" means the user decides.** Dead code left behind by a *retired feature*
  can be hiding a latent bug (`reapplyLerp`, `_clearStapleChecks`) or a cheaper code path (the
  deformation in-place-PATCH branch). Those go to **DECISIONS**, never a silent delete.
- **Deleting files, directories, or tests is user-confirm territory** (`CLAUDE.md` → Risky-action
  policy). Deleting a *symbol* with zero callers is not.
- **Scope creep is the failure mode.** If a bullet turns into a program (write 4 rules, test a
  4k-LOC module, carve a god-file), that is **PROMOTE** — hand it to the owning loop and strike it
  here. Never start a program inside this loop.
- **DNA topology / three-layer questions → ask the user, implement nothing** (`CLAUDE.md`).

## Steps

1. **Resolve the target.** Argument id → that item. No argument → the ledger's `▶ NEXT`. If neither,
   take the top unstruck row of the **Queue** table. One item per pass — never batch.
2. **Load context.** Read `memory/project_tech_debt.md` — the head (through the handoff) plus the
   target `TD-NN` section only. Skim `memory/feedback_*.md` filenames against the area the item
   touches and open any that match. If the item names a subsystem with a `memory/project_*.md`
   topic file and you will change behavior there, read that file's **head**.
3. **Extract the anchors.** List every concrete thing the item's bullets claim: file paths, symbols,
   line numbers, routes, test names, LOC counts, "zero callers" claims. These are what gets probed.
   A bullet with no falsifiable anchor is a prose claim — say so and rank it last.
4. **Probe (delegate — context economy).** Spawn a **read-only, no-git** `general-purpose` (or
   `Explore`) subagent — brief it explicitly to run **no git commands** and make **no edits** — to
   check each anchor and report, per anchor: **exists / moved / gone**, **callers: N (list them)**,
   and whether any newer module already covers it. It returns paths + the load-bearing snippet only.
   Classify here, not in the subagent.
5. **Assign a terminal state per bullet** — STALE / FIXED / DELETED / DECIDE / PROMOTED / ACCEPTED
   (definitions + tests in the ledger head's table). Do this for **every** bullet before editing
   code, so the pass has a known shape.
6. **Execute, cheapest-first.** Prose/comment fixes, then symbol deletes (only after "callers: 0" is
   confirmed **repo-wide**, including tests, e2e, scripts and `experiments/`), then real code fixes.
   For a behavior fix, pin it: ≥1 test that fails without the change (backend `pytest`, frontend
   `vitest`) unless the fix is provably prose-only.
7. **Gate.** Per the ledger's Gate section: backend → `just test-smart` (cite decision, pass count,
   any `DEFERRED` group); frontend → `just test-frontend` **plus exercise it in the running app**,
   or lead the report with `NOT VERIFIED IN APP`; prose-only → no tests, say so. Never run
   `just test` / `just test-slow` — those are test-dedicated-session only; ask the user instead.
8. **Record.** In the ledger: strike each resolved bullet with `~~…~~ — <STATE> YYYY-MM-DD:` plus
   **one line of probe evidence** (what you grepped, what it returned). When every bullet in the
   item is struck, cut the whole `TD-NN` section into `project_tech_debt_archive.md` and strike its
   Queue row. If bullets remain (DECIDE parked, PROMOTE pending), leave the section with a
   `▶ REMAINING:` line naming exactly what's left, and keep the queue row.
9. **Park decisions + promotions.** DECIDE bullets → the **DECISIONS** section, one question with
   its two outcomes. PROMOTE bullets → append to the owning loop's ledger (`main_js_carveup.md`,
   `SIM_COVERAGE_PLAN.md`, a `project_*.md` topic file — create one only if none fits) and leave a
   one-line pointer here.
10. **Hand off.** Overwrite `## Next-session handoff` with: what this pass closed, the next `▶ NEXT`
    id + why it's next, and the trap the next pass should expect. Move the `▶ NEXT` marker in the
    Queue table. Surface any new DECISIONS to the user in the done message — batched, one line each.
11. **`MEMORY.md` hygiene.** Touch `memory/MEMORY.md` **only** when the ledger's headline state
    changes (e.g. the queue empties). It sits in the always-loaded prefix; every edit invalidates the
    prompt cache for all sessions.

## Re-ranking

The queue is a starting order, not a contract. If the probe shows an item is far cheaper or far more
harmful than its band says, move its row and say why in the handoff. New debt found *while*
resolving an item gets appended as a new `TD-NN` section + queue row — don't fix it opportunistically
in this pass.

## Done message (what to report)

- Item id + title, and the per-bullet tally (`3 STALE / 2 FIXED / 1 DECIDE`).
- The probe evidence that changed the plan (which bullets were already dead).
- Gate result verbatim: `just test-smart` decision + pass count, or why no tests were needed.
- Any new DECISIONS, one line each.
- Next `▶ NEXT`.

## Don't

- Don't read `project_tech_debt_archive.md`, or any other `*_archive.md`.
- Don't delete on a bullet's word alone — "zero callers" is a claim until your probe reproduces it.
- Don't delete a file, directory or test without user confirmation.
- Don't guess on a DECIDE bullet to keep the pass moving.
- Don't run git commands, and forbid git explicitly in the probe subagent's prompt (another session
  may share this tree — `CLAUDE.md` → Git conventions).
- Don't batch items, and don't leave an item half-classified: every bullet gets a state.
- Don't confuse this with the neighbouring loops: user-reported bugs → `issues_ledger.md`; stale
  plans → `/audit-plan`; features shipped without a hand-check → `manual_validation_debt.md`;
  god-file decomposition → `/carve-router` (backend) or `main_js_carveup.md` (frontend).
