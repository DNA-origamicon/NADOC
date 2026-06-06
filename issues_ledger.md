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
| 2 | ~~**ISSUE-2** Cross-tab sync delay + console clutter~~ ✅ DONE 2026-06-05 (propagation fix + silent-logging C + badge co-editing B all shipped) | functional bug (data-integrity) | medium | no |
| 3 | **ISSUE-1** Context-menu proliferation — Phase 1 ✅ + Phase 2a-binding ✅ + Phase 2a-orientation ✅ DONE 2026-06-05; Phase 2a-blunt / 2b–2e + Phase 3+ open | UX + tech-debt | large, multi-phase | yes (done) |
| 4 | **ISSUE-4** Drill-selection overhaul | UX redesign | large, multi-phase | yes (most) |

This order is a recommendation; the user may name a different issue. ISSUE-2 overlaps the autosave
validation backlog (see `main_js_extraction_log.md` #55 + the validation TODOs) — doing it also discharges
that debt.

---

## ISSUE-1 — Too many context menus (UX + tech debt)

- **Status:** Phase 1 `[x]` DONE 2026-06-05 (inventory + spec). Phase 2 `[~]` IN PROGRESS — **2a-binding `[x]` DONE 2026-06-05** (overhang-binding menu migrated); **2a-orientation `[x]` DONE 2026-06-05** (overhang-orientation menu migrated → `ui/overhang_orientation_menu.js`; primitive gained a `{ type:'custom', el }` passthrough for the rep flyout; main.js −83 LOC; 16 vitest tests); 2a-blunt `[ ]`, 2b–2e `[ ]`. Phase 3+ `[ ]` (content cleanup).

### Phase 1 OUTPUT — inventory + target spec (banked 2026-06-05)

**Inventory (18 builders, 3 editors; only 3 use the shared `createContextMenu` primitive):**

| Target | File | Primitive? | Editor | Items |
|--------|------|-----------|--------|-------|
| Assembly part instance | `ui/assembly_context_menu.js:52` | bespoke | Assembly | Repr, Move/Rotate, Define Connector, Fixed, Allow Part Joints, Show/Hide, Edit Part, Duplicate, Polymerize, Group, Ungroup, Delete |
| Assembly linker | `scene/assembly_pointer.js:554` | ✅ shared | Assembly | (header), Relax linker |
| Assembly belt path | `scene/assembly_pointer.js:605` | ✅ shared | Assembly | (header), Attach part to belt |
| Blunt end ring | `main.js:2897` | bespoke | Design | Extrude, Bend, Twist |
| Overhang orientation | `main.js:2813` | bespoke | Design | Edit/Reset Orientation, Set Label, Generate OH binding strand, Representation ▸, Open Overhangs Manager, Clear All Overhangs |
| Overhang binding | `main.js:1688` | bespoke | Design | (header), Bind/Unbind, Delete binding |
| Spreadsheet strand row | `ui/spreadsheet.js:362` | bespoke | Design | Go to strand |
| Spreadsheet 5′ cell | `ui/spreadsheet.js:633` | bespoke | Design | Go to strand, Clear sequence |
| Spreadsheet seq cell | `ui/spreadsheet.js:664` | bespoke | Design | Go to strand, Set binder sequence, Clear sequence |
| Spreadsheet 3′ cell | `ui/spreadsheet.js:699` | bespoke | Design | Go to strand, Clear sequence |
| cadnano strand | `cadnano-editor/main.js:1597` | bespoke | Cadnano | Make Active/Reference, Convert to OH binding strand, Convert to scaffold, Edit extensions |
| cadnano crossover/ligation | `cadnano-editor/main.js:1847` | bespoke | Cadnano | Add/Edit extra bases, Delete |
| cadnano overhang | `cadnano-editor/main.js:1488` | bespoke | Cadnano | Set name, Generate binding strand |
| Empty 3D space | `scene/empty_space_menu.js:13` | bespoke | Design | Extrude |
| Plate / pathview / sliceview canvases | `ui/plate_view.js` / `ui/overhang_pathview.js` / `cadnano-editor/sliceview.js` | bespoke | both | (contextmenu *suppressed* via preventDefault only — no menu) |

> ⚠ Locations grepped via Explore 2026-06-05; verify each line before editing (they drift). cadnano `pathview.js:4681` is a *router* that dispatches to the three cadnano builders above — not a 4th menu.

**Duplicates / dead items found:** cross-editor doubles (strand→reference, overhang labeling, generate-binding-strand — design vs cadnano, implemented twice w/ different UX); "Go to strand" ×4 + "Clear sequence" ×3 in spreadsheet; global/bulk actions ("Open Overhangs Manager", "Clear All Overhangs") hanging off a single-overhang menu; z-index sprawl (1000→9999→10000); 3 different dismissal mechanisms.

**TARGET SPEC (user AskUserQuestion decisions, 2026-06-05 — these gate Phases 2–3):**
1. **Shape = fewer-but-still-multiple.** NOT one-unified-menu-per-type. Goal is to cut redundant menus + dead items and make the surviving menus consistent — not to collapse everything into a single per-type menu.
2. **Primitive first (Phase 2 = pure migration, NO behavior change).** Migrate all 15 bespoke menus onto `createContextMenu` → one positioning/dismissal/z-index/keyboard impl. ≥1 factory test per migrated builder. Kills the z-index sprawl + 3 dismissal mechanisms. This phase ALSO discharges the inline Assembly-menu carve-up extraction debt (satisfies the interleave rule — `assembly_context_menu.js` is already its own module, so migrating it IS the unification).
3. **Editors stay DISTINCT.** Design vs cadnano keep separate builders; clean up within each editor. Accept the design↔cadnano duplication (strand→reference, overhang labeling, generate-binding-strand stay doubled) — do NOT build a shared cross-editor builder.
4. **Global/bulk actions stay in-menu but in a separated section.** Don't move them to a sidebar. Put global actions (e.g. overhang menu's "Open Overhangs Manager" + "Clear All Overhangs") in a clearly-separated bottom section using the primitive's `separator`/`header`, visually distinct from per-object actions.

**Refined phase plan (post-spec):**
- **Phase 1** ✅ inventory + spec (this).
- **Phase 2 — primitive migration.** All 15 bespoke menus → `createContextMenu`, pure consolidation, ≥1 test each. LARGE — recommend splitting per file-group to keep each session cheap & reviewable: **2a** design-editor main.js menus (blunt-end / overhang-orientation / overhang-binding), **2b** spreadsheet (×4 menus), **2c** `empty_space_menu.js`, **2d** `assembly_context_menu.js` (= the carve-up extraction), **2e** cadnano-editor menus (×3). Each sub-phase: migrate verbatim → factory test → smoke → app exercise. main.js LOC Δ ≤ 0 (menus 2a move OUT of main.js into a module as part of migrating).
  - **2a is itself split (the 3 menus differ a LOT in migration cost — verified 2026-06-05):**
    - **2a-binding `[x]` DONE 2026-06-05** — overhang-binding menu → `ui/overhang_binding_menu.js` (clean dynamic builder, header + Bind/Unbind + Delete). Required a tiny reusable `danger` flag on the primitive (`context-menu__item--danger` + CSS). main.js −81 LOC. 9 vitest tests.
    - **2a-orientation `[x]` DONE 2026-06-05** — overhang-orientation menu → `ui/overhang_orientation_menu.js` (Edit/Reset Orientation, single-overhang Set Label/Generate, rep flyout, Open Manager, Clear All danger). Extended `createContextMenu` with a reusable `{ type:'custom', el }` HTMLElement passthrough (the rep flyout from `createRepresentationMenuItem` rides in as a custom item — `selection_manager.js:420` uses the same flyout and is now a cheap future migration). main.js −83 LOC. 16 vitest tests (12 menu + 4 primitive-custom-item). `danger` flag covers "Clear All Overhangs".
    - **2a-blunt `[ ]`** — blunt-end menu is NOT a builder: a **static HTML element** `#blunt-end-ctx-menu` (index.html) with three heavy pre-wired handlers (`blunt-extrude/bend/twist-btn-ctx` at `main.js:~2974`, bodies launch slice-plane / deform tool / set mode-indicator). Converting → dynamic `createContextMenu` means moving those 3 handler bodies + deleting the static element. Largest & riskiest of the 3 — do it as its own phase.
- **Phase 3+ — content cleanup (one target-type per phase).** Apply the spec: separate the global section in the overhang menu (decision 4), normalize "Go to strand"/"Clear sequence" labels+ordering in spreadsheet, remove any dead/unguarded items (e.g. cadnano "Generate binding strand" already-bound guard), consistent ordering (primary top / destructive bottom). Factory test per revised menu.

### Original dossier (pre-Phase-1 — leads, superseded by the inventory above)
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

- **Status:** ✅ FULLY CLOSED 2026-06-05. Propagation fix `[x]`; silent-by-default sync logging `[x]`
  (console mirror in `ui/sync_badge.js` `syncLog` gated on the debug panel being open — Ctrl+Shift+D /
  `__nadocSyncDebug.show()` enables it, close/hide silences; rolling in-panel log still records every
  event); badge co-editing (stale-sibling) indicator `[x]` DONE 2026-06-05.
- **Sub-phase B (badge co-editing indicator) — SHIPPED 2026-06-05.** User-chosen scope (AskUserQuestion):
  trigger = **co-editing PRESENCE** (no content-version counter exists, so flag whenever another tab holds
  the SAME workspace file in a DIFFERENT backend doc — the real save-clobber risk); visual = **distinct
  dot + label** (a blue `coedit` dot + `saved · N tab(s) editing this file`, only at the resting green
  "saved" state — an active save/error keeps its own colour). Implementation: `ui/sync_badge.js` composes
  base status + a sibling count via a new `setSiblingCoediting(count)` + `_render()`, plus a pure exported
  `countCoeditingSiblings(myPath, myDocId, others)` (excludes same-docId child windows = genuinely in-sync).
  main.js wiring: `doc-presence` broadcast now carries `workspacePath` (+ stores sibling `docId`);
  `_refreshCoediting()` recomputes the count on presence/goodbye/own-path-change; new `doc-goodbye` emit on
  `beforeunload` keeps the count honest when a sibling closes; `_setWorkspacePath` re-announces + refreshes.
  Pinned by 13 vitest tests (`ui/sync_badge.test.js`: 7 badge-render + 6 detector). App-validation =
  two-real-tab USER TODO (BroadcastChannel can't cross Playwright contexts — same constraint as the
  propagation fix). main.js LOC Δ +~22 (thin wiring across existing blocks, not a new cohesive subsystem).
- **ROOT CAUSE (confirmed by code trace, 2026-06-05):** two independently-opened tabs get
  *different* sticky doc ids (`doc_id.js` mints one per tab in `sessionStorage`). So the fast path
  (`design-changed` BroadcastChannel) is doc-scoped out (`isSameDoc` false → `main.js` ignores it),
  AND the fallback (SSE `file-changed` → reload) was suppressed because `main.js`'s `file-saved`
  broadcast handler added the path to `selfSavedPaths` **regardless of doc**. Each save re-armed the
  5 s self-echo window just before its own SSE, so a sibling's genuine edit was swallowed for minutes.
  The `markSameDocActivity` 10 s window is NOT the culprit (only set on a same-doc `design-changed`).
- **FIX (decision: auto-sync B→A ~1s):** doc-scoped the echo guard. New
  `initAutosaveSync.registerSiblingSave(path, sameDoc)` in `app/lifecycle.js` suppresses ONLY a
  same-doc sibling's save (stale echo we already sync via design-changed); a different-doc sibling's
  `file-saved` is left un-suppressed so the SSE `file-changed` reloads it. `main.js` `file-saved`
  handler now calls it with `nadocBroadcast.isSameDoc(data)` (−4 main.js LOC). Pinned by 3 vitest
  tests in `app/lifecycle.test.js` (same-doc suppresses; different-doc reloads = the repro; 5 s clear).
- **User decisions banked (2026-06-05 AskUserQuestion):** (1) same-file tabs auto-sync ~1s [DONE];
  (2) the "saved" badge SHOULD distinguish disk-saved from siblings-in-sync (flag stale siblings)
  [sub-phase, not built]; (3) sync console logging silent by default, verbose only behind
  Ctrl+Shift+D / `__nadocSyncDebug` [sub-phase, not built].
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

_Living pointer — each session overwrites this. Last updated 2026-06-05 (ISSUE-1 Phase 2a-orientation done — overhang-orientation menu migrated)._

**ISSUE-2 + ISSUE-3 closed. ISSUE-1 Phase 1 + Phase 2a-binding + Phase 2a-orientation done.** 2a-orientation
migrated the overhang-orientation menu onto `createContextMenu` (`ui/overhang_orientation_menu.js`, main.js
−83 LOC, 16 tests) and extended the primitive with a reusable `{ type:'custom', el }` HTMLElement passthrough
(the only way to embed the rep hover-flyout). Recommended next pick, in cost order:

- **ISSUE-1 Phase 2a-blunt (next; biggest/riskiest of 2a).** The blunt-end menu is NOT a builder — it's a
  **static HTML element** `#blunt-end-ctx-menu` (index.html) shown/hidden by `_showBluntCtx`/`_hideBluntCtx`
  (`main.js:~2735` after this commit) with three heavy pre-wired ctx-button handlers
  (`blunt-extrude/bend/twist-btn-ctx`, bodies launch slice-plane / deform tool / set mode-indicator).
  Migrating → dynamic `createContextMenu` means moving those 3 handler bodies into the module AND deleting the
  static element from index.html. Own phase. The `danger` flag + `{type:'custom'}` passthrough are both
  available now if needed. ⚠ note the handler bodies call closure helpers (`_hideBluntPanel`, `startToolAtBp`,
  `slicePlane`, `deformView`, `_clusterDeformGuard`, `expandedSpacing`) — pass them as deps / lazy getters.
- **ISSUE-1 Phase 2b–2e (spreadsheet ×4 / empty-space / assembly / cadnano ×3).** Remaining bespoke menus.
  2b (spreadsheet) is self-contained in `ui/spreadsheet.js`; 2d (assembly) also discharges the carve-up
  extraction debt. Pick any — each is its own cheap phase.
- **ISSUE-4 — Drill-selection overhaul (alternative, no-code Phase 1).** Map every drill transition + the
  state it mutates (`ui/selection_filter.js` drill-lock machine #61 + `scene/selection_manager.js`), propose
  2-3 interaction models, ASK the user to pick. Cheap cold-session starter if you'd rather not start code.

**Primitive now supports:** `danger` (`{ label, onClick, danger: true }` → red `.context-menu__item--danger`)
AND `{ type:'custom', el }` (caller-owned HTMLElement passthrough — for flyouts/widgets the flat-item model
can't express; clicks inside it do NOT auto-dismiss, wire that in the el). Reuse both in remaining migrations.

**App-validation gap banked for 2a-orientation:** the live right-click-on-an-overhang gesture is a **USER TODO**
(numbered steps in the fix-log row) — driving a WebGL raycast right-click on a rendered overhang sprite isn't
automatable here. The boot/wiring path IS exercised by `just smoke`'s console-error gate (loads a real design
with the changed main.js, zero errors); the rendered items / single-vs-multi gating / danger / rep-flyout
passthrough / api-wiring are pinned by the 16 vitest tests. **Pure migration — zero intended behavior change**
(same items, same actions; only positioning/dismissal/z-index now come from the shared primitive, which ALSO
adds Escape + scroll dismissal that the bespoke menu lacked).

**ISSUE-1 spec recap (banked from the user, so Phase 2/3 don't re-ask):** fewer-but-still-multiple (not
one-menu-per-type); primitive-first then content; editors stay distinct (accept design↔cadnano duplication);
global/bulk actions stay in-menu in a separated bottom section (not moved to a sidebar). Full spec + inventory
table + refined phase plan are in the ISSUE-1 dossier above.

**Sub-phase B notes for whoever audits the badge next:** `ui/sync_badge.js` now composes TWO orthogonal
signals via `_render()` — the base sync status (`setSyncStatus`) and a co-editing sibling count
(`setSiblingCoediting`); the co-edit annotation only paints over the resting green "saved" state, so don't
assume `dot.className` is `sync-dot <state>` anymore (it can be `sync-dot coedit`). The `debugLogging`
gate (sub-phase C) is untouched and must stay panel-tied. The pure `countCoeditingSiblings` deliberately
EXCLUDES same-docId siblings (cadnano child windows share our backend doc = genuinely in-sync).

**Gotchas banked:**
- **Two-context Playwright canNOT reproduce ISSUE-2.** `BroadcastChannel` does NOT cross Playwright
  browser contexts, so tab B never receives tab A's `file-saved` echo → `selfSavedPaths` never gets the
  path → the SSE reload fires even on the OLD code. The bug only manifests between two REAL same-browser
  tabs (shared BroadcastChannel) that hold DIFFERENT sticky doc ids. Pin the logic with the
  `registerSiblingSave` unit tests; app-verify with the two-real-tab USER TODO in the ISSUE-2 dossier.
- **doc-id model:** independently-opened main-app tabs each mint a sticky per-tab id (`doc_id.js`), so
  "same file in two tabs" ⇒ two different backend docs. Same-doc only happens for child windows opened
  with an inherited `?doc=` (cadnano editor, part editor).
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
