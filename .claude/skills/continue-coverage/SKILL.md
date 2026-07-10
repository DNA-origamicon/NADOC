---
name: continue-coverage
description: Run one iteration of the full simulation/feature-coverage loop — advance the four structure-prediction engines (CanDo FEM, mrDNA, oxDNA, NAMD) toward covering all four unconventional features (extra crossover bases, linkers/overhang connections, E-fields, anchors) AND emit shared, comparable prediction descriptors so engines cross-validate. Use when the user invokes `/continue-coverage` (optionally `/continue-coverage <TASK-ID>`) or says "continue full simulation/feature coverage", "work the next coverage task", or "run the sim-coverage loop". A manager (this main-loop session) reads the JSON plan + handoff, picks the next-best task by rubric, builds it with an oracle, validates, and hands off. NOT a design-automation headless wrapper (that's /automate-feature), NOT a god-file carve-up (/carve-router), NOT a bug fix (issues_ledger).
---

# continue-coverage

Run **one** iteration of the sim-coverage loop. You are the **manager**: a single main-loop session that reads
the authoritative plan + the previous handoff, picks the highest-leverage eligible task, implements it with a
machine-checkable oracle, validates (fast/slow-tagged + a one-off display-vs-oracle check), auto-commits to
master, and overwrites the handoff. Use **read-only subagents** for investigation and a fresh-context
diff-vs-plan review — **never** an implementer swarm.

State files (all repo root): [`SIM_COVERAGE_PLAN.md`](../../../SIM_COVERAGE_PLAN.md) (protocol + rubric +
handoff), [`sim_coverage_plan.json`](../../../sim_coverage_plan.json) (authoritative task list — status-only
edits), [`sim_coverage_log.md`](../../../sim_coverage_log.md) (log + oracle catalog),
[`sim_coverage_metrics.md`](../../../sim_coverage_metrics.md) (metrics + agreement table).

**Context economy (2026-07-09).** `sim_coverage_log.md` is now a lean head (conventions + full oracle
catalog + lessons + difficulties); its per-session entries moved verbatim to
`sim_coverage_log_archive.md`. **Never read the archive in a routine loop** — append new session entries
to the head. Same for `issues_ledger_archive.md` / `manual_validation_debt_archive.md` when routing
findings. See `memory/project_context_economy_split.md`.

## The bright line (read first)

The pass criterion is **a comparable prediction with a property oracle** — anchor held, deflection along field,
descriptors agree within tol — never "the engine ran" or "a wrapper exists". End your log row with
**"Comparable prediction gained, not just a run: ___."**

**Three-Layer Law is absolute:** every engine output is Physical/display-only. Anchors + field specs are
job-request annotations, never `Design` edits; CanDo extra-base/linker *elements* derive from existing topology
metadata, not topology mutations. Any confusion about DNA topology/polarity/which-layer → **ask the user first,
implement nothing.**

## Steps

1. **Resume.** Read the `▶` handoff in `SIM_COVERAGE_PLAN.md`, `git log -5`, and `sim_coverage_plan.json`. Run
   `just smoke` (or the task-relevant fast check) **before new work** to surface any prior-session regression.
2. **Pick + justify.** Eligible = `status=="pending"` tasks whose every `dep` is `"done"`. Apply the rubric
   (§"Manager decision rubric" in the plan): shared-metric track leads; anchors-before-field; rank by
   `coverage-gap × cross-val-value / effort` + milestone-unblock bonus; finish in-progress tracks first. If a
   `<TASK-ID>` arg was given, use it (verify deps). **State: "Picking `<ID>` — `<one-line why>`."**
3. **Investigate.** `rg` the real seams for this engine/feature; confirm the plan's named functions/routes still
   exist (a read-only subagent if it spans many files). Load only the relevant `memory/project_*.md` topic
   file(s) for this engine — not everything.
4. **Oracle first.** Write the property-asserting oracle (or its skeleton) before the feature. Set the task
   `status="in_progress"` in the JSON.
5. **Build.** Module-first (`initX({deps})→{api}` / `backend/core` service; core imports no `backend/api`).
   `main.js` = imports + factory init + thin wiring only (cite LOC Δ). Metrics reuse the shared card machinery
   (generate → view → export PNG/CSV; mirror `project_oxdna_metrics_card.md`) — never rebuilt.
6. **Fast/slow tag.** Fast: oracle math, descriptors, card helpers, conf-emission. Slow (register in
   `tests/conftest.py` `_SLOW_MODULES`/`_SLOW_TESTS`): real oxDNA CUDA / NAMD / mrDNA ARBD / CanDo-nonlinear-on-
   large runs. Keep `just test-fast` fast.
7. **Gate.** Oracle green; `just test` (or `just test-fast` for fast-only — say which) + `just lint`;
   `just test-frontend` + `just smoke` for stateful frontend. Cite pass counts; flag drops.
8. **Display-vs-oracle (per new validation/card).** One-off Playwright: doc-pinned design → run/mock engine →
   open card → **scrape displayed numbers/graph, assert == headless oracle within tol** + screenshot. **If they
   diverge, STOP and ask the user** (the display may measure something the oracle doesn't). Delete the spec;
   file an `MV-N` row in `manual_validation_debt.md`.
9. **Review.** Fresh-context read-only subagent: "review the diff against this task's plan entry — correctness +
   does it satisfy the stated oracle; flag only real gaps, not style."
10. **Commit (auto → master).** Gates green → one commit `feat(<engine>-coverage): <task> + <oracle>` + co-author
    trailer. **No push.** Not-green → don't commit.
11. **Record.** JSON `status="done"` (+ `notes`); update milestone status. Append a `sim_coverage_log.md` entry
    (+ oracle-catalog row if reusable) and a `sim_coverage_metrics.md` row (with the justification sentence; add
    a cross-engine agreement-table row if a comparison ran). **Overwrite** the `▶` handoff (≤8 lines). Route: bug
    → `issues_ledger.md`; can't-headless pixel op → `MV-N`; stuck → `status="blocked"` + `notes` + difficulty
    log, then pick another eligible task or ask.

## Don't

- Don't mark `done` without the oracle passing (evidence, not assertion). Don't edit/remove tests to go green.
- Don't add/remove/reorder/rewrite JSON tasks — **status + notes only**. Scope changes need the user.
- Don't rebuild the metrics-card machinery; bind the shared factory. Don't grow `main.js` with cohesive logic.
- Don't spawn implementer swarms — single main loop + read-only investigation/review subagents.
- Don't write engine output back to topology. Don't reason geometrically about crossovers/polarity — ask first.
- Don't run broad Playwright in the routine cycle (one-off, deleted, then `MV-N`). Don't push to remote.
- Don't do more than one task. Overwrite the handoff before finishing.
