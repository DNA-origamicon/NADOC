---
name: audit-plan
description: Run one iteration of the plan-audit loop — reconcile a stale plan/topic file against the live codebase, then drive it to a terminal state (delete it, or keep it with a priority rank). Use when the user invokes `/audit-plan` (optionally `/audit-plan <slug>`) or asks to "audit the plans", "check which plans are dead/superseded", "find abandoned plans and clean them up", or "rank the unfinished plans". NOT a bug fix (issues_ledger), NOT a god-file carve-up (/carve-router), NOT a design-automation wrapper (/automate-feature).
---

# audit-plan

Run **one iteration** of the plan-audit loop. Each iteration takes ONE `memory/project_*.md`
(or root plan file), probes the codebase for the concrete things it names, classifies it, and
drives it to a terminal state: **deleted**, or **kept with a priority rank**. Optional argument
is a plan slug (`/audit-plan surface_strands`); no argument → take the handoff's `▶ NEXT`.

The taxonomy, priority rubric, queue, results table, and handoff live in
**`memory/plan_audit_ledger.md`** (repo `memory/`). This skill is the thin driver that loads it
and executes one pass — same shape as `/carve-router` over `backend_router_carveup.md`.
**Never read a `*_archive.md`** — heads only.

## The bright line (read first)

A plan's own words are **not** proof of its state. A file can *say* it's abandoned while the
code it documents is live (`bundle_stiffness_params` 0T data; `periodic_md` backend — both are
current standing HOLDs, do not touch without user OK), or *say* it's just a plan while a newer,
undocumented module already shipped it. **Only the codebase probe decides.** So:

- **Grep before you delete.** Never delete a plan whose named files/symbols are still live and
  wired without first migrating what the doc uniquely explains (schema, units, invariants).
  That migration is often the whole value of the pass.
- **Delete is a real outcome, not a failure.** A confirmed-derelict plan should go, not linger.
- **Rank only what's genuinely unfinished-and-still-wanted.** Live-reference and dormant docs
  get kept but are never ranked as "unfinished."

## Steps

1. **Resolve the target.** Argument slug → that plan file. No argument → the ledger's
   `▶ NEXT`. If neither, take the topmost unaudited entry in the **Audit queue**. **Never audit
   the out-of-scope loop-drivers** listed in the ledger (carve-up, issues, coverage,
   automation — unfinished *by design*).
2. **Load context:** read `memory/plan_audit_ledger.md` (taxonomy + rubric + queue + the living
   `## Next-session handoff` + the HOLD list). Then read the target plan's **head only**
   (top ~60 lines; never its `*_archive.md`).
3. **Extract the anchors.** From the head, list every concrete thing the plan claims: file
   paths, functions/classes, routes/URLs, JSON/data paths, frontend modules, test names,
   config flags. These are what you'll grep for.
4. **Probe the codebase (delegate — context economy).** Spawn a **read-only, no-git**
   `general-purpose` (or `Explore`) subagent — brief it explicitly to run no git commands — to
   grep the repo for each anchor and report, per anchor: **exists / dead / wired-in vs
   orphaned**, plus **any newer module or topic file that covers the same ground** (a
   supersession signal). It returns paths + the load-bearing snippet only; its file reads never
   enter this session. Do the classification here, not in the subagent.
5. **Classify** into exactly one verdict from the ledger's taxonomy: DERELICT /
   SUPERSEDED-DOCUMENTED / SUPERSEDED-UNDOCUMENTED / LIVE-REFERENCE / UNFINISHED-ACTIVE /
   DORMANT-REVIVABLE.
6. **Act on the verdict:**
   - **DERELICT** → delete the file; scrub its one-line pointer from `memory/MEMORY.md`.
   - **SUPERSEDED-DOCUMENTED** → delete + scrub; name the successor slug in the ledger row.
   - **SUPERSEDED-UNDOCUMENTED** → **migrate** the load-bearing facts into the correct topic /
     REFERENCE file *first* (that missing doc was the gap), then delete + scrub.
   - **LIVE-REFERENCE** → keep; trim the dead-plan/"unfinished" narrative down to a lean
     reference (what the live code is, where, invariants); refresh the `MEMORY.md` hook. No rank.
   - **UNFINISHED-ACTIVE** → keep; assign a **priority rank** (P0–P3 per the rubric) written
     into the head (`**Rank:** Px — <why>`) and the `MEMORY.md` hook; **rewrite the head's
     open-items list to match the code you just probed** (drop claims your probe found already
     done; keep only what's genuinely left).
   - **DORMANT-REVIVABLE** → keep; ensure an `ARCHIVED (date)` banner + a one-line revive path
     at the top. No rank.
7. **`MEMORY.md` hygiene.** Edit `MEMORY.md` at most once per pass and only for this plan's
   pointer (remove it on delete; update the hook/rank on keep). It sits in the always-loaded
   prompt prefix — every edit invalidates the prompt cache for all sessions, so touch it once.
8. **Record + hand off.** Append a row to the ledger's **Results** table (date, plan, one-line
   codebase evidence, verdict, action). Remove the plan from the **Audit queue**. **Overwrite**
   the `## Next-session handoff` with the next target + why. If a call is genuinely the user's
   to make, park it under **HOLD** instead of guessing.

## Gate

Doc-only work → **no tests needed**; say so. Only a SUPERSEDED-UNDOCUMENTED migration that edits
*code* (rare — usually you're moving prose) runs `just test-smart` and cites its decision.

## Don't

- Don't read any `*_archive.md`, and don't read the whole plan when the head decides it.
- Don't delete a plan whose named files/symbols are still live/wired without migrating first
  (the `bundle_stiffness` trap). Don't touch the standing HOLD items without user OK.
- Don't rank LIVE-REFERENCE or DORMANT-REVIVABLE docs — they aren't unfinished.
- Don't run git commands, and forbid git explicitly in the probe subagent's prompt (another
  session may share this tree — see `CLAUDE.md` → Git conventions).
- Don't audit the ongoing loop-driver ledgers — they are unfinished *by design*.
- Don't batch-audit many plans in one pass. One plan, one terminal state, one handoff.
