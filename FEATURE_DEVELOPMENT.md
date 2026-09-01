# Feature Development — module-first guardrails (anti-backslip)

**Why this exists.** The carve-up loop (`main_js_carveup.md`) spent dozens of sessions shrinking
`frontend/src/main.js` from ~16,530 lines to ~7,500 by lifting cohesive subsystems into their own tested
modules. That god-file was the worst structural debt in the repo. **The moment feature work resumes, the
default failure mode is re-growing it** — a "quick" panel, dialog, or handler dropped inline because it's
faster than making a module. This document is the law that prevents that. Read it before adding any
feature; it is referenced from `CLAUDE.md` (always loaded).

The carve-up, the bug-fix loop (`issues_ledger.md`), and feature work all obey **one law:**

> **`main.js` (and any composition root) only ever gains: imports, ~one-line factory inits, and thin
> per-action wiring. Never a new cohesive logic block inside the `main()` closure.**

This is Michael Feathers' **Sprout Method / Sprout Class** (*Working Effectively with Legacy Code*): when
you must add behavior to a large file, write the new logic as a *separate, fully-tested* unit and inject a
single call from the messy code — only the call site stays in the closure. It is the same discipline as
the carve-up's extraction, applied *before* the code is ever written instead of after.

---

## Pre-flight (decide BEFORE writing the feature)

1. **Will this add more than ~15 lines of cohesive logic to `main.js`** (or any file already >1k lines)?
   → Build it as a module first, then wire a single init line. Don't "write it inline and extract later" —
   later rarely comes, and that's exactly how the 16.5k file happened.
2. **Does the feature own state** (its own `let`s, a cache, a `store.subscribe`, DOM element refs)?
   → It's a **factory**: `initX({ deps })→{ api }`. Mirror a proven one — `scene/measurement_tool.js`,
   `ui/file_io.js`, or the most recent `scene/protein_subsystem.js` (#85). Pure cores (math/data shaping,
   decisions) come out as **separately-tested pure functions** (e.g. `scene/*_math.js`, `coloring_modes.js`).
3. **Does it have a "does it look/behave right" gesture or visual** that automated tests can't cover?
   → Plan a `manual_validation_debt.md` entry up front (you'll push an `MV-N` row when you ship it).
4. **Reuse the construction mechanics the carve-up proved** — don't re-derive them:
   - Factory-init **placement** (deps-below-banner, lazy-let, lazy getters): `.claude/rules/main-init.md`.
   - **Alias-const** wiring (`const _x = _module.x`) keeps existing call sites byte-identical when you also
     touch nearby code.
   - **Subscription-order** rule (store fires in registration order) — register a new subscriber at the
     correct point in `main()`; reordering silently breaks position-overlay invariants. See `main-init.md`.
   - **Frame-callback / TDZ** landmines (a frame callback that reads a later-declared `const` kills the
     render loop) — `main-init.md`.
5. **Does an equivalent feature already exist in part or assembly mode?**
   → Treat the existing behavior as the parity specification, not merely as visual inspiration. Inventory
   its full user-visible and persisted contract before coding: controls and advanced options, defaults,
   enablement, validation, progress/cancel/resume, results and visualization, errors, undo/history,
   save/reload, export, and downstream job behavior. Put reusable behavior behind one shared domain or
   controller API; add a thin host adapter for design vs selected assembly target. See
   `memory/project_assembly_feature_parity.md`.

## Gate (same bar as the carve-up + fix loops)

- **≥1 vitest per pure function** (input→output, oracle from the spec — for *new* code this is genuine
  test-first, the strongest case; there's no verbatim-vs-adapted question because nothing was moved).
- **jsdom factory test** for the stateful module (drive its API + subscribers via `createMockStore` +
  `mountIds` + mock deps; assert the *observable* contract — rendered output / exposed API / clean
  teardown — not internal call order, so the test survives the next refactor).
- **Stateful (DOM/scene/store)** → one **app exercise** + `just smoke` (console-error + teardown gates).
- **Canvas-gesture** behavior → a `scene_harness` gesture e2e (real raycast, assert on exposed state),
  *or* an `MV-N` manual-validation row if it's a Tier-3 "looks right" check (golden-image stays manual).
- **Backend change** → `just test` (no exceptions).
- **`just lint`** delta ≤ 0.

## The ratchet (the anti-backslip trigger)

`main.js` LOC is a **one-way ratchet**: a feature commit must leave it **flat or lower**. A net rise
greater than the genuine wiring cost (one import + one factory init + one thin handler ≈ a handful of
lines) is the smell that a cohesive block crept into the closure — **extract it into its module before
committing.** Cite the `main.js` LOC Δ in every feature's done message, exactly as the carve-up log does.

Current ceiling reference: **~7,500 lines (2026-06).** If `main.js` is materially above this after a
feature, something regressed the carve-up. *(Optional hard enforcement, when CI exists: a tiny vitest /
`just` check that fails if `wc -l frontend/src/main.js` exceeds a pinned ceiling — a literal ratchet. Not
wired yet; the documented rule + the LOC-Δ-in-done-message habit is the current guard.)*

## What legitimately lives in `main.js` (the irreducible composition root)

Per the carve-up endgame note: imports (~146), module constructions / factory inits (~100), the
**lifecycle spine** (`_resetForNewDesign` / `_enterAssemblyMode` / `_exitAssemblyMode`), `_setMenuToggle`
(43-use shared util), and thin per-action wiring. This is the ~2,500–3,500-line floor — *supposed* to know
about many things because it's where modules are assembled. Don't try to extract it further (diminishing
returns); just don't let *new cohesive logic* join it.

## When a feature must touch buggy or still-inline code

- **Extract-then-feature:** if the region you need is still a cohesive inline block, do its carve-up
  extraction first (per `main_js_carveup.md`), then build the feature in the new module. If that's out of
  scope for the session, make the **minimal inline patch** and log the region as an extraction target in
  the carve-up map. Never add a *new* cohesive block to the closure to get the feature done.
- **A bug you trip over while building** → push an `ISSUE-N` dossier into `issues_ledger.md` (+ a fix-log
  row, `[x]` if fixed same session). **A gesture/visual you ship without a live hand-check** → push an
  `MV-N` row into `manual_validation_debt.md`. (Same cross-loop intake the carve-up uses — see
  `issues_ledger.md` "Intake" + `manual_validation_debt.md` "Intake".)

An existing mode guard is not a specification. In particular, do not preserve or add
`if (assemblyActive) return`, disabled assembly controls, or “not available in assembly mode” solely
because the assembly adapter has not been written yet. Establish whether there is a real ownership,
topology, or measured scale constraint. Otherwise wire the shared behavior through the assembly host.

## The design-automation loop (a feature loop that runs ON this law)

`design_automation_backlog.md` + `design_automation_log.md` (invoked by **`/automate-feature`**) are a
feature-development loop in the carve-up family: each session gives one UI-only / API-less operation a
**programmatic (headless) entry point + a reusable validation oracle**, building toward automated
validation and eventual text-to-DNA-origami. It is bound by *this* document — new code lands in
`headless_build.py` / a new `headless_*_build.py` / `backend/core`, never in a god-file. Its anti-shovel
metric is **"validation gained, not just a passthrough"** (an oracle that asserts a property of the result),
the analog of the carve-up's back-import-surface gate. Read its backlog's `## Next-session handoff` to start.

## Cross-references

- Construction mechanics + init/subscription order: `.claude/rules/main-init.md`
- Carve-up endgame / what's irreducible / map-trust rules: `main_js_carveup.md`
- Bug loop (repro-first, ask-first, root-cause + reopen tracking): `issues_ledger.md` + `issues_fix_log.md`
- Manual-validation debt (SBTM-style charters, risk-ordered): `manual_validation_debt.md`
