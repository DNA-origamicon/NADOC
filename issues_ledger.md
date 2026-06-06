# Issues & bugs ledger — "fix next issue" loop

**Purpose.** A prioritized backlog of UX bugs / tech-debt, run as a tight per-session loop that
mirrors the `main.js` carve-up (`main_js_carveup.md` + `main_js_extraction_log.md`). One **phase** per
session; large issues decompose into phases. The metrics + difficulties ledger live in
`issues_fix_log.md`. Run each session FRESH (token cost scales with conversation length) — these two
files carry all the state a cold session needs.

**The core discipline (what makes this different from "just fix it"):**
1. **Reproduce + pin with a test FIRST**, before proposing any change. A bug you can't reproduce on
   demand, you can't prove you fixed. Write a failing repro (gesture e2e via `e2e/helpers/scene_harness.js`,
   or a unit test) — or, if a gesture is impractical to automate, a written **USER TODO** repro the user
   confirms. The repro is the acceptance test.
2. **THEN ask the user what behavior they want** (`AskUserQuestion`) — do NOT assume the fix. Several of
   these are UX-design calls, not mechanical bugs; the wrong "obvious" fix wastes a session. Ask after you
   can demonstrate the current behavior, so the question is concrete.
3. **Implement ONE phase**, gated like the carve-up (vitest green → smoke → app exercise).
4. **Update this ledger + the fix log** on the way out (check the phase box, correct stale notes,
   overwrite the handoff, add a metrics row).

> ⚠ **Same map-trust rule as the carve-up:** the "suspected locations" under each issue are *leads to
> verify*, not facts. Read the code and re-derive the real surface before investing. Locations were
> grepped 2026-06-05 and drift as modules move.

---

## Session kickoff prompt (paste at the start of a fix session)

```
Address the next issue in issues_ledger.md (the "fix next issue" loop).

READ FIRST, in order:
1. issues_ledger.md — START with the "Next-session handoff" block (names the recommended
   issue + phase). Then read that issue's dossier.
2. issues_fix_log.md — conventions + difficulties ledger (don't repeat a logged dead-end).
3. .claude/rules/main-init.md — the module map + test harness + "don't grow main.js" rules.

PROTOCOL (do not skip step 1-repro or step 2-ask):
1. Reproduce the bug and PIN IT WITH A TEST (failing gesture e2e / unit test, or a written
   USER TODO repro the user confirms). Demonstrate the current broken behavior before touching code.
2. ASK the user what behavior they want (AskUserQuestion) — these are UX calls, not just
   mechanical bugs. Do not assume the fix.
3. Implement ONE phase. Route the fix through the already-extracted module that owns the code
   (ui/ scene/ app/), NEVER back into the main() closure — see "Don't grow main.js" below.
4. GATE: just test-frontend green (≥1 test pinning the fix) → just smoke → one app exercise.
5. Update issues_ledger.md (check the phase box, fix stale notes, overwrite the handoff) +
   add a row to issues_fix_log.md.

HARD RULES: git pull --rebase origin master before starting; don't push/amend; one phase per
commit; don't touch _PHASE_*, backend topology invariants, or rendering invariants without
asking. Use `rg` not `grep` on main.js (grep treats it as binary — silently returns nothing).
```

---

## Don't grow main.js (the prime directive of this loop)

main.js is the worst structural debt in the repo and the carve-up loop is actively shrinking it
(16.5k → 9.6k LOC). A bug-fix session must NOT undo that. Rules:

- **Fix in the module that owns the code, not in main.js.** Most of these subsystems are already
  extracted (`ui/selection_filter.js`, `scene/assembly_pointer.js`, `app/lifecycle.js`,
  `ui/primitives/context_menu.js`, …). The fix + its test belong there.
- **If the buggy code is still inline in main.js:** prefer **extract-then-fix** (do the carve-up
  extraction for that region first, per `main_js_carveup.md`, then fix in the new module). If the
  extraction is out of scope for the session, make the **minimal inline patch** and log the region as a
  future extraction target in `main_js_carveup.md`. Never add a *new* cohesive block to the closure.
- **Every fix gets ≥1 test** that fails before and passes after (the repro from step 1, promoted to a
  committed test). Pure logic → vitest; gesture → `scene_harness` e2e; un-automatable → a USER TODO the
  user signs off (logged as such, mirroring the carve-up's accepted caveats).
- **Reuse the harness:** `src/test-helpers/{mock_store,factory_dom}.js`, `e2e/helpers/scene_harness.js`,
  `just smoke` (console-error + teardown gates), `just test-frontend-watch` for the tight loop.

---

## Priority / sequencing

Ordered for the loop. Functional bugs with a bounded surface come before big UX overhauls that need
design decisions + research (so early sessions build the loop's muscle on tractable wins).

| Order | Issue | Type | Size | Needs UX research? |
|-------|-------|------|------|--------------------|
| 1 | ~~**ISSUE-3** Assembly Ctrl-click multi-select~~ ✅ DONE 2026-06-05 | functional bug | small, bounded | no |
| 2 | **ISSUE-2** Cross-tab sync delay + console clutter | functional bug (data-integrity) | medium | no |
| 3 | **ISSUE-1** Context-menu proliferation | UX + tech-debt | large, multi-phase | yes |
| 4 | **ISSUE-4** Drill-selection overhaul | UX redesign | large, multi-phase | yes (most) |

This order is a recommendation; the user may name a different issue. ISSUE-2 overlaps the autosave
validation backlog (see `main_js_extraction_log.md` #55 + the validation TODOs) — doing it also discharges
that debt.

---

## ISSUE-1 — Too many context menus (UX + tech debt)

- **Status:** `[ ]` not started.
- **Symptom (user):** for any right-clickable location there are often multiple/overlapping context-menu
  items; the UX is confusing. Needs unification + revision.
- **Repro (to pin):** right-click each target type (bead/strand, overhang, blunt end, empty space,
  assembly part, cadnano grid, spreadsheet row, plate well) and catalogue the menu(s) shown + duplicate /
  conflicting items. A written inventory table IS the repro here (this is a survey bug, not a single
  broken gesture).
- **Suspected locations (verify):** there's a shared primitive `ui/primitives/context_menu.js`
  (`createContextMenu`) but it's inconsistently used. Distinct `contextmenu` listeners live across
  `scene/selection_manager.js`, `scene/assembly_pointer.js`, `ui/assembly_context_menu.js`,
  `scene/empty_space_menu.js`, `scene/slice_plane.js`, `scene/domain_ends.js`,
  `scene/cross_section_minimap.js`, `ui/overhang_pathview.js`, `ui/spreadsheet.js` (×4),
  `ui/plate_view.js`, `ui/strand_length_histogram.js`, plus the cadnano-editor (`pathview.js`/
  `sliceview.js`). **≥12 independent menu builders** — that's the tech debt.
- **Decomposition into phases (proposal — confirm with user before committing to it):**
  - **Phase 1 — inventory + design.** Build the full right-click → menu(s) → items table. Identify the
    duplicates/conflicts. ASK the user which items belong where, what should merge, what's dead. Output: a
    target menu spec (no code). *This phase is the "ask" — it gates all later phases.*
  - **Phase 2 — unify the primitive.** Migrate every builder to `createContextMenu` with one consistent
    structure (positioning, dismissal, sectioning, keyboard). No behavior change yet — pure consolidation
    + tests. Shrinks the per-site boilerplate.
  - **Phase 3+ — apply the spec.** One target-type per phase: revise its menu to the agreed spec, remove
    dead/duplicate items, add a factory test per menu.
- **UX research (starting points, NOT decided):** progressive disclosure (show the 3-4 common actions,
  "More…" for the rest); consistent ordering (primary action top, destructive bottom, separated);
  context-scoped sections vs one flat list; avoid menus that differ only by which layer was clicked.
  Research deliverable, if the user wants it: a short comparison of how Blender / Figma / cadnano-style
  tools scope right-click actions to the hovered object. Park it in this dossier when produced.
- **Open questions for the user (ask in Phase 1, after the inventory):** which menus feel redundant?
  Is a single unified menu-per-object-type the goal, or fewer-but-still-multiple? Any items that should
  move to the left/right sidebar instead of a context menu?

## ISSUE-2 — Cross-tab sync claims saved but doesn't sync (functional, data-integrity)

- **Status:** `[ ]` not started.
- **Symptom (user):** multiple tabs with the same part open both show "saved" but don't actually sync to
  each other for several minutes. Console debug clutter makes it hard to diagnose.
- **Repro (to pin):** open the same workspace-backed part in two tabs (the app spawns a new tab per
  doc — see `shared/doc_id.js`). Edit in tab A; time how long until tab B reflects it. Expected: ~1 s;
  observed: minutes. Capture the console noise. A Playwright two-context spec can drive this
  deterministically (two `browser.newContext()` on the same `?doc`), asserting tab B's design version
  updates within N seconds — that spec is the acceptance test.
- **Suspected locations (verify):** `app/lifecycle.js` `initAutosaveSync` owns the autosave debounce +
  the Library-SSE handler + the cross-tab suppression. Note `_RELOAD_SUPPRESS_MS = 10000` (a 10 s
  same-doc activity window that suppresses reloads) and the design-save debounce (`setTimeout … 900ms`)
  + the `_selfSavedPaths` 5 s self-echo clear. The SSE handler refreshes the **library file list**
  (`libraryPanel.refresh()`), not necessarily the **open design** — cross-tab *design* propagation rides
  the `BroadcastChannel('nadoc-design')` path (`shared/broadcast.js`). **Hypothesis (unproven):** the
  10 s suppression window + the broadcast/SSE split means a sibling tab's edit is suppressed-then-not-
  re-fetched until some later unrelated event. Verify before believing.
- **Console clutter:** there's a `__nadocSyncDebug` helper + a Ctrl+Shift+D debug panel (`ui/sync_badge.js`).
  Part of this issue is gating/quieting the default-on sync logging so the real signal is visible — likely
  a sub-phase.
- **Decomposition into phases (proposal):**
  - **Phase 1 — instrument + repro.** Two-context Playwright repro that measures sync latency; quiet the
    console noise behind the existing debug flag so the trace is readable. ASK the user what the target
    sync latency + console verbosity should be.
  - **Phase 2 — fix propagation.** Based on the confirmed root cause (suppression window? missing design
    re-fetch on broadcast? badge lies about "saved"?), fix in `app/lifecycle.js` + a passing two-context
    spec.
- **UX research:** none needed (functional). The only UX call is "saved" badge honesty — the badge should
  not claim saved+synced if siblings are stale.
- **Open questions (ask in Phase 1):** acceptable sync latency? Should the "saved" badge distinguish
  "saved to disk" from "siblings in sync"? Default console verbosity (silent unless Ctrl+Shift+D)?

## ISSUE-3 — Assembly Ctrl-click multi-select feedback (functional bug)

- **Status:** `[x]` DONE 2026-06-05 (single phase). Fix in `scene/assembly_lasso.js`
  (`toggleInstanceSelection`) + `scene/assembly_multi_box.js` (white-for-1 / purple-for-2+);
  main.js `onClick` re-wired to the pure helper (+1 LOC: a dev-only test oracle). See the fix-log
  row. **User-chosen semantics:** (1) Ctrl+click a 2nd part while one is plain-selected → ADD both
  (the active pick folds into the set); (2) Ctrl+click an already-selected part → deselect just it;
  (3) a single Ctrl-selection draws a WHITE box, purple only at 2+.
- **Symptom (user):** in assembly mode, Ctrl+click on a part shows **no visual change** until a *second*
  part is also selected. And the sequence "click part A, then Ctrl+click part A again" *clears* the first
  selection instead of toggling/keeping it.
- **Repro (to pin):** load a ≥2-part assembly (`workspace/Belt_test1.nass`). (a) Ctrl+click one part →
  assert a selection box/highlight appears immediately (currently does not until #2). (b) Click A, then
  Ctrl+click A → assert A stays selected or toggles predictably (currently clears). Drive via
  `e2e/helpers/scene_harness.js` (`selectAssemblyInstance` / assembly select helpers already exist) +
  `getSelectedObject`-style state assertions — extend `e2e/assembly_select.spec.js`.
- **Suspected locations (verify):** `scene/assembly_pointer.js` (`initAssemblyPointer` → `onAssemblyClick`,
  carve-up #29) handles the click/select; `scene/assembly_multi_box.js` (#34) draws the purple union box
  only at **≥2** selections (that's the "no change until a second part" symptom — single-select feedback is
  suppressed by design there). `scene/assembly_lasso.js` handles Ctrl-modified selection. The
  single-select-no-feedback and the re-click-clears behaviors are likely two distinct bugs in the
  click-handler's selection state machine.
- **Decomposition:** likely a **single phase** (bounded). If the two symptoms have separate causes, split
  into 1a (immediate single-select feedback) + 1b (re-click toggle semantics).
- **UX research:** none — this is standard multi-select semantics (Ctrl/Cmd toggles membership; single
  selection shows feedback immediately). The "ask" is just confirming the desired toggle rule (Ctrl+click
  an already-selected part → deselect just it? no-op? ).
- **Open questions (ask after repro):** should single-part selection show the same purple box as multi, or
  a distinct single-select highlight? Ctrl+click on an already-selected part — deselect it, or keep it?

## ISSUE-4 — Drill selection UX overhaul (UX redesign)

- **Status:** `[ ]` not started.
- **Symptom (user):** the drill-down selection (click into nested levels: assembly → part → cluster →
  strand → bead, or the design-side filter drill) has become a "terrible UX." Needs a from-scratch
  redesign, not a patch.
- **Repro (to pin):** demonstrate the current drill flow end-to-end and catalogue the friction points
  (what's unpredictable, what loses selection, what level you land on, how you escape). A narrated USER
  TODO walkthrough + the user's pain points IS the repro; promote specific broken transitions to e2e
  assertions once the target model is agreed.
- **Suspected locations (verify):** `ui/selection_filter.js` (`initSelectionFilter` + the drill-lock
  state machine `reflectDrillLevel`/`reflectLockOnButtons`/`resetToAutoBaseline`, carve-up #61) +
  `scene/selection_manager.js` (which CALLS the filter's `reflectDrillLevel` from the bead-click drill) +
  `state/store.js` (selectableTypes / drill state). The drill-lock machine was just extracted (#61) — read
  that dossier + the extraction log row first.
- **Decomposition into phases (proposal — confirm):**
  - **Phase 1 — current-state map + target model.** Map every drill transition + the state it mutates.
    Research + propose 2-3 candidate interaction models (see below). ASK the user to pick. Output: an
    interaction spec + a state-machine diagram. No code.
  - **Phase 2 — rebuild the state machine** to the agreed model in `ui/selection_filter.js` /
    `selection_manager.js`, behind a flag if risky, with the e2e repro suite passing.
  - **Phase 3 — polish** (visual affordances for "what level am I on", escape/up-level, keyboard).
- **UX research (needed — this is the most research-dependent issue):** standard hierarchical-selection
  models to compare: (a) **double-click to drill in / Esc to pop out** (Figma groups, Blender object→edit);
  (b) **persistent breadcrumb** of the current drill level with click-to-jump; (c) **modifier-scoped**
  (Alt = drill one level under cursor). The current design is a "drill-lock" toggle model that the user
  finds terrible — the research should articulate *why* (mode confusion? hidden state? no escape?) and what
  replaces it. Produce a short written comparison before Phase 1's ask. Park it in this dossier.
- **Open questions (ask in Phase 1):** what does "drill" need to reach (which levels, in which editor)?
  Is the current *filter* UI (pin a type) part of the problem or separate? Preferred mental model from the
  three above?

---

## Next-session handoff

_Living pointer — each session overwrites this. Last updated 2026-06-05 (ISSUE-3 shipped)._

**Recommended next: ISSUE-2 (Cross-tab sync delay + console clutter) — Phase 1 (instrument + repro).**
It's the next priority (medium, functional, no UX research) and overlaps the autosave-validation backlog
(`main_js_extraction_log.md` #55), so doing it discharges that debt too.

**Do FIRST (Phase 1):** open the same workspace-backed doc in two browser contexts on the same `?doc`
(the app spawns a tab per doc — `shared/doc_id.js`), edit in tab A, measure how long until tab B reflects
it (expected ~1 s; observed minutes). A two-`browser.newContext()` Playwright spec is the acceptance test —
assert tab B's design version updates within N seconds. Capture the console noise. Suspected owner:
`app/lifecycle.js` `initAutosaveSync` (note `_RELOAD_SUPPRESS_MS = 10000`, the 900 ms save debounce, the
`_selfSavedPaths` 5 s self-echo clear, and the SSE-refreshes-library-list-not-open-design / BroadcastChannel
split — `shared/broadcast.js`). **Then ASK** the Phase-1 questions in the ISSUE-2 dossier (target latency?
should the "saved" badge distinguish disk-saved vs siblings-in-sync? default console verbosity?).

**Gotchas banked:**
- `grep` treats `frontend/src/main.js` as binary and silently returns no matches — use `rg` or `grep -a`.
- **`getInstanceCenters()` IS populated on the shared (default) renderer for a real loaded `.nass`** (62
  for Belt_test1) — the `scene_harness.js` comment "empty on the shared path" only holds for freshly-built
  INLINE designs (empty `instBoundingBox`). So assembly union-box / center-based features DO work in the
  real app; they just can't be asserted in the inline-fixture e2e (`loadAssemblyWithParts`). Use
  `__NADOC_DBG__.{store,assemblyRenderer}` + `importAssembly` to exercise center-dependent rendering on a
  real fixture (see how ISSUE-3 was app-verified).
- The assembly move/rotate gizmo auto-arms on plain-click (`activateTranslateRotateTool`) and OCCLUDES
  nearby parts in the tight `loadAssemblyWithParts` fixture — so "plain-click A then Ctrl+click a DIFFERENT
  part B" can't be driven in that e2e. Pin that branch with a unit test instead (ISSUE-3 did:
  `toggleInstanceSelection`).
