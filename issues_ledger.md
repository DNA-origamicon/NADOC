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
   can demonstrate the current behavior, so the question is concrete. **Capture the user's answer AS the
   test** where you can — the agreed Given/When/Then *is* the repro from step 1 (specification by example),
   so "what they wanted" and "what now can't regress" can't drift apart.
3. **Implement ONE phase**, gated like the carve-up (vitest green → smoke → app exercise).
4. **Update this ledger + the fix log** on the way out (check the phase box, correct stale notes,
   overwrite the handoff, add a metrics row). **DoD — record the root cause** (one 5-Whys line) **and the
   failed hypothesis** if you chased a wrong fix first, in the fix-log's Root-cause log; if the bug is a
   *class*, add a `LESSONS.md` entry. **On any reopen, log it + bump the reopen counter** — reopen rate is
   the metric that tells you whether your repro + root-cause depth are actually working (a rising rate =
   too-shallow 5-Whys). Distrust a single causal thread: three-layer/topology bugs are usually multi-factor.

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
   add a row to issues_fix_log.md. Record the root cause (5-Whys) + any failed hypothesis in the
   fix-log's Root-cause log; on a reopen, bump the reopen counter. Class-of-bug → LESSONS.md.

HARD RULES: git pull --rebase origin master before starting; don't push/amend; one phase per
commit; don't touch _PHASE_*, backend topology invariants, or rendering invariants without
asking. Use `rg` not `grep` on main.js (grep treats it as binary — silently returns nothing).
```

---

## Don't grow main.js (the prime directive of this loop)

main.js is the worst structural debt in the repo and the carve-up loop is actively shrinking it
(16.5k → ~7.5k LOC). A bug-fix session must NOT undo that. This is one instance of the project-wide
**module-first law** that also governs feature work — see [FEATURE_DEVELOPMENT.md](FEATURE_DEVELOPMENT.md)
(the general statement: `main.js` only ever gains imports + factory inits + thin wiring; a fix/feature
commit leaves its LOC flat or lower). Rules:

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

## Intake — where issues come from

Two sources feed this ledger:
1. **Direct triage** — the user reports a UX bug / tech-debt smell; it gets a dossier here.
2. **Push from the sibling loops (the carve-up + manual-validation loops).** When a carve-up extraction
   session (`main_js_carveup.md`) trips over a bug — in the region it's lifting or adjacent to it — that
   session adds a new `ISSUE-N` dossier here (symptom + repro + suspected location), **even if it fixed
   the bug the same session** (then it also marks the issue `[x]` DONE and adds an `issues_fix_log.md`
   row). This keeps every user-facing bug visible to the fix loop instead of dying in the carve-up's
   *extraction difficulties ledger* (which is for extraction dead-ends only). Likewise a regression the
   manual-validation loop surfaces (`manual_validation_debt.md` → REGRESSION FOUND) opens an issue here.

A bug pushed in already-fixed still earns a dossier + fix-log row — the record is the point.

---

## Priority / sequencing

Ordered for the loop. Functional bugs with a bounded surface come before big UX overhauls that need
design decisions + research (so early sessions build the loop's muscle on tractable wins).

**Rebuilt 2026-08-08.** This table is the authoritative open set. Closed dossiers retained below are
historical only and should move to `issues_ledger_archive.md` during the next archive compaction.

**Active October 15 user override:** finish standard-part geometry first. G1's
ordinary grouping omission is focused-fixed (ISSUE-99); the next item is the
reproduced bend/twist preview lifecycle defect (ISSUE-100). The older ordering
below remains background backlog, not the active geometry delivery sequence.

| Order | Issue | Type | Size | Needs UX research? |
|-------|-------|------|------|--------------------|
| **→ 1** | **ISSUE-22** oxDNA/MD roll-return staleness remains user-confirmed broken after multiple fixes (promoted from MV-OXSTALE). | correctness / workflow | medium | reproduce exact gesture |
| 2 | **ISSUE-23** Assembly animation keyframes persist `configuration_id`, but the playback engine never reads it (promoted from MV-8). | functional bug | medium | no |
| 3 | **ISSUE-21** Exported animation video has three shared-frame-loop defects. | export correctness | medium | no |
| 4 | **ISSUE-19** Scaffold routing may extend through a linker/staple while validation misses the double occupancy. | routing correctness | medium | no |
| 5 | **ISSUE-18** Scaffold helpers can nick/ligate staple strands because two filters are missing. | routing correctness | small | no |
| 6 | **ISSUE-20** Fast-suite timing measures contended wall time and misclassifies healthy tests. | test infrastructure | medium | no |
| 7 | **ISSUE-11** Deformed-continuation helices carry `grid_pos=None`; obvious repair is Three-Layer-sensitive. | data model | small if approved | decision required |
| 8 | **ISSUE-8** Multi-section autoscaffold end-turn policy remains decision-gated; re-probe reachability before accepting the old “default-off” claim. | routing correctness | medium | decision required |
| 9 | **ISSUE-13** Strand-end resize still uses the questioned axis endpoint convention. | geometry | small | ask-first |
| 10 | **ISSUE-12** `cluster_create` still falls through the generic move/rotate feature-log branch. | functional bug | small | no |
| 11 | **ISSUE-1** Context-menu consolidation remains a large multi-phase UX program. | UX / debt | large | decisions banked |
| 12 | **ISSUE-59** Creating an all-helix cluster drops the lattice placement cluster and produces a saved design that cannot reload. | persistence / cluster correctness | triage | no |
| 13 | **ISSUE-60** Extrusion into fresh cells leaves new helices outside the default placement cluster; moving that cluster moves only the original cells. | geometry / cluster correctness | triage | no |
| 14 | **ISSUE-70** Free Join can reject an otherwise attachable brace when the maximum precursor connection set contains a connector-only cycle. | Join correctness | triage | attachment policy |
| 15 | **ISSUE-71** Native import can reverse derived flexible-connector anchor order and change connector nucleotide positions. | persistence / geometry | triage | geometry review |
| 16 | **ISSUE-80** Assembly cold loading and Full frame rates remain costly; validated prepared CG switches are fast, but load/GPU targets remain unmet. | performance / responsiveness | medium | no; load/FPS targets unmet |
| done | ~~**ISSUE-16**~~ ✅ FIXED — all relevant `eigsh()` calls now pass deterministic `_eigsh_v0(...)`; focused verification still owed before archival. | reproducibility | — | — |

ISSUE-8 and ISSUE-11 remain decision-gated. Closed ISSUE-9/14/15/16/17 belong in the archive, not in
future priority calculations.

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

## ISSUE-8 — Autoscaffold doesn't route irregular multi-section designs to a single scaffold strand (routing correctness + tech debt)

- **Status:** `[~]` IN PROGRESS — **warn-only mitigation shipped** (commits `e9d6750` + `91fa2ac`,
  2026-06-08). **Build session 2 (2026-06-08): single-strand construction SOLVED + GENERALIZED in the
  harness** (NOT yet codified): reuse-trunk + reuse-window-cycles + 2-opt splice gives **1 strand, 0 bad
  transitions, full coverage, no double-coverage, buried nick** on BOTH teeth (square) and the 10-6-10
  dumbbell (honeycomb). Prototype: `scripts/section_router_prototype.py` (+ `..._harness.py`). Full decode +
  session-3 checklist in plan `~/.claude/plans/floating-crunching-widget.md` and `project_autoscaffold_single_strand.md`.
  **CODIFIED + GATED (default-OFF `NADOC_SECTION_ROUTER`) in `backend/core/section_router.py`; 1837 tests
  pass.** **FIXTURE CORRECTION (user caught it):** `teeth.nadoc` IS the reference base pre-fine-routing (same
  grid/bp_start/axis; differs only in helix length); `teeth_unrouted.nadoc` is an IDEALIZED uniform-face
  block, NOT representative — validate on `teeth.nadoc`. Added `_uniformize` (square ragged faces) so the
  REAL ragged teeth.nadoc routes to **1 strand, full coverage, 0 bad transitions, 0 overflow** (+ dumbbell).
  **NOT visually done:** the reuse approach over-extends ~822 bp of scaffold INTO THE GAPS on teeth (bloated
  teeth, unlike the reference's clean no-gap route). **REMAINING = non-extending window end-turns (construct
  the end turns at/just-past the true faces) → eyeball on teeth.nadoc → flip default.** See
  `project_autoscaffold_single_strand.md` + plan.

  **OPEN USER DECISION (window-face tradeoff) — blocks codification.** Sub-bundle routing extends helix
  geometry+scaffold past the section faces (router end-search = first valid ≥ hi+3, so +3…+period). Fine for
  the TRUNK (wanted blunt ends; propagate the extended helices). For WINDOWS it pushes helix+scaffold into the
  physical gaps. Lossless suppression is impossible when no valid crossover sits exactly at a window face
  (measured offsets: raw `teeth_unrouted` ≤6 bp, production-shaped `teeth.nadoc` ≤1 bp, HC dumbbell ≤4). So a
  window end-turn lands either (a) just INSIDE → ≤6 bp tooth-TIP coverage gap, or (b) just OUTSIDE → ≤ a few
  bp minimal extension into the gap but FULL coverage. On real designs both are ≤1 bp. Pick (a) or (b) →
  implement window end-turns at nearest-valid-to-face → propagate trunk extension → codify
  `section_router.py` (gate `_has_multisection_helix`, DEFAULT-OFF flag) → tests → `just test` → write teeth +
  dumbbell `.nadoc` → USER EYEBALL → flip default.
- **Symptom (user-facing):** a single *connected* design — one cluster of helices that share valid scaffold
  crossover adjacency — routes to MULTIPLE scaffold strands instead of one. It should be one strand per
  connected cluster (multiple strands only across genuinely *disconnected* clusters). Measured: `teeth.nadoc`
  → 5 (seamless) / 11 (seamed) pieces; the 10-6-10 dumbbell → 2–3 pieces. Uniform prisms (6HB/18HB) already
  route to 1.
- **What shipped (mitigation only):** both `auto_scaffold_seamed` and `auto_scaffold_seamless` now emit a
  warning when a connected cluster fragments into >1 scaffold strand ("Scaffold routed into N strands across M
  connected cluster(s)…"), so the gap is visible/actionable instead of silent. Helpers
  `scaffold_strand_clusters()` + `append_single_strand_warning()` in `backend/core/seamed_router.py`. (Same
  work: matched-ends became the seamed default — uniform prisms → 1 matched-end strand — and the CSP /
  advanced-seamed / advanced-seamless routers were deleted.)
- **Why the easy fix does NOT work (empirically falsified — do not re-try it):** you cannot consolidate by
  adding scaffold crossovers at valid mid-strand sites. Proven on teeth/seamless: a SINGLE crossover between
  two distinct pieces *splits* (5→6); a DOUBLE crossover (bp, bp+1) *swaps* (5→5). Neither merges. The
  fragments are **linear strands** whose 5'/3' termini must be joined — that's end-joining (forced-ligation
  territory, manual-only) or a **2-opt cycle reconnection** (remove one crossover from each of two cycles, add
  two that cross-connect them). 2-opt is the real path; it is the "cycle merging not implemented" gap the
  deleted CSP router had noted.
- **Caution:** this is the area `memory/LESSONS.md` **H18** records as repeatedly producing
  tests-pass-but-visually-wrong results. Do the rework with a real design loaded in the running app + visual
  confirmation at each step, NOT tests alone.

### Reference fixtures — hand-made + validated scaffold routings (use these to troubleshoot)
`workspace/Scaffold routing/` holds **hand-routed, user-validated** scaffold paths for the teeth design — the
*correct target outputs* to diff the router against when debugging fragmentation / single-strand routing:
- `workspace/Scaffold routing/teeth_seamed_route1.nadoc`, `…/teeth_seamed_route2.nadoc` — validated **seamed**
  routings (two variants). Each: 16 helices, **1 scaffold strand**, 62 crossovers.
- `workspace/Scaffold routing/teeth_seamless_route1.nadoc`, `…/teeth_seamless_route2.nadoc` — validated
  **seamless** routings (two variants). Each: 16 helices, **1 scaffold strand**, 38 crossovers.
All four are the single-strand TARGET (`scaffold_strands == 1`). The "yields 5/11 pieces" claim was measured
on a CORRUPT fixture (see below); on the clean fixture the standard routers route teeth to 1 strand. Clean
pre-routing input fixture: `tests/fixtures/teeth.nadoc` (replaced 2026-06-08 with `workspace/preroute_teeth.nadoc`).

## ISSUE-21 — Exported animation video: three defects in the SHARED frame loop (found 2026-08-02 while building the photo-mode video export)

- **Status:** `[ ]` OPEN — found while wiring `exportPhotoVideo` (see `memory/project_photo_mode.md`
  → "Video export"). User decision 2026-08-02: **fix only the photo-specific material/bounds gap;
  file these three.** None is photo-specific — all three hit the **existing** Animations-tab
  raw-canvas export identically, and have since it shipped.
- **Why filed together:** all three are the same root shape — `export_video.js`'s frame loop assumes
  `player.seekTo(t)` leaves the scene fully settled and fully driven, and in three places it does not.

**(a) A trajectory frame can capture the PREVIOUS frame's atoms.**
`animation_player._applyAt` → `trajectoryKeyframes.show()` → `ctrl.showFrame(idx)`
(`ui/oxdna_display.js:1460`), which calls **`_applyHeavy()` (`:938`) — `async`, and NOT awaited.**
In a heavy rep it can `await api.getOxdnaFramesAtomistic(...)`. `seekTo` returns before the atoms
land, so `renderFrame()` photographs the frame before. Partly masked by `play()` calling
`trajectoryKeyframes.setPlaying(true)`, which forces coarse granularity onto the pre-built grid
(usually a cache hit) — but a grid miss is a real `await`. Sibling: `trajectory_keyframes.js:137`
`_swap()` returns from `show()` **without showing anything** while a second job on the same engine
reloads, holding the stale frame for the whole reload.
*Fix needs* a quiescence signal from the display controllers (`oxdnaDisplay` / `mdViz`) that the
frame loop can await — there is none today.

**(b) Assembly joints animate in NO exported video, at all.**
`export_video.js` calls `player.play(animation)` with **no opts**, so the player's `_onJointUpdate`
is null and the `joint_values` lerp writes nowhere. The panel supplies it only for live playback
(`ui/animation_panel.js:1327`), and does so as an **unbatched fire-and-forget
`api.patchAssemblyJoint` per joint per frame** — so the naive fix (pass it through) turns a 300-frame
export into hundreds of unawaited HTTP writes whose effects land whenever. Wants a display-only
joint path before it can be exported.

**(c) `configuration_id` is authored but inert on the player.**
Zero references to it in `animation_player.js` (`grep -c` → 0). The panel writes it
(`animation_panel.js:1067`) and counts it in the dirty signature (`:1293`), but `_kfState` never
reads it. Assembly configuration transitions run through a *separate* animator,
`scene/assembly_config_animator.js:81`, with its own `performance.now()` + rAF tween and a trailing
`await api.restoreAssemblyConfiguration(...)` — not on the player's frame path. So a keyframe with a
configuration plays back as a no-op, in the app and in every export.

- **Also noted, not filed as a defect:** a surface-rep animation whose baked states differ in vertex
  count **snaps at `t=0.5`** and drops vertex colours until stop (`_rebuildTopology`, see
  `memory/project_animation_all_reprs.md`). Deterministic, but visually discontinuous mid-clip.
- **Suspected locations (leads — re-derive before investing):** `frontend/src/scene/export_video.js`
  (the two frame loops), `frontend/src/ui/oxdna_display.js` (`_applyHeavy`, `showFrame`),
  `frontend/src/scene/trajectory_keyframes.js` (`show`/`_swap`),
  `frontend/src/scene/animation_player.js` (`_applyAt`, `play` opts).
- **Repro shape (step 1 of the loop is still owed):** author an animation with (a) a trajectory
  keyframe over a job whose heavy rep is on, (b) an assembly `joint_values` keyframe, (c) a keyframe
  with a `configuration_id`; export it from either tab; compare frames against live playback.

---

## ISSUE-20 — The fast-suite guard's per-test budget measures CONTENDED time, so it flags healthy sub-2s tests and ratchets them out of the fast suite

- **Status:** `[ ]` OPEN — found 2026-07-16 during the AF-39 loop (`/automate-feature`). Diagnosed + evidenced,
  **not fixed**: the fix changes the test guard itself (a risky-action / infra file), so it wants a decision first.
  User decision 2026-07-16: **stop and file it; do NOT relegate the healthy tests.**
- **Symptom.** `just test-smart` prints `HEAVY TEST IN THE FAST SUITE — N unmarked test(s) over the per-test
  budget` for tests that are **not heavy**. Triaging them "fixes" the run, and then the *next* run flags a fresh
  batch of equally-healthy tests. An infinite ratchet: each round silently removes real coverage from the fast suite.
- **Evidence (same session, no code change to any of these tests between the two runs):**

  | test | run A | run B | **standalone** |
  |---|---|---|---|
  | `test_snupi_hydro_coarse::test_generalized_rpy_min_eigenvalue_is_stable_in_N` | 4.28s | **6.21s** | **1.28s** |
  | `test_simple_router::test_full_autostaple_splits_oversize_seam_bridge` | 4.11s | **5.95s** | **1.21s** |
  | `test_atomistic_validation::test_backbone_closure_connects_and_preserves_rigid` | 3.61s | **5.27s** | **0.74s** |
  | `test_overhang_geometry::test_cadnano_overhang_axes_use_trimmed_physical_span` | 4.26s | **5.20s** | **1.54s** |

  All four are **0.74–1.54s uncontended** (`pytest -p no:xdist -p no:randomly --durations`), i.e. 3–7× UNDER the
  5s budget, yet all four crossed it in run B purely from scheduling noise. The 3 tests triaged in run A
  (`test_model_nt_grows_by_exactly_the_insert_total`, `test_voltroncore_model_grows_by_334_beads`,
  `test_pdb_serials_hybrid36_past_9999`) were likewise 1.2–1.6s standalone.
- **Root cause (5-Whys).** The guard reads per-test `seconds` from a pytest run executed under `-n auto`
  (12 workers) at `nice -n 10`. That number is wall-clock **under contention**, not the test's intrinsic cost, and
  it inflates ~4–5×. So `NADOC_PER_TEST_BUDGET_SEC=5.0` is in practice a **~1.2s standalone bar** — low enough that
  a large fraction of the suite's legitimate mid-weight tests sit within noise of it. Whichever tests happen to
  land on a contended worker that run become "violators".
- **Why this matters / why it's not just cosmetic.** `CLAUDE.md` makes triage *mandatory* on a per-test violation
  and forbids raising the budget — both correct **given the premise that an over-budget test is genuinely heavy**.
  That premise is false here, so following the letter of the rule relegates healthy tests forever. Note the
  guard already reasons this way about the *aggregate* backstop ("it grows with test count and CPU load, so a
  fixed ceiling just ratchets healthy tests out") — the per-test budget has the same disease and no such caveat.
  The next tier is already queued at the line: 4.95s / 4.50s / 4.48s / 4.32s.
- **Suspected location (lead, verify before investing).** `scripts/test_guard.sh` — the per-test budget check and
  the `.nadoc-slow-candidates.json` writer; `NADOC_PER_TEST_BUDGET_SEC`, `NADOC_TEST_NICE`.
- **Candidate fixes (decide first — do NOT just raise the budget, which is explicitly forbidden and would also
  mask real regressions):**
  1. **Re-time before flagging** — when a candidate exceeds the budget under `-n auto`, re-run *just that test*
     serially and only flag it if it's still over. Costs a few seconds on the rare violating run; makes the
     number mean what the rule assumes it means. Most faithful to the existing policy's intent.
  2. **Budget on standalone CPU time**, not wall-clock (e.g. per-test `user+sys` rather than elapsed), which is
     contention-invariant — then re-derive an honest threshold from the current distribution.
  3. **Scale the budget by observed contention** (e.g. `budget × (total_test_seconds / wall_clock)`), cheapest
     but still an estimate.
- **Do NOT (banked so a future session doesn't relearn it):** relegate an under-2s-standalone test just because
  the guard flagged it; raise `NADOC_PER_TEST_BUDGET_SEC`; set `NADOC_TEST_FORCE=1`. The 2026-07-16 triage round
  *was* sound on its own merits and stays (two real mrDNA/16k-nt builds relegated per existing precedent, one
  genuine redundancy removed — `export_pdb` was rebuilding an all-atom model the test had already built,
  verified byte-identical), but it was fixing the symptom, not this.

---

## ISSUE-19 — The scaffold router EXTENDS ITS DOMAIN THROUGH a linker/staple (double occupancy), and the validator doesn't notice

- **Status:** `[ ]` OPEN — found 2026-07-13 while fixing ISSUE-18 (its sibling: same rule, different verb).
  Repro'd, not fixed — the fix changes *where the scaffold is allowed to extend*, i.e. real routing behaviour
  on every overhang/linker design, so it wants a decision first (see below).
- **Symptom.** Plant a LINKER at bp `-9..-4` REVERSE on a helix — i.e. in the region the near-end turn extends
  INTO, not overlapping the scaffold's original footprint. Route with `auto_scaffold_seamed`. Result:

  ```
  scaffold dom  81 -> -9  REVERSE      # extended straight through the linker
  LINKER        -4 .. -9  REVERSE      # still there
  ```

  Two strands now occupy **the same nucleotides on the same helix in the same direction** — physically
  impossible. ISSUE-18's allowlist correctly stops the router *nicking/ligating* the linker, and a pre-existing
  guard correctly refuses the scaffold↔linker crossover with a clear warning ("both halves must be the same
  strand type") — but nothing stops `_extend_scaf_domain_lo` / `_extend_helix_lo` from **extending over** it.
- **`validate_design()` returns `passed=True` on that design.** There is **no double-occupancy check at all** —
  nothing anywhere asserts that a given `(helix, bp, direction)` nucleotide is claimed by at most one strand.
  That is the more alarming half of this: the invariant isn't merely violated by the router, it is *unowned*.
- **Where:** `seamed_router._extend_scaf_domain_lo/_hi` (~:421-470) and `_extend_helix_lo/_hi` (~:376-420) —
  they extend to the turn bp with no occupancy test. The `bounded_ends`/section-router path is likely exposed
  the same way.
- **Two things to decide (why this is filed, not fixed):**
  1. **What should the router DO when the end-turn zone is occupied?** Refuse the turn for that pair and warn
     (route degrades to >1 scaffold strand — it already warns about that today)? Or search *inward* for the
     next legal crossover site that clears the obstruction? The second keeps the single-strand route but moves
     the turn, which changes routing output on existing designs.
  2. **Should double occupancy become a hard validator error?** It looks like a genuine missing invariant, but
     turning it on may light up existing saved `.nadoc` files (unknown blast radius until measured).
- **Test seam already exists:** `tests/test_scaffold_router_strand_isolation.py` has the fixture helper
  (`_with_strand_at`) and the exact end-turn-zone case
  (`test_scaffold_router_leaves_a_linker_in_the_end_turn_zone_alone`, which today asserts only that the linker
  is not *edited* — it deliberately does NOT yet assert non-overlap).

## ISSUE-16 — `predict_shape(with_rmsf=True)` is NONDETERMINISTIC (unseeded ARPACK start vector)

- **Status:** `[ ]` OPEN — found 2026-07-13 while chasing a "flaky" test in the full suite. Repro'd, not fixed
  (it lives in the SNUPI/FEM area under active development on the other machine — coordinate before touching).
- **Symptom (the messenger):** `tests/test_snupi_element.py::test_g12_salt_ignored_by_cando` fails
  intermittently in the full parallel suite (`assert cando_drift < 1e-2`) and passes in isolation and as a
  whole file. It only *runs* on an idle box — under a live NAMD job the sim guard skips it, which is why the
  earlier runs in that session looked clean.
- **The actual bug (worse than the test):** `predict_shape(design, with_rmsf=True)` **does not return the same
  answer twice for identical inputs.** Measured on the suite's own `routed_6hb` fixture, three consecutive
  calls: `max|run0 − run1| = 3.7e-3 nm`, `max|run0 − run2| = 2.6e-3 nm`. The FEM RMSF output is simply not
  reproducible.
- **Root cause:** every `eigsh(...)` call in `backend/physics/fem_solver.py` (lines ~1376, 1441, 1443, 1475,
  1477) omits `v0=`. SciPy/ARPACK then draws a **random start vector** from numpy's global RNG, so the
  shift-invert eigenvectors — and hence the RMSF built from them — differ run to run.
- **Why the test is a trap:** it asserts the cando cross-salt drift is `< 1e-2`, where the true value should be
  **~0** (cando has no electrostatics ⇒ `mgcl2_M` is inert). So the quantity under test is *pure eigensolver
  noise*, and the assertion is really "is today's noise small enough". Its docstring claims that noise is
  ~1e-4 nm; it is actually ~3.7e-3 nm, **~37× larger** than documented.
- **Fix shape:** pass a deterministic start vector (e.g. `v0=np.ones(n)/sqrt(n)`, or a seeded RNG draw) to every
  `eigsh` call, so the eigenproblem is reproducible. Then re-tighten the test's tolerance to something that
  actually discriminates (with a deterministic solver the cando drift should be ~0, not ~1e-3), and correct the
  docstring's noise figure.
- **Blast radius:** anything that fingerprints or diffs FEM RMSF — the SNUPI-vs-CanDo comparators, the
  shape-gap diagnosis, and any oracle asserting on RMSF floats. A cross-engine comparison whose own solver has
  ~4e-3 nm of run-to-run jitter cannot resolve differences below that.

## ISSUE-9 — Autoscaffold is not idempotent — ✅ FIXED 2026-07-13

- **Status:** `[x]` FIXED 2026-07-13. `backend/core/scaffold_reset.py` + wiring in
  `seamed_router` / `seamless_router` / `section_router`; pinned by `tests/test_scaffold_idempotence.py`
  (12 tests, 8 verified can-go-red against the pre-fix source).
- **It was NOT teeth-specific** — the dossier below implies it was, and that framing is wrong. Measured on a
  plain 4HB honeycomb bundle with no teeth, no sections and no section-router: helices ratcheted
  `168 → 189 → 199 → 210` bp and crossovers `6 → 9 → 12` over three routes, unbounded, on **both** the seamed
  and the seamless router. Teeth is only where it was *visible* (the extension intrudes into the inter-tooth
  gaps); on a plain bundle it silently lengthens your helices with no visual tell, which is worse.
- **Verified root cause.** The near/far end-turn legitimately extends a helix a few bp past the scaffold's
  terminal face so the scaffold has ssDNA to turn around in (`MIN_SSDNA_MARGIN`, see `scaffold_invariants`).
  But the router derives the face it extends FROM `_scaffold_coverage(...)` — i.e. from its own previous
  output. On a second call `face` is the already-extended terminus, `near_floor = face - 3` searches strictly
  further out, and it extends again. The extenders are monotone (`if new_lo >= helix.bp_start: return`), so it
  is a ratchet, not an oscillation. It rewrites `bp_start`/`length_bp`/`axis_start`/`phase_offset` in place —
  destroying the very information needed to undo it — and persists to the `.nadoc`.
- **Second, independent bug found in the same code:** the seamed router stamps THREE `process_id`s on the
  crossovers it creates (`auto_scaffold_seamed:seam`, and the bare `create_near_ends` / `create_far_ends`), but
  `_clear_auto_scaffold_route_for_seamed` only matched the `auto_scaffold_` prefix. The end-turn crossovers
  therefore survived every "clear" — which is why crossovers accumulated, and means that clear helper (used by
  `auto_scaffold_matched`) had never actually worked. `scaffold_reset.is_route_crossover` now owns the full set.
- **The fix — staples are the structure** (user's rule, then verified against real designs). Autoscaffold never
  touches staple strands, so a helix's true extent is the bp span of its STAPLE domains. Confirmed: across three
  re-routes the staple spans stayed at `[0,167]` while the helices ratcheted to `[-30,179]`. And in the real
  multi-section fixtures the staple intervals are *identical* to the scaffold sections, gaps and all —
  `teeth`: `[(0,41),(84,125),(168,209)]`; `dumbbell`: `[(0,41),(126,167)]` — i.e. exactly the "clean per-domain
  seed" this dossier asked for. So the routing algorithm was left untouched; only its INPUT is normalised:
  retract each helix + re-seed the scaffold to the staple-defined extent, then route. `reset(route(fresh))` now
  reproduces `fresh` field-for-field, so N calls ≡ 1 call.
- **Deliberately conservative:** the reset only ever CLAMPS INTO the staple intervals, never grows the scaffold
  to fill them (a scaffold left short of its staples was never routed there — growing it would silently edit an
  unrouted design). Forced ligations bail out with a warning: a manual fixed-edge topology is not derivable from
  the staples.
- **Consequence — the "latently corrupt" fixture concern is retired.** `10-6-10hb_seamed.nadoc` being pre-routed
  no longer poisons anything, because a re-route now resets to the structural seed first.

<details><summary>Original dossier (2026-06-08) — kept for the history; its "teeth" framing and its
"root cause (to verify)" were both only half right</summary>

- **Status:** `[ ]` OPEN — discovered 2026-06-08 while fixing the teeth fixture (ISSUE-8).
- **Symptom:** running an autoscaffold mode on a design that was ALREADY autoscaffold-routed does NOT reset to
  a clean per-domain seed first — it routes the previously-EXTENDED scaffold geometry, pushing domain ends
  further past the section faces and into the inter-tooth gaps. Each re-run compounds. This is how the old
  `tests/fixtures/teeth.nadoc` got corrupted: it was a seamless-routed file whose tooth faces had already been
  pushed from the clean `[0,41] [84,125] [168,209]` out to ragged `[-3,47] [72,132] [157,218]`, etc. Measuring
  the section router against THAT baseline made clean routes look like they over-filled the gaps (172 bp in-gap
  vs the clean route's ~9 bp worst extension / 32 bp gap clearance). It cost most of a session chasing a
  non-existent "gap-stagger" problem.
- **Root cause (to verify):** `auto_scaffold_seamed` / `auto_scaffold_seamless` (and the matched variant) do
  clear `auto_scaffold_*`-prefixed crossovers, but they re-route on the existing (already-extended) scaffold
  DOMAINS / helix lengths rather than resetting each scaffold strand to its clean per-domain extent first. The
  seamed `_extend_helix_*` / `_extend_scaf_domain_*` then extend an already-extended domain.
- **Desired behavior:** autoscaffold is idempotent — N calls produce the same result as 1. Before routing,
  reset the scaffold to its clean per-domain seed (un-extend faces back to the design's true section extents,
  drop prior route crossovers) so a re-route starts from the bare structure, not a prior route's output.
- **Repro (write as the pin):** load a clean multi-section design (`workspace/preroute_teeth.nadoc`), run seamed
  autoscaffold twice; assert run-2 output == run-1 output (same domains/faces/crossovers), and that no scaffold
  domain end has been pushed further into a gap on the second run. The section-router gap invariants in
  `tests/test_section_router.py` (`intertooth_gap_extension`, `min_per_gap_clearance`) are the ready-made checks.
- **Caution:** `tests/fixtures/10-6-10hb_seamed.nadoc` (the dumbbell) is ALSO a pre-routed file (14 scaffold
  strands, 12 crossovers, `_seamed` in the name) — same latent corruption; its tests happen to pass but it
  should likely be replaced with a clean pre-routing dumbbell when this is fixed.

</details>

## ISSUE-11 — Deformed-continuation helices carry `grid_pos=None` (data-model inconsistency; ask-first)

- **Status:** `[ ]` OPEN. Discovered 2026-06-17 during AF-5 (`/automate-feature`, deformed-continuation
  headless wrapper). NOT fixed — it's a three-layer/directionality question (see "desired behavior").
- **Symptom:** `make_bundle_deformed_continuation` (`backend/core/lattice.py:1234`) is the **only** bundle
  builder that does not set `grid_pos` on the new `Helix` it creates — `make_bundle_design`,
  `make_bundle_segment`, and `make_bundle_continuation` all pass `grid_pos=(row,col)`. Because the new helix's
  id collides with the source cell's (`h_XY_0_0` → `_unique_id` → `h_XY_0_0_1`), the legacy
  `_recover_grid_pos` regex (`fullmatch r'h_XY_(-?\d+)_(-?\d+)'`) does NOT back-fill it either, so the helix
  ends up with `grid_pos=None`.
- **Impact:** any design containing a deformed continuation crashes `canonical_topology` /
  `assert_roundtrip_stable` (`TypeError: '<' not supported between NoneType and tuple` — it sorts on
  grid_pos). More broadly, grid_pos drives cluster reconciliation, overhang-neighbor lookup, and
  `loop_skip_calculator` (which raises "no grid_pos") — so a deformed-continuation segment may be invisible to
  or break those features. AF-5 worked around it by using a pure geometric oracle (`assert_on_deformed_frame`)
  instead of the round-trip oracle.
- **Where:** `backend/core/lattice.py` ~1322 (the `Helix(...)` constructor inside
  `make_bundle_deformed_continuation`); `canonical_topology` in `tests/automation_harness.py:52`.
- **Desired behavior (ASK USER FIRST — do NOT just patch):** likely fix = add `grid_pos=(row, col)` to that
  constructor to match every sibling builder. BUT the omission may be **intentional**: a non-None grid_pos
  could make the straight-geometry path (`_helix_lattice_params`, which derives x/y from grid_pos) recompute
  the helix's lattice position and *clobber the baked deformed world-coordinates* the deformed continuation
  stores in `axis_start`/`axis_end`. This is a three-layer (topology↔geometry) boundary question — confirm
  with the user whether geometry reads grid_pos or the baked axis for these helices before changing it.
  Secondary (defensive, independent): make `canonical_topology` tolerate `grid_pos=None` (stable sort key)
  so the round-trip oracle degrades instead of crashing.
- **Scope:** one-line builder change IF approved; small oracle hardening. Medium priority (blocks round-trip
  validation of any deformed design; may mask feature breakage).

## ISSUE-12 — `cluster_create` feature-log entries mislabel as "move/rotate" in the log panel (UI correctness)

- **Status:** `[ ]` OPEN. Discovered 2026-06-18 during AF-16 (`/automate-feature`, loggable cluster creation).
  NOT fixed — frontend work outside the backend design-automation loop's scope; logged for cross-loop intake.
- **Symptom:** the feature-log panel's render dispatch (`frontend/src/ui/feature_log_panel.js`) switches on
  `entry.feature_type` with explicit branches for `deformation` / `overhang_rotation` / `routing-cluster` /
  `snapshot`, and a **catch-all `else` (line ~1374) that assumes any remaining entry is a `cluster_op`** (it reads
  `entry.cluster_id`, renders `"F#: move/rotate <name>"`, and wires an edit button to the cluster-transform editor
  `onEditFeature`). The NEW `cluster_create` entry type (AF-16) ALSO carries `cluster_id`, so it falls into that
  `else` and renders as a misleading **"move/rotate"** row with an edit button that opens the *transform* editor on
  a grouping entry (wrong tool; may error or produce nonsense).
- **Impact:** LOW today — `cluster_create` entries are only produced by a **headless** `add_cluster(..., log=True)`
  build; no UI path emits one, so it surfaces only when a user *loads* a headless-/automation-built `.nadoc` that
  used the AF-16 log path. But once the generated 4-bar/parallelogram parts (which is the AF-16 motivating use case)
  are saved and opened, every bar's creation step will mislabel.
- **Where:** `frontend/src/ui/feature_log_panel.js` ~817 (`_brokenReason`, returns null for the type — fine) and
  ~1374 (the catch-all `else` that should test `entry.feature_type === 'cluster_op'` explicitly and give
  `cluster_create` its own branch). Model: `ClusterCreateLogEntry` in `backend/core/models.py`.
- **Desired behavior:** add an explicit `else if (entry.feature_type === 'cluster_create')` branch rendering a
  sensible label (e.g. `"F#: Group <name> (N helices)"` with a distinct icon) and a delete button (no transform
  edit/revert — creating a cluster isn't a posable op). Tighten the trailing `else` to `feature_type === 'cluster_op'`
  so a future unknown type doesn't silently inherit the move/rotate UI. Route through the panel module; gate vitest
  + smoke + one app exercise (load a headless design carrying the entry). Low priority.

## ISSUE-13 — `resize_strand_ends` re-trims a helix axis to a different endpoint convention than `create_bundle` (geometry-convention off-by-one; ask-first)

- **Status:** `[ ]` OPEN. Discovered 2026-06-26 during AF-30 (`/automate-feature`, strand end-resize headless
  wrapper). NOT fixed — it's a geometry-convention question (CLAUDE.md: geometry/axis changes ask-first).
- **Symptom:** `make_bundle_design` (and siblings) set a fresh helix's `axis_end` to
  `axis_start + length_bp · BDNA_RISE_PER_BP` (for a 42-bp helix: `42·rise ≈ 14.028 nm`). But the axis re-trim
  inside `resize_strand_ends` (`backend/core/lattice.py:4490`) recomputes the endpoints from the strand-coverage
  union as `axis_start + (max_bp_index − min_bp_index) · rise` — i.e. `(length_bp − 1)·rise ≈ 13.694 nm`, one
  rise SHORTER. So the FIRST resize of *any* strand end on a freshly-created bundle silently shifts that helix's
  `axis_end` by ~0.334 nm even when the resized end is the *other* end, and the shift never reverts.
- **Impact:** LOW for geometry correctness — **the convention shift does not change the nucleotide count** (the
  geometry kernel emits per `length_bp`, which is identical under both axis-endpoint conventions; the resize's own
  intended count change is a separate, correct effect that AF-30's `assert_geometric_length_delta` pins cleanly). The
  visible effect is the axis-arrow length and any consumer that reads `axis_end` directly. The concrete bite: a
  `+δ` then `−δ` resize is NOT a `canonical_topology` identity from a raw bundle (the fingerprint includes axis
  floats), even though the strand bp-ranges restore exactly — AF-30's inverse-pair test works around it by
  capturing `start` AFTER a settling resize (both ±δ runs then share the re-trim convention).
- **Where:** `backend/core/lattice.py:4515-4516` (`offset_hi_nm = (hi_bp - old_bp_start) * BDNA_RISE_PER_BP`)
  vs the `make_bundle_*` constructors' `length_bp · rise`. `shift_domains` (`lattice.py:4554`) uses the same
  re-trim convention, so it shares the discrepancy.
- **Desired behavior (ASK USER FIRST — do NOT just patch):** decide which convention is canonical — `length_bp·rise`
  (axis_end one rise past the last bp center) or `(length_bp−1)·rise` (axis_end at the last bp center) — and make
  both `create_bundle` and the re-trim agree. This is the same family of three-layer/geometry-boundary question as
  ISSUE-11; confirm whether downstream geometry/rendering expects the axis to bracket bp centers or span the full
  bp count before changing either site.
- **Scope:** a one-line change at one of the two sites IF approved; would let AF-30's inverse pair drop its
  settling step. Low priority (cosmetic axis offset; no nucleotide-count impact).

## ISSUE-14 — `assembly_exit_cleanup` smoke spec fails — ✅ FIXED 2026-07-13 (it was the TEST HARNESS, not the app)

- **Status:** `[x]` FIXED 2026-07-13. **The recorded diagnosis above was WRONG** and is preserved below as a
  lesson in what a red gate does NOT tell you.
- **There was never a console error.** The assembly teardown is clean — `d5be41c` DID fix it. The spec died in
  `e2e/helpers/scene_harness.js` during **setup**, so the console-error assertion it was blamed for never
  even ran. The failure the ledger recorded ("a console error fires while exiting assembly mode") was an
  inference from the spec's *name*, not from its output. Reading the actual error took 5 minutes and pointed
  somewhere else entirely.
- **Two real defects, both in the harness** (`loadScaffoldedPart`, shared by **9 specs**):
  1. **A race.** `await page.waitForTimeout(500)` after File→New assumed the design had reached the backend.
     The welcome screen hides as soon as the *page* has a design, but the POST may still be in flight — and on
     a cold smoke backend it takes >500 ms. `page.request` then hit the doc before it had a design and got
     **404 "No active design."**, collapsing every downstream call (`design.helices[0].id` → undefined). Now an
     `expect.poll` on `GET /design` == 200 — poll the backend's own view, never guess a duration.
  2. **A dead route.** `POST /design/auto-scaffold` has returned **405 Method Not Allowed** since `e9d6750`
     (2026-06-08) consolidated it into the `-seamed`/`-seamless`/`-matched` variants without updating the
     harness. It had been 405-ing into its `scaffold-domain-paint` fallback for a month. The fallback is what
     actually works, so it is now the primary path and the dead call is gone.
- **Why it looked like an app bug:** the race is load-sensitive, so it only bit when the box was busy — which
  is exactly when someone runs a gate. It surfaced 2026-07-06 under a *backend-only* CanDo change, which is
  itself the tell: a frontend teardown bug cannot be caused by a backend-only diff.
- **Second-order finding — smoke was ALSO being starved.** With the harness fixed, the heavy browser specs
  still time out when a production NAMD job is running (measured: NAMD `+p6` = ~5.5 of 12 cores, load ~10;
  a spec that passes in 16 s takes >30 s). The failure *moves between specs* run-to-run, which reads as a flaky
  app but is pure CPU contention. `just smoke` now **refuses to run** under a live sim (`scripts/sim_guard.py`,
  reusing `hardware.heavy_sim_running()`); it fails LOUD rather than skipping, because a silent skip on a
  *commit* gate is no gate. Override: `NADOC_IGNORE_SIM_GUARD=1`.
- **Lesson (banked in [[LESSONS]] H13):** when a gate goes red, read the captured error before believing the
  spec's name. A spec named "no console error" failing does not mean there was a console error.

## ISSUE-15 — `fetch_outputs` marks a remote MD job `completed` even when its output download failed (correctness; surfaced-by-review, ask-first)

- **Status:** `[x]` FIXED 2026-07-08. A SLURM-COMPLETED job whose checkpoint restart set
  (`.coor/.vel/.xsc`) failed to download is no longer reported `completed`: `reconcile_remote_job` now checks
  `_completion_checkpoint_present` after `fetch_outputs` and, if no segment has a complete local restart set,
  keeps the job **re-pollable** (`status=running`, stays in `is_remote_active`) so the supervisor re-fetches on
  the next pass; after `_MAX_FETCH_ATTEMPTS` (3) it surfaces a genuine `failed` (`failure_kind="fetch_incomplete"`)
  naming the missing files. New `MdJob.fetch_attempts` counter (reset to 0 on a clean completion). End-state
  semantics (re-pollable auto-retry vs a distinct `fetch_failed` state) confirmed with the user = re-pollable.
  Pinned by `tests/test_md_executor.py::test_reconcile_completed_missing_checkpoint_{stays_repollable,fails_after_retries}`
  (both can-go-red against the old source, verified via stash-rerun). Conservative predicate: a job with any
  surviving checkpoint or no segments passes, so a good fetch is never falsely flagged; a *partial* drop that
  keeps some-but-not-the-seed checkpoint is not caught (acceptable — the reported total/near-total failure is).
- **Symptom:** `backend/core/md_executor.py` `_poll_one`/reconcile calls `fetch_outputs` inside a try/except that
  only **logs a warning** on failure and then **unconditionally** marks the remote (Alpine/SLURM) job
  `completed` (around `md_executor.py:621-633`). So a job whose `output/<ckpt>.coor/.xsc` did not (fully) download
  is still reported `completed`. A completed job is no longer re-polled by `poll_remote_jobs`, so the missing
  outputs are never re-fetched automatically.
- **Why it matters (the P2 trigger):** the job-planner chain executor (`advance_chains`) seeds stage N+1 from stage
  N's checkpoint; a `completed`-but-outputs-missing stage makes `spawn_md_production` 400 ("Checkpoint … were not
  found locally"). P2 now HARDENS its own side (bounded spawn retry, `_MAX_STAGE_SPAWN_ATTEMPTS`), but because the
  completed job is never re-polled, retries exhaust and the chain halts requiring manual intervention — the true
  fix is on the `md_executor` side (don't mark `completed` on a failed/partial fetch; keep it re-pollable).
- **Where (leads, verify):** `md_executor.py` `fetch_outputs` + `_poll_one` completion transition; check whether a
  partial/failed download can be distinguished (rc / expected-file manifest) and whether the job should stay
  `running`/`fetching` for a re-poll instead of flipping to `completed`.
- **Repro FIRST + ASK before fixing** (loop discipline): construct a remote job whose fetch fails (mock the
  transfer) and assert it does NOT go `completed` with missing outputs; confirm the desired state (re-pollable vs
  a distinct `fetch_failed`) with the user — it's a UX/semantics call, not purely mechanical.

## ISSUE-17 — `polymer_router` synthesizes staples over bare scaffold ends — ✅ NOT A BUG (by design, 2026-07-13)

- **Status:** `[x]` CLOSED as WORKING AS INTENDED — user ruling 2026-07-13. **Do not "fix" this.**
- **Raised because:** `backend/core/polymer_router.py` reads scaffold coverage and manufactures a STAPLE
  complementary to each unpaired scaffold run at a helix cap (`_complement_strand` ~:146-157, appended ~:277),
  and errors with *"No unpaired scaffold ends found"* (~:270-274). Under `feedback_staples_are_user_intent`
  that looked like blunt-capping the very ssDNA loops the law protects.
- **Why it's fine:** those staples are exactly the ones **defining how individual structures link to each
  other**, and creating them is otherwise manual work — polymer_router is a *shortcut for the user*, not a
  router inferring intent. It runs **after** individual-structure validation, as an explicit user-invoked op
  ("Route for polymerization"); it is never reachable from a scaffold auto-route. So it falls under rule (c) of
  the law: an explicit user-invoked staple operation may create staples. **polymer_router gets a pass.**
- **Note for the law:** despite the name, it is a STAPLE op, not a scaffold router. The ban in
  `feedback_staples_are_user_intent` is on *scaffold routers* silently touching staples — not on user-invoked
  tools whose entire purpose is to create linking staples.

## ISSUE-18 — A SCAFFOLD router can nick/ligate a STAPLE — two unfiltered helpers in `seamed_router`

- **Status:** `[ ]` OPEN — surfaced 2026-07-13 by the same audit. Latent via `section_router` (its sub-design
  holds scaffold only), but **live** on the direct `auto_scaffold_seamed` / `auto_scaffold_seamless` API path,
  which runs against the full strand list.
- **The rule it breaks:** scaffold routers must **never** create, extend, trim, split, or delete a staple. They
  may extend helices and scaffold domains only. Every other router obeys this; these two shared helpers don't.
- **Where (leads, verify):**
  1. `seamed_router.py` ~:307-311 — `_nick_if_needed` calls `lattice._find_strand_at`, which iterates **all**
     strands with **no `strand_type` and no `is_reference` filter**. On any bp where the scaffold does not reach
     but a staple/linker occupies the scaffold-direction slot (LINKER complements are documented to do exactly
     this; so can OH_BINDER domains and hand-drawn staples), the scaffold router will `make_nick` a staple —
     creating a strand and trimming a domain. Contrast `nick_all_major_ticks`, which *does* filter.
  2. `seamed_router.py` ~:339-350 — the ligation terminal maps (`three_p` / `five_p`) are built over **every**
     strand with no type filter, so any staple/linker/binder whose 5'/3' terminus lands on a scaffold-crossover
     half gets fused into the scaffold. Contrast `ligate_crossover_chains` (lattice.py ~:2002), which filters.
     `_linearize_circular_scaffolds` (~:1074-1095) inherits both.
- **The designations already exist — this is not a modelling gap.** `StrandType.LINKER` (its own docstring:
  *"skipped by most pipelines (geometry render, scaffold validators, **auto-routing tools**)"* — i.e. the
  contract is already written down), `StrandType.OH_BINDER`, `Domain.overhang_id` / `binds_overhang_id`, and
  `Strand.is_reference`. Peers honour them (`build_strand_ranges` excludes LINKER; `validator.py:161`;
  `lattice.py:2423`). These two helpers simply never consult them.
- **Fix shape:** gate both on a **positive allowlist** — `strand_type == SCAFFOLD and not is_reference` — not on
  a linker/overhang blocklist. The allowlist also excludes OH_BINDERs and plain hand-drawn staples (a blocklist
  would still let the scaffold router nick those) and stays correct for any strand type added later.
  Mechanically the same guard the lattice-level equivalents already carry. Low risk, but it changes
  scaffold-routing behaviour on designs with linkers/overhangs, so pin it with a repro first (route a design
  carrying a linker whose complement sits in the scaffold-direction slot; assert no non-scaffold strand is
  nicked or fused).

## ISSUE-22 — Roll/return staleness workflow remains broken after multiple fixes

- **Status:** REVALIDATION REQUIRED — API lifecycle green; one frontend edge fixed 2026-08-08.
- **Observed:** user-confirmed failure on 2026-06-24 persisted across multiple fix rounds. Rolling the
  feature log to a job's design and returning does not reliably clear stale state and restore the live
  trajectory workflow.
- **Why this is an issue:** expected behavior was exercised and failed. Do not return it to manual-
  validation debt.
- **Audit/automation (2026-08-08):** `assert_roll_return_lifecycle` now drives and asserts the complete
  oxDNA simulate → edit → 409 guard → roll → fingerprint/cursor/log restore → warning clears → return
  → exact latest fingerprint/cursor/log restore → warning reappears lifecycle. The MD API test now drives
  the real `save_current=false` return endpoint and asserts parity. All focused tests pass.
- **Confirmed edge fixed:** `showPersistentToast` reused one global persistent-toast slot but updated only
  its message. If a loading/status toast already occupied that slot, the roll-complete message retained
  the old action (or no action), so **Return to latest was unavailable**. Repurposing a persistent toast
  now replaces severity, loading state, and controls; a discriminating Vitest test pins the action swap.
- **Identity root cause fixed (2026-08-08):** cross-design roll remains allowed, but now switches to the
  job snapshot's own Feature Log instead of splicing the active file's history onto unrelated topology.
  `Design.id` now follows rename/move; Save As and detected copies mint a new UUID. Persisted
  `identity_last_known_path` + `identity_confirmed_at` provide the location signoff. Legacy files claim
  their path without changing UUID; duplicate legacy UUIDs are separated deterministically during the
  library audit. Managed/external moves remap simulation `design_source_path` provenance across all seven
  job engines. Old files remain schema-compatible through metadata defaults.
- **Seek latency/UI follow-up (2026-08-08):** Feature Log scrubbing no longer opens the global
  `Loading F…` persistent toast or the generic slow-request popup. The seek route avoids an unnecessary
  full-design deep copy, while MD/oxDNA stale-marker refreshes are coalesced and run after the scene has
  applied the selected state. Roll responses carry their authoritative fingerprint match, so starting
  the requested workflow no longer waits for a synchronous re-list of every historical job.
- **Next:** hand-drive the exact roll → follow/view job → return gesture in the current app. If it passes
  for oxDNA and MD, close this as a stale historical report; the former June failure is now API-pinned.

## ISSUE-23 — Assembly animation playback ignores keyframe `configuration_id`

- **Status:** OPEN — promoted from MV-8 on 2026-08-08.
- **Static repro:** `ui/animation_panel.js` persists and displays `configuration_id`, while
  `scene/animation_player.js` has no `configuration_id` reference. Playback therefore cannot apply a
  configuration attached to a keyframe.
- **Reference implementation:** `_animateAssemblyConfiguration` in `frontend/src/main.js`.
- **Next:** write a failing playback test with a configuration-bearing keyframe, then route configuration
  application through the animation player. Manual validation comes after the functional fix.

## Next-session handoff

_Living pointer — each session overwrites this. **Last updated 2026-10-16 (geometry-first G1 checkpoint).**_

**NEXT PICK: ISSUE-100 isolated bend/twist history preview.** Ordinary grouping
now always records its native input under one lock-owned publication transaction
(ISSUE-99). G1 remains in progress: preview/Apply/Cancel still changes canonical
state before acceptance. Follow the [geometry delivery map](docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md).
Grouping has 102 unique focused checks at its checkpoint; the ten deformation
cases include explicit characterizations of unresolved defects. App, broad-suite
and performance qualification are outstanding (MV-48); `main.js` delta is zero.
Forced ligation (ISSUE-101), batch nick/resize (ISSUE-102) and stale auto-crossover
publication (ISSUE-103) are focused-fixed. The private deformation prefix, host,
DTO, disabled HTTP adapter, transport/controller and native renderer now have
focused coverage. The router remains unregistered and the existing editor is
not wired. Next finish complete control validation, correct group retargeting
(ISSUE-105), connect the popup, then qualify response/desktop behavior. Do not
treat private preparation as a live preview fix.
Nanoparticle/asset expansion, assemblies and machine-specific VR work remain
outside this next step.

**Earlier queued work, deferred behind the user's geometry priority:** ISSUE-22
live revalidation, then ISSUE-23. The complete oxDNA/MD roll-return lifecycle is
now API-automated and green, and the missing-Return-action persistent-toast edge is fixed. Hand-drive the
roll → follow/view → return gesture; if green, close ISSUE-22 as stale and proceed to ISSUE-23.

**ISSUE-16 is no longer open:** deterministic `_eigsh_v0(...)` is present on the relevant FEM eigensolver
calls. Run the focused reproducibility tests, add a fix-log row if missing, then archive its dossier.

**Decision-gated:** ISSUE-8 and ISSUE-11. Do not infer either product/geometry decision.

<details><summary>Superseded 2026-06-08 handoff (ISSUE-1 Phase 2a-blunt) — kept for its banked detail</summary>

**OLD NEXT PICK: ISSUE-1 — context-menu migration, Phase 2a-blunt.** ISSUE-4's drill overhaul is functionally
complete and its legacy is deleted, so ISSUE-1 (deferred behind it) resumes. Phase 2a-blunt is the
biggest/riskiest of the 2a sub-phases: the blunt-end menu is NOT a builder — it's a **static HTML element**
`#blunt-end-ctx-menu` (index.html) with three heavy pre-wired handlers (`blunt-extrude/bend/twist-btn-ctx` in
main.js, bodies launch slice-plane / deform tool / set mode-indicator). Migrating → dynamic `createContextMenu`
means moving those 3 handler bodies into a new `ui/blunt_end_menu.js` factory + deleting the static element +
its CSS. Route the fix THROUGH the new module (main.js LOC Δ ≤ 0). The primitive supports `danger` AND
`{ type:'custom', el }`. ≥1 factory test; gate vitest + smoke + app exercise. (Alternative if the user prefers:
ISSUE-1 2b spreadsheet ×4, or 2c empty-space — cheaper than 2a-blunt. Or pick up ISSUE-4's optional
assembly-unification / text-breadcrumb, both low-priority.)

> **OPTIONAL USER TODO — re-eyeball the deleted-legacy build** (the deletion is "no behavior change", e2e+smoke
> green, but the multi-helix visual was eyeballed BEFORE deletion): `just frontend`, load
> `Examples/26hb_platform_v3.nadoc`, confirm the click ladder / Tab cycle / level persistence / crossover tube
> still behave exactly as before. (Expected identical — only dead code was removed.)

**ISSUE-4 STILL OPEN (optional, low-priority — pick only if the user asks):**
1. **Assembly unification (decision G)** — assembly adopts the same 1st-click-part / 2nd-click-subelement shape.
   Net-new (no assembly drill exists today).
2. **(Optional) text level-breadcrumb (decision-E)** — a persistent `Strand ▸ End` text trail in ADDITION to the
   glow + filter-row highlight. Confirm before building (the user previously did NOT want a text widget).

**ISSUE-1 context-menu migration — remaining phases (now unblocked):** 2a-blunt (NEXT PICK above), 2b–2e
(spreadsheet ×4 / empty-space / assembly / cadnano ×3), Phase 3+ content cleanup. The primitive supports
`danger` AND `{ type:'custom', el }` (HTMLElement passthrough — for flyouts/widgets the flat-item model can't
express; clicks inside don't auto-dismiss, wire that in the el); reuse both. The rep hover-flyout in
`selection_manager.js` uses the same `{type:'custom'}` pattern, so it's a cheap future migration.

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

</details>

**Gotchas banked** (still live — these outlive the issues that produced them):
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


> **History.** Closed issues live in [issues_ledger_archive.md](issues_ledger_archive.md). Read on demand only — never in a routine loop.

## ISSUE-24 — [x] Animation trajectory rows wait forever on stale operation timing

User observed all trajectory dropdowns stuck at Loading jobs with indeterminate bars.
Read-only browser evidence showed unfinished POST /design/import timing after the backend
was idle. Job-list lookup awaited the timing idle gate without a deadline; row metadata
and preparation subscriptions depended on that lookup. The exact orphaned render-callback
origin was not established. Fixed visible-request bypass, bounded background wait, and
independent row initialization. Regression tests cover stale timing and pending job lists;
the original panel fails the new pending-list regression. See
[trajectory audit](docs/animation_trajectory_loading_audit.md) for validation and the
subsequent ordered preparation/readiness feature. No topology changes; main.js delta 0.

## ISSUE-25 — PEG coating setup UI and validation boundaries

2026-09-11, user-requested PEG setup work. [x] Numerical fields now match adjacent
sidebar colors and pass browser contrast checks; invalid raw PEG values are rejected
by the new setup review. [x] Removed density/charge step constraints that rejected
the existing density default and fractional charges.

Open follow-ups: saved setup enablement after entering Simulations (PEG-06),
frontend/backend half-count rounding (PEG-07), shared validation for legacy
Store/New job (PEG-08), and older floor-stiffness step validity (PEG-09). Evidence,
scope and next actions: [barrier catalogue](docs/peg_coating_setup.md).

## ISSUE-26 — PEG Live rejected prepared coating jobs

2026-09-11: [x] Replaced the unconditional PEG Live rejection with an isolated
persistent PEG oxpy worker, job-specific capability gating, retained coating
topology and PEG CM frame output. Reconfiguration preserves topology and current
pose. Build script compiles bindings without replacing stock oxpy. Browser start/
frame/stop test passes with mocked engine responses; real stepping remains gated.
Evidence and unresolved validation: [PEG Live](docs/peg_live.md).


## ISSUE-27 — First autosave erased a blank document's NAMD surface setup

[x] Fixed 2026-09-13 within the requested blank-document charged-wall workflow.
Playwright reproduced the enabled surface resetting after New job triggered the
first save. `workspace-path-change` now preserves unsaved controls on that first
save; actual file switches still reset. The charged-surface browser regression
creates a real draft and checks persisted charge, salt and temperature.

## ISSUE-28 — GPU electrode loading and restart initialization

[x] Fixed 2026-09-14. Managed launch exposed the loader's need for `./electrode_gpu.so`;
client creation also freezes NAMD settings before the existing restart writer adds
new coordinates/output settings. Package conversion now uses explicit relative
loading and initializes after all settings. Force inputs/engine are checksum-pinned.
Native managed 4 fs pilot passes; config and fallback regressions pass. Details:
[managed GPU electrodes](docs/namd_electrode_gpu.md).

## ISSUE-29 — Process adoption matched the validation controller's shell text

[x] Fixed 2026-09-14. `_segment_pid` searched the entire command string for both
"namd" and a config filename, so a shell that mentioned them could be adopted as
NAMD and stall launch. Matching now requires a native executable plus a real config
argument. The same prepared job subsequently launched through the normal API.

## ISSUE-30 — Screening time and stationarity depended on an assumed cadence

[x] Fixed 2026-09-14. Standalone screening used a hardcoded 2 fs time axis, and the
managed health window was 60 frames. A 4 fs run with 2 ps output would mislabel time
and shorten the health question to 120 ps. DCD/segment timing is now cross-checked;
restart rollback is respected; health retains 600 ps and reports its actual span.
Sampling diagnostics use physical-time blocks and report correlation explicitly.

## ISSUE-31 — LAN viewer crashed before join when secure UUID API was absent

[x] Fixed 2026-09-20. The prepared viewer initialized its optional performance
automation bridge, which called `crypto.randomUUID()` unconditionally. A real
HTTP LAN origin lacks that secure-context method, so startup failed before name
entry. Earlier app checks used localhost, which browsers treat as trustworthy
and therefore did not cover this condition. The optional bridge now stays inert
when UUID support is absent; ordinary rendering and manual performance capture
remain available. A unit regression and production browser test on non-secure
`http://nadoc-lan.test` verify join, rendering, pointer orbit and completed metrics
with both `crypto.randomUUID` and `crypto.subtle` actually undefined. The secure
localhost project passes as well. No `main.js` change for this fix.

### ISSUE-32 — Alpine ensemble review discarded its partition before submitting [x]

- **Found:** 2026-09-21 while adding the periodic-image submission block.
- **Trigger:** Open ensemble submission review and click Submit.
- **Cause:** `dispose()` cleared `_ctx`, then the ensemble branch read `_ctx.partition`.
- **Fix:** Capture the partition with the other submission values before disposing the overlay.
- **Verification:** `md_submit_review.test.js` exercises ensemble submission with the independent image-gap override and checks the parent, partition, and payload.

<!-- ISSUE-31/32 below were independently assigned on the CPD branch; historical IDs retained. -->

## ISSUE-31 — CPD builder retained a reactant planar improper

[x] Fixed 2026-09-20. The bundled THY topology has a planar C5 improper absent
from the v6 research fixture. Native startup of a builder-created CPD reproduced
missing parameters for `CS005 CS001 CS006 CS003`. The CSV6 patch explicitly
removes both reactant C5 impropers; the static audit verifies this exact delta.
Native minimization and 2 ps dynamics passed with all lesion stereocenters intact.
Evidence: `.development-artifacts/cpd-builder-integration-v1/native_check.json`.

## ISSUE-32 — Raw solute coordinates could bypass CPD placement

[x] Fixed 2026-09-20 during strand-builder integration. The solvation builder
applied `solute_coords` after audited product placement, permitting reactant
coordinates to overwrite the product. Formed products now reject that raw
coordinate override and graphene-only topology omission. Atomistic seed models
still go through placement and topology audits. Regression covers both bypasses.

## 2026-09-22 VR inspector validation: unrelated backend gate failures

`just test-smart` selected FAST (full suite deferred without a test session):
8,685 passed, 30 failed, 9 errors, 118 skipped. Recheck after the current workspace
changes settle; no baseline checkout was used, so these are not asserted to be
pre-existing. Failures are outside the inspector files: absent workspace
`smallO-poly.nass`, oxDNA physics-build rejection, aptamer fixture initialization,
animation seek geometry and photoproduct round-trip metadata. Full output retained
at `.development-artifacts/scrywrite-inspector/validation/test-smart.log`.

Timing triage: real upstream oxDNA hybrid execution (8.10s) moved to the existing
slow/oxdna registry; default-preset unit test no longer probes host NAMD. The
Chudoba compiler fixture took 0.33s alone versus 8.16s contended and stays fast.
Ten further offenders in the 68s fast rerun all passed in isolation (0.01–1.78s
calls; 9s guarded run); they stay fast per ISSUE-20. Budgets unchanged.

## 2026-09-22 — Live VR matrix transport interruptions (open)

Combined, capture-heavy Extrude runs intermittently abort with either a motion
lateness error (250 ms versus the unchanged 150 ms budget) or a three-second
Unix-socket timeout. Native viewing resumes focused; input cleanup releases held
buttons. Root cause is not established; do not label this a profile failure or
silently retry input mutations. Retained examples:
`.development-artifacts/scrywrite-inspector/visibility-03/profiles-1790105505697705522/report.json`
and `visibility-05/profiles-1790106183551253079/report.json` under the same root.
New single-profile reruns (`extrude_probe --preset`) avoid repeating already checked
profiles; failures now retain operation/frame/sequence context in report.json.
The timing/transport budgets remain unchanged. This infrastructure issue is separate
from the reproducible variable-profile wheel-detent overshoot and visible-path fixes.

## ISSUE-33 — null native tool draft stops VR event polling

- [x] Guard target resolution when native tool_config draft is null.
- Reproduced in physical fit/undo run: browser pageError at main.js target_identity access after configuration sequence9; polling stopped before valid painted preflight.
- Root cause: optional chaining returns undefined, and undefined !== 'none' incorrectly treated a missing draft as a target snapshot. Guard existence before comparing; same fix for plane-pick branch.
- Regression: vr_painted_commit.spec.js dispatches null draft before valid paint and commit/undo. Validation recorded in VR fit artifacts.

## ISSUE-34 — VR status reader races launch publication

- [x] Publish complete private session JSON with atomic rename; readers never unlink.
- Physical test launch failed chmod because another status reader removed its partially written state. Native process existed but status reportednone.
- Focused tests observe old record until replace and simulate an invalid old read racing a new record. Owned orphan terminated; diagnostic restored.
- Physical launch/commit/Undo passes after fix (fit-undo-atomic).

## ISSUE-35 — autosave invalidates native topology refresh

- [x] Retry snapshot publication for a newer revision of the same design, at most three attempts; never replay extrusion.
- Reproduced with real six-helix42-bp VR paint: commit201, save-workspace advances revision, scene-refresh409 during serialization. Native remains empty.
- Regression covers same-design revision advance, unchanged revision, and switched document refusal. Physical confirmation recorded in sixhb artifacts.

## ISSUE-36 — confirmed autosave leaves VR preflight revision stale

- [x] Lightweight confirmed-save acknowledgement includes design_id, previous_revision and revision captured under the state lock.
- Browser advances watermark only for its current design and exact previous watermark, without replacing Design or restarting autosave.
- Reproduced live: all painted cells acquired, repeated frame preflight409 with expected_revision4 after a confirmed autosave. Frontend-only fix was insufficient because the response omitted revision; failure retained.
- Unit regressions cover concurrent edits, document switch and stale acknowledgements. Physical existing-frame commit/Undo/edit/save/reload passes with complete fix; scene serialization remains slow.
- Evidence: `.development-artifacts/vr-workflows/existing-frame-complete/`, save-ack test logs.

## ISSUE-37 — native End selection returns default selection mode in live workflow

- [ ] Diagnose native selection-level publication/browser feedback ordering.
- New physical end probe reaches a visible terminal using captured depth and the
  production selection sphere (12cm in front of controller). Submitted-eye image
  confirms overlap. Browser feedback reports selection_level default and two
  strand owners; native selection_kind stays none after5s. No geometry committed.
- END was requested through the options menu. Root cause not established;
  reordered Paint exit before END still fails. Stop repeating unchanged probe;
  inspect native level state/event publication and browser event ordering next.
- Evidence: `.development-artifacts/vr-workflows/end-observed/` (trace, pick/
  selection-volume stereo) and `end-level/`. All temporary workspaces cleaned;
  idle diagnostic viewer restored and observed focused in end-restored.json.

### ISSUE-37 follow-up — menu acquisition and event ordering separated

- Live hover assertions show END was not hit: aiming with the hand holding the
  wrist menu changed the target. Two-hand setup (left menu/right input) fixes
  acquisition; end-two-hand trace now reports selection_level end.
- Fixed two code ordering hazards separately: browser processes mode before
  selection from one poll; native ignores level feedback predating a newer local
  choice. Frontend event-order regression and native sequence guard tests pass.
- End commit still unverified: acquired selection contains two terminal owners
  plus an axis alias mapping to the distant end. Record below, not a mode failure.

## ISSUE-38 — end volume acquisition includes coarse spanning axis owners

- [ ] End-mode sphere on a visible terminal returns multiple end owners, including
  a remote endpoint from a spanning axis alias; browser correctly refuses a single
  tool target. Two terminal nucleotides at the local face are also within25mm sphere.
- `selectionVolumeOwnerToken` picks the first matching typed alias; current
  `resolveSelectionVolumeHits` also forwards unresolved coarse identities.
- Need explicit exact-end acquisition behavior/diagnostic scale and a regression
  excluding distant endpoints. Do not weaken target identity or silently widen
  extrusion scope. Evidence: end-two-hand trace and selection-volume eye images.

### ISSUE-38 checkpoint — live exact-end continuation succeeds

End-mode owner lookup now rejects primitives with multiple end aliases instead
of choosing the first; unresolved End primitives are excluded from selection.
Native regression covers ambiguous axis, interior and exact terminal cases.
The physical probe targets a visible terminal backbone bead (ideal pixel/depth
acquisition), verifies the selected owner and commits42→63bp on exactly one helix.
Native Undo restores42/42; cadnano edit/save/reload preserves210nucleotide positions.
`end-roundtrip-framed` passes. Broader coarse primitives with only one remote end
alias, arbitrary multi-end usability, noisy acquisition and through-lens visibility
still need coverage; do not generalize this diagnostic to all end picking.

### ISSUE-38 spanning single-end alias follow-up

End filtering now also excludes `segment:` identities even if their alias list
contains only one end. Regression covers this formerly ambiguous coarse case.
Physical end-segment-filter passes exact Confirm/Undo/cadnano edit/save/reload.
Dense multiple exact terminals still remain a user acquisition/usability concern;
no arbitrary owner selection or extrusion-scope widening was added.

### ISSUE-38 combined-workflow scale evidence

The12helix combined workflow could not acquire the visible terminal at its initial
recentered scale (`combined-authoring`). A recorded4×normal two-hand zoom allowed
exact end acquisition and continuation (`combined-zoom`, `combined-transition`).
No selection tolerance or owner-scope changes. This diagnoses an acquisition-scale
usability boundary; noisy acquisition remains unresolved, not closed by ideal zoomed input.

## ISSUE-39 — Tools menu Extrude does not open paint tablet

Reproduced through profiled visible Tools→Inspect→Extrude clicks in physical viewer
(menu-activation-real). Tool settings open but extrude.open staysfalse.
Radial/semantic activation initializes the lattice; the tools-menu branch omitted
that block. Existing framing helper also hid the discrepancy by activating tools
internally; it now accepts an explicit visible-UI callback. Extract existing lattice
initialization to one shared helper and invoke it from both paths. First fix alone
exposed a second gate: ToolShell classified targetless Extrude as unsupported,
so the menu never entered configuration. Targetless Extrude now explicitly requires
configuration; other tools retain their selection requirements. Native regression
added; menu-capability-fixed physical VR-first roundtrip passes. Native36tests
and26focused tooling tests pass. Shared initialization opens the tablet through
visible menu controls, including framing callbacks, without semantic activation.
No geometry or input-tolerance change.

## ISSUE-40 — VR labels silently drop minus signs

Observed in settings-targets-steady/wheel-before-drag/left.png: intended -1 BP
renders as 1 BP, DIRECTION - loses its sign, and SIZE - is indistinguishable by
sign. Root cause: stroke_font.hpp supports '+' but omits '-' and defaults unknown
characters to blank glyphs. The numeric target/hover checks still pass, so they
cannot establish label clarity. Add the horizontal minus glyph and regression
that it differs from both blank and plus. No action IDs or numeric behavior change.
Validation and submitted-eye review: settings-sign-* artifacts; status recorded
in settings-targets-validation.md. This mechanical correction is within the user's
explicit VR UI clarity goal.

## ISSUE-41 — Native authored-pixel presence check accepts an unhelpful review view

Resolved for opt-in authored-geometry review checks2026-09-23; physical headset
comfort and authoring-trace delivery remain separate open validation work.
Originally observed in combined-profile-approach/freeform/framed/left.png.
Desktop reload image usefully shows both bundles. Native1852x2056submitted eye
has only82x64authored-pixel bounds (1383nonzero IDs); the >=100pixel assertion
passes despite poor review visibility. Native view is largely end-on. Do not infer
missing/malformed geometry: independent19helix/2frame/1554position save-reload
oracles pass. Whether additional scale/bounds behavior contributes remains unproven.

Next: improve observation via ordinary view rotation/zoom, retaining original
capture as the failed observation condition; verify useful nonempty projected
bounds and distinguish both frame groups. Strengthen the visibility oracle with
negative tiny/offscreen cases. Check delivered desktop mirror separately; native
submitted eyes are not through-lens evidence. Do not enlarge hitboxes or alter
canonical geometry to fix an observation condition. See cell-approach-validation.md.

Resolution: `tools/vr_workflows/review_view.py` applies ordinary grip rotation and
bounded scale gestures after authoring, retaining the original view. Both-eye
coverage, per-cluster visible primitive counts and RGB checks reject tiny, blank,
edge-clipped, missing-group and black-image cases. Enable `NADOC_VR_REVIEW_VIEW=1`
and `NADOC_VR_DESKTOP_REVIEW=1`. Combined and variable_deliberate VR-first pilots
pass independent geometry/round-trip and actual X11 mirror checks. Configuration
and scene revision remain unchanged by observation. Existing legacy presence-only
checks remain when flags are absent. Evidence: `.development-artifacts/vr-workflows/review-view-validation.md`.

## ISSUE-42 — Simulations browsing prepares an entire assembly; recommendation GET rejected

2026-09-27: [x] Opening Simulations reached automatic availability/list/recommendation
requests which all unconditionally materialized the assembly into the Design slot.
The recommendation also supplied a body with GET, rejected by real Chromium.
Request preparation now distinguishes passive browsing from design consumers;
assembly facts and job identity no longer require flattening. Failed preparation
cannot launch against stale Design state. See
`docs/audits/assembly_simulations_20260927.md` for the reproduction, parity scope
and validation. No scientific topology or physical sampling changed.

## ISSUE-43 — Assembly FEM launch rebuilds browser geometry and polling rehashes full topology

CanDo/SNUPI assembly launch prepared a full frontend Design projection before creating
jobs; matching backend fingerprints could then incorrectly select live-part geometry
for assembly result display. Preparation and large result reads also occupied the API
event loop, while FEM polling bypassed the shared revision fingerprint cache.

Fix: compact backend-only preparation, snapshot-owned display, worker-pool API work,
shared revision fingerprint cache, CPU launch policy and failure-safe optimistic rows.
The native BigO check additionally exposed a no-RMSF node-summary error: unpaired
terminal bases were counted as duplex nodes. Counts now use the FEM axis records.
Validation and expensive-mode limits: [execution audit](docs/audits/assembly_fem_execution_20260927.md).

## ISSUE-44 — CanDo thermal reconstruction repeats immutable geometry and hides progress

BigO's 48 thermal frames rebuilt full reference geometry and discarded full
orientation/axis records on each iteration; progress updated only every five frames
and gave all thermal work an 8% weight. Stop waited for the whole prediction.
Fixed with a job-local numeric reconstruction context, XYZ-only frame path,
bounded statistics/streaming persistence, per-frame labels and cancellation
boundaries. The original full reconstruction remains the representative geometry
path and numerical oracle. [Evidence and limits](docs/audits/cando_thermal_optimization_20260927.md).

## ISSUE-45 — Completed BigO CanDo views freeze during scene rebuilds and joint remapping

Four result modes rebuilt detailed geometry or performed quadratic cylinder-joint
mapping; hidden shared source meshes remained in render traversal. Stale loads
could override newer mode choices, and large metric graphs downloaded full JSON.
Fixed with compact exact-position point/line displays above 50k nucleotides,
indexed joints, root visibility, bounded transport/caches, cancellation epochs,
and GPU scalar recoloring. Detailed small-result views remain available. See
[visualization audit](docs/audits/cando_visualization_guards_20260927.md).

## ISSUE-46 — Simulation fingerprint cache can match a recycled object ID

Closing and reopening a document can recycle the Python design object's ID at
the same revision. The cache now verifies a weak reference to the actual design
before returning its fingerprint, avoiding stale results without retaining closed
large designs. A deterministic ID-reuse regression and all 18 staleness tests pass.

## ISSUE-47 — SNUPI result views rebuild large scenes and unbounded trajectories

SNUPI retained the pre-guard FEM visualization paths, uncancelled panel races and
per-job metric caches. Dynamics downloaded every JSON frame and rebuilt position
objects on every tick. Static modes now reuse the bounded compact renderer and
metrics controller; trajectory playback indexes and loads one frame at a time,
reuses GPU buffers and cancels stale scrubs. [Audit](docs/audits/snupi_visualization_guards_20260928.md).

## ISSUE-48 — VR representation acknowledgements fall back to Full; selective loads erase Full

- [x] Share all eleven representation names across both browser publishers.
- [x] Install only genuinely available native blocks; injected reference axes do
  not replace Full geometry or blank Beads.
- [x] Reuse desktop cylinder geometry/default radius and persisted colors; draw
  sidebar aiming rays before trigger presses.
- [x] Add actual browser acknowledgements and per-representation stereo model
  pixel checks to the reusable VR tour.

The stale four-name API allowlist caused the 99% state despite desktop success.
A separate nonempty-block test confused injected reference axes with requested
geometry. See [audit](docs/audits/vr_representation_parity_20260929.md).

## ISSUE-49 — VR shadow parity and continuous sidebar navigation (2026-09-29)

- [x] Stick/Ball & Stick bonds bypassed lighting via a GL_LINES branch; use the
  shared cylinder color/shadow geometry and lighting path.
- [x] Touchpad focus could not reach off-page rows; reveal one adjacent item with
  a 200 ms eased transition, including simulation jobs/visualizations.
- [x] Clip moving row graphics and hit boxes consistently; retain fixed custom
  headers, prevent inverted offscreen hit rectangles, and clamp scrollbar thumbs.
- [x] Indent category descendants from catalog ancestry rather than label guesses.

Verification and retained failed attempts: [audit](docs/audits/vr_shadow_scroll_20260929.md).

## ISSUE-50 — Representation loading blocks VR frame delivery (2026-09-29, OPEN)

- [x] Reproduce with real browser launches and controller-selected Stick,
  Ball & Stick and Surface; retain end-to-end CPU phase traces.
- [x] Locate 226–806 ms style-application blocks outside the old frame timer.
- [x] Reproduce a separate 112 ms Surface frame gap at 49.198%.
- [x] Attribute the earlier gap: synchronous avatar-state publication (335 ms).
- [x] Move CPU preparation off the XR loop; stage GPU uploads within a budget.
- [x] Preserve bounded resident caches, add loading guards and frame-time gates.
- [ ] Resolve residual XR submission/presentation waiting: final 73.87 ms gap
  with nearby SteamVR wait-for-present 62.13 ms (GPU <5.87 ms).
- [ ] Complete all four controller profiles without replay deadline failure
  (three completed; variable_deliberate failed at 162 ms) and headset comfort review.

Diagnosis and primary-source research: [audit](docs/audits/vr_loading_stalls_20260929.md).
Implementation and finer profile: [follow-up audit](docs/audits/vr_loading_frame_delivery_20260929.md).
Reaching 100% is functional success, not evidence of comfortable frame delivery.

## ISSUE-51 — Detailed VR representations trail during motion (2026-09-29, OPEN)

- [x] Record the user's baseline: loaded-model motion was satisfactory before
  the loading-freeze changes; treat new blur/lag as a regression.
- [x] Remove speculative lighting/shadow optimizations and restore original
  head-relative lighting and shadow rendering, including removal of shadow reuse.
- [x] Compare legacy/staged GPU uploads with the same saved Stick scene: identical
  final pixels and approximately equal 5.5 ms median GPU time.
- [ ] Isolate remaining post-load frame-delivery regression in the real runtime.
- [ ] Complete all four motion profiles and physical-headset review.

[Investigation and retained unsuccessful experiments](docs/audits/vr_motion_regression_20260929.md).

## ISSUE-52 — Hidden animation slab connectors contain NaNs (2026-09-30, FIXED)

- [x] Reproduce by fading a slab to zero scale; its connector matrix becomes
  nonfinite and the shared-presentation host rejects the frame.
- [x] Skip rotation decomposition for collapsed slabs and hide their connectors
  with a finite zero-scale matrix. Visible slab placement is unchanged.
- [x] Regression test covers the hidden endpoint and restoration to visible geometry
  in `helix_renderer.simulation_visibility.test.js`.

## Archive transfer progress appears stalled during a large file — 2026-10-03

- **Status:** Fixed 2026-10-03 after the original transfer finished; user explicitly authorized the fix and recovery of a later interrupted cube_pore move. Copy progress now advances every 8 MiB; frontend reports a lost/idle task after restart instead of polling forever. Regression reproduced red before implementation; 22 archive tests and the frontend interrupted-task test pass.
- **Observed:** Change directory for `small_plate` production job `a5e2cf157a76` to `/mnt/f/NADOC/a5e2cf157a76` shows roughly 1.2 GiB (1%) and appears stopped.
- **Read-only evidence:** `/api/md/jobs/a5e2cf157a76/archive-status` reports `state=running`, `error=null`, `moved_bytes=1318619828`, `total_bytes=201664351423`. Meanwhile the destination `package/small_plate_namd_solvated/output/small_plate_01_production_200ns_k0.dcd` grew across checks from 643,497,984 to 2,162,028,544 to 3,809,603,584 and now 23,384,252,416 bytes. The transfer is progressing; the displayed count excludes the current file.
- **Confirmed cause:** `backend/core/job_archive.py::_copy_tree_with_progress` calls `shutil.copy2(s, d)` for an entire file, then increments `progress['moved_bytes']` only after it returns. Frontend polling displays the stale backend counter correctly. This is transfer-progress reporting granularity, not evidence of a stopped copy.
- **Follow-up after completion:** Add progress within a single large file (bounded chunk copying or another low-overhead mechanism), preserving metadata, copy-then-delete safety, rollback behavior, and throughput. Pin a regression test proving progress advances before the first large file finishes; verify monotonic totals and failure handling.
- **Operational constraint:** Do not edit backend/scripts, restart/reload NADOC, cancel, remount, or modify source/destination files during this transfer. The move task runs in a background thread and would be interrupted by a backend reload. Verify terminal transfer status and destination/index consistency before starting the fix.

**cube_pore recovery completed (2026-10-03):** Interrupted Alpine production job
`a4cb52583c26` resumed and verified against its original using SHA-256 for all
37 files. Archive index updated, original removed only after verification; archived
job loads successfully. Audit: `.development-artifacts/archive-recovery-cube-pore-20261003/`.

## ISSUE-53 — Backend FAST environment failures during tool validation (2026-10-04, OPEN)

Reproduced with `just test-smart`: 9,633 passed, 19 failed, 17 skipped. Ten VR
representation tests require missing `native/vr_viewer/build/nadoc-vr-viewer`;
seven photoproduct review tests require an unavailable external definition-review
packet; VR startup rejects this WSL host; CPD snapshot-refresh preservation fails
its coordinate comparison. These failures are outside the design-tool changes.
Evidence: `.development-artifacts/tool-selection-clear-20261004/backend.log`.
Next: reproduce in the relevant environment/fixtures; investigate the CPD
comparison without updating locked scientific geometry or its reference data.
The 186 s aggregate runtime warning has no per-test violators (maximum 4.06 s);
the run overlapped the frontend suite. Slow-test triage made no classifications
or budget changes because no individual heavy test was identified.


Linear-pattern validation follow-up (2026-10-04): `just test-smart` chose **FAST**;
9,640 passed, the same 19 failures, 17 skipped, 243.15 s. FULL remains deferred.
Six timing flags occurred while the backend, frontend and browser suites competed
for CPU. Isolated `just test-focused` reruns all passed below 5 s per test
(including setup); no marker or budget changes were warranted:

| Test | Contended call (s) | Isolated call (s) | Work measured |
|---|---:|---:|---|
| `test_undo_cap_enforced_for_large_assembly` | 8.64 | 1.59 | 15 history snapshots of 2,000 instances |
| `test_display_route_surfaces_extension_tails` | 6.65 | 1.41 | 6HB routing and mocked relaxation display |
| `test_teeth_spec_matches_hand_calls` | 5.79 | 0.80 | Two equivalent bundle/extrusion builds |
| `test_prepare_excludes_both_extra_bases_topology_exactly` | 5.78 | 1.47 | Small atomistic export and mocked solvation |
| `test_display_route_surfaces_extra_bases` | 5.70 | 1.40 | 6HB routing and mocked relaxation display |
| `test_namd_bundle_zip_contents` | 5.05 | 0.51 | 6HB atomistic PDB/PSF archive generation |

Evidence: `.development-artifacts/linear-pattern-test-smart.log` and
`.development-artifacts/linear-pattern-timing-triage.log`. No broad rerun was
needed to re-diagnose the already-known missing-environment failures.

Custom-vector/UI follow-up: FAST has 9,644 passes, the same 19 failures, and
17 skips (115.65 s pytest / 121 s guard). FULL remains deferred. The timing report
has no per-test violators (maximum 4.39 s across 9,680 cases); the frontend suite
ran afterward. Slow-test triage found aggregate suite cost rather than an
individual over-budget test, so no classifications or budget changes were made.
Evidence: `.development-artifacts/linear-pattern-custom-smart.log`.


Headless parity follow-up (2026-10-11): final `test-smart` decision **FAST**;
10,529 passed, 90 skipped, one archive timeout and four CPD fixture errors
(121.62 s). **FULL DEFERRED**, recorded in `.nadoc-slow-pending`. The CPD preview
fixture rejects `cis-anti-I` after separate working-tree chemistry-definition
changes; those scientific assets were left untouched. The archive test's path
does not call the new runtime; its retry passed in 0.32 s. All six timing-flagged
tests passed in an isolated 6.06 s run (individual calls 0.23–0.85 s); no genuine
heavy work or reclassification. An earlier run's three IPC failures were caused
by overlong AF_UNIX paths under the archive TMPDIR; a shorter test-owned path
resolved them. The earlier native review-gate timing flag fell from 10.4 s to
0.30 s on retry. Polling responsiveness tests now bind a temporary workspace for
every engine catalog, avoiding real workspace scans; all ten pass in 1.31 s.
No test budgets or guards changed.

Frontend validation: 7,796 passed, one skipped, two unchanged
`md_jobs_panel.test.js` RAM-confirmation failures (lines 2067/2109), reproduced
in isolation. Readiness app exercise: two passed; smoke: 23 passed. Lint has five
unrelated unused-import findings in VR prompts and CPD tests. Evidence and exact
failure names: `.development-artifacts/headless-api-parity-20261010/`.

## ISSUE-54 — Pattern confirmation treated rejected requests as success (2026-10-04, FIXED)

[x] `createCircularPattern` previously passed `_request`'s null failure through the
sync helper. The tool then closed its preview as though creation had succeeded.
Circular and linear request wrappers now reject with the recorded backend error,
so the panel retains its inputs and preview for correction. Covered by
`frontend/src/api/pattern_requests.test.js` and the linear panel rejection test.
## ISSUE-59 — All-helix cluster creation leaves a dangling lattice placement reference (2026-10-05, OPEN)

- **Status:** `[ ]` OPEN; observed during the native-tool Benchy benchmark. The saved design was repaired through existing tools; product cluster code is unchanged.
- **Repro / observed:** Create a square-lattice bundle, continue it with `hb.extrude`, then call `hb.add_cluster(..., helix_ids=all_helix_ids)` and save normally. The resulting Benchy file has 1,157 helices and one new cluster, while `lattice_frames[0].placement_cluster_id` still names the removed default cluster. `Design.from_json(...)` rejects the saved file with `Value error, lattice frame placement cluster is missing`.
- **Confirmed location:** `backend/api/routes_clusters.py::add_cluster` removes an emptied default cluster from `cluster_transforms`; the observed output retains its ID in `lattice_frames`. No broader behavior is inferred.
- **Evidence:** [Retained invalid native design](.development-artifacts/benchy_20261005/Benchy_v4_initial_invalid.nadoc), [frame/cluster IDs and native reload error](.development-artifacts/benchy_20261005/cluster_bug_evidence.json).
- **Benchmark workaround:** Keep the existing placement cluster and rename/patch it through `update_cluster`, then save normally. The corrected file passes native reload; see [final native geometry validation](.development-artifacts/benchy_20261005/native_model_validation.json).
- **Follow-up:** Pin a minimal create-cluster → save → native-reload regression before changing placement-cluster handling.

## ISSUE-60 — Extruded fresh cells are omitted from default placement-cluster membership (2026-10-05, OPEN)

- **Status:** `[ ]` OPEN; observed during the native-tool Benchy benchmark. Only the benchmark design received a native membership patch; product extrusion/cluster code is unchanged.
- **Repro / observed:** Create 443 square-lattice cells, then call `hb.extrude(..., extend_inplace=True)` for successive contours containing fresh cells. The completed design has 1,157 helices, but its default placement cluster still contains only the original 443. Moving that cluster by `[-1.649, 0, 0]` nm moves 443 helices and leaves 714 unmoved. Actual occupied-domain geometry then differs from the intended uniformly moved reference by 972 missing and 874 extra sampled cell-slabs.
- **Evidence:** The final saved file's last `extrude-continuation` post-state still records the 443/1,157 membership before the workaround; [read-only extracted counts and observed movement](.development-artifacts/benchy_20261005/cluster_bug_evidence.json). [Native build log](.development-artifacts/benchy_20261005/build.log) records the contour growth. Entry points to investigate are `backend/api/headless_build.py::extrude` and its native bundle-continuation route; no deeper cause has been established.
- **Benchmark workaround:** Use native `update_cluster` with `PatchClusterBody(helix_ids=all_1157_ids, commit=True, log=True)`, retaining the intended whole-model Move, then save. [Native domain validation](.development-artifacts/benchy_20261005/native_model_validation.json) now matches all 11,984 measured cell-slabs with zero missing, extra, or off-grid intervals; [occupied-domain renders](.development-artifacts/benchy_20261005/native_model_views.png) preserve the openings.
- **Follow-up:** Pin a minimal fresh-cell continuation → default-cluster Move regression and verify membership/placement after normal save/reload.

## ISSUE-55 — Native atomistic and print export fail above 702 strands (2026-10-05, FIXED)

- [x] Reproduce the 3,062-strand Benchy failing before surface extraction: `build_atomistic_model` indexes beyond `A`…`Z` while assigning chain 702.
- [x] Replace the two-letter limit with shared alphabetic chain labels (`A`…`ZZ`, `AAA`…), preserving all existing 702 labels. Generalize PDB single-character cycling and the matching NAMD package/playback encoders.
- [x] Verify 24 focused chain tests, including a real 3,062-strand atomistic model and legacy semantic component IDs such as `ST0`. Existing NAMD segment-order, streptavidin preparation, and large-design PDB-connectivity compatibility tests also pass. Native Benchy print export now completes.
- **Scope:** Identity bookkeeping only; no topology, atom placements, phase constants, or surface algorithm changes. See `backend/core/chain_ids.py`, `tests/test_chain_ids.py`, and [native export provenance](.development-artifacts/benchy_20261005/Benchy_v4_candidate.provenance.json).

## ISSUE-56 — VR Extrude Confirm leaves editing windows open; menu text collides or fades (2026-10-05, FIXED)

- [x] Accepted Confirm dismisses the painter and right-hand menu immediately, freezes the submitted target/configuration, and clears the successful draft while retaining feature-bound Undo. Failed/refused commits restore the draft with fresh validation.
- [x] Audit all sidebar tabs, tool pages, legacy menus, desktop chrome, View Tools, loading panels and component galleries. Separate titles/subtitles/value columns, bound dynamic text, retain padding and readable tab labels, and keep text clear of controls, progress bars and borders.
- [x] Correct transparent-menu alpha handling, framebuffer restoration during cache allocation, and texture aspect preservation after the width cap; wide desktop headers retain visible lettering.
- **Evidence:** 12,001 layout states, 425 production-rendered states, native lifecycle regressions, the full frontend suite, and an actual browser-backed VR commit. Initial observation failures and human-headset limits remain recorded in the [audit](docs/audits/vr_menu_formatting_20261005.md).

## ISSUE-57 — Nick tour cannot reliably observe scissors and bond glow together (2026-10-05, OPEN)

- **Status:** `[ ]` OPEN. Found during right-touchpad-wheel regression work; wheel selection succeeds before this failure.
- **Repro:** `uv run python -m tools.vr_workflows.nick_tour --validate --profile steady_fast`. The isolated one-helix fixture fails the existing stereo/mirror scissors-and-glow coverage requirement at open, half, or almost-closed squeeze.
- **Confirmed test defect fixed:** `nick_pixels.py` projected blades along controller +Y although the current renderer and quiver oracle use controller -Z. Its corrected projection has an independent unit check. `audit_observation.py` now uses the same forward-axis contract for clearance.
- **Remaining evidence:** `.development-artifacts/vr-edit-wheel-20261005/nick/` and the retained `nick-visible`, `nick-final`, `nick-face-on`, `nick-clear`, `nick-review-size`, `nick-beside`, and `nick-scaled` attempts. The corrected oracle passes the retained `nick-visible/open` frame, but that does not clear the whole workflow.
- **Failed observation approaches:** near-side target selection, face-on wrist, contact offsets within the unchanged selection radius, enlarged mirror, and ordinary grip zoom did not establish all squeeze states. Experimental pose/zoom adjustments were removed from the maintained probe. No production geometry or pixel thresholds were changed.
- **Follow-up:** diagnose blade/model/glow occlusion across squeeze states before changing rendering or accepting a new observation setup. The separate right-wheel document-history tour verifies Undo/Redo without depending on scissors visibility.

## ISSUE-58 — Ligate tour stretched-preview pixel coverage fails (2026-10-05, OPEN)

- **Status:** `[ ]` OPEN; discovered during right-wheel regression work after Ligate was selected successfully through thumb input.
- **Repro:** `uv run python -m tools.vr_workflows.ligation_tour --validate --profile steady_fast`. The isolated one-helix fixture acquires an end and rejects a same-polarity release, then fails at the stretched-preview pixel assertion before committing a bond.
- **Evidence:** `.development-artifacts/vr-edit-wheel-20261005/ligate/`. Coverage is 3/7 left-eye samples and 2/7 right-eye/mirror samples, below the unchanged 0.7 requirement. Captured state, images and input reaches are retained.
- **Scope / follow-up:** No Ligate geometry or preview renderer was changed by the wheel conversion. Diagnose projected-line occlusion and observation setup before assigning a production root cause or altering the oracle. This failure does not establish whether later commit/save/Undo steps pass; they were not reached.

## ISSUE-65 — Native cluster creation loses attachment ownership during history replay (2026-10-08, FIXED)

- **Status:** `[x]` FIXED during generator conversion to ordinary operations.
- **Repro / cause:** Seeking to an attachment's native Create cluster entry could omit its parent and duplex driver, because the entry only retained helix/domain membership. Snapshot substitution also omitted original groups when seeking before generation.
- **Fix:** Optional full cluster-creation snapshots preserve ownership; a small replay helper reconstructs active creations before pose replay. Native generator snapshots restore the full cluster baseline; legacy v1 histories retain compatibility.
- **Evidence:** `tests/test_feature_history_clusters.py`; all 98 history boundaries in the isolated `4NP_standard_operations.nadoc` review passed. Geometry equivalence remains 28,428 positions with maximum delta 0 nm.

## ISSUE-61 — Pending-review regression was not isolated from WSL platform rejection (2026-10-07, FIXED)

- **Status:** `[x]` FIXED; discovered during readiness-feature FAST validation. The test-only platform isolation is verified and the infrastructure incident explicitly reviewed. Runtime platform policy, placement geometry, and review-gate behavior are unchanged.
- **Observed / cause:** `tests/test_native_placement_vr_failure.py::test_pending_review_prevents_relaunch_without_duplicate_incident` expects the structured `NATIVE_PLACEMENT_REVIEW_REQUIRED` response. On this WSL2 host, `launch_vr` calls `_require_local` first and receives the platform rejection as a plain-string HTTP 503. The test's `detail["code"]` assertion then raises `TypeError` at line 121, before the pending-review check is reached.
- **Incident handling:** The test's synthetic `NativePlacementError("Review me")` uses its temporary incident directory. Separately, `tools/native_placement_audit/pytest_plugin.py` intentionally retains the outer marked test failure in the durable directory captured at pytest configuration. Thus this report records a test/platform precondition failure; it contains no measured placement discrepancy. It is not evidence that the temporary incident store leaked.
- **Evidence:** [Preserved incident report](.native-placement-review/incidents/20261007T180833-b0aaf4e5ebcb/report.json), incident `20261007T180833-b0aaf4e5ebcb`; the failing host's `/proc/version` identifies `microsoft-standard-WSL2`. Original report, source traces, and focused logs remain retained.
- **Focused remediation (2026-10-07):** The single pending-review test now stubs only `_native_platform_reason`, retaining real locality checks and all runtime behavior. All 18 VR-failure assertions pass; that pre-acknowledgement process exited 1 for the preserved unresolved incident. All four supported/unsupported-platform cases pass separately. No molecular coordinates were evaluated by the original failing call; this fix makes no molecular-placement certification.
- **Review completed:** After inspecting the candidate review and source trace, Codex (OpenAI coding agent) explicitly acknowledged this incident at `2026-10-07T18:22:10Z`. The [recorded review](.native-placement-review/incidents/20261007T180833-b0aaf4e5ebcb/review.json) binds the original report SHA-256; the explicit audit check is clear and the journal has no pending incidents. A passing rerun did not clear the gate. See ISSUE-53 for separate broader-suite environment failures.

## ISSUE-63 — SNUPI PDB reader drops adjacent negative coordinates (2026-10-07, FIXED)

- **Status:** `[x]` Fixed during the three-design Exp comparison.
- **Repro:** Official SNUPI platform output contains `11.250-155.885` in adjacent 8-character coordinate fields. Whitespace parsing silently returned 5,572 of 6,766 graph nodes.
- **Root cause:** The reader assumed separators between every coordinate even though SNUPI writes PDB-width xyz fields.
- **Fix:** Preserve the existing whitespace reader and fall back to xyz columns 30:54 plus the existing node identity prefix. No node-order, topology or coordinate changes.
- **Evidence:** `tests/test_snupi_reference.py::test_parse_snupi_pdb_adjacent_negative_coordinate_fields`; task artifacts under `.development-artifacts/exp_local_20261007/`. The comparison still requires complete mapping and a 0.1 nm geometric residual check.

## ISSUE-64 — Requested MgCl2 absorbed by Mg counterion count (2026-10-07, FIXED)

- **Repro:** DNA -6982 e and a requested 84 MgCl2 units produced 3491 Mg / 0 Cl,
  because `ion_counts` selected max(counterions, salt). UI describes salt excluding counterions.
- **Fix:** Add salt to neutralising Mg; record the concentration convention in new
  charge audits and distinguish historical package notes. Existing packages are unchanged.
- **Evidence:** Official tutorial PSFs contain DNA -865 e / 516 Mg / 167 Cl;
  `.development-artifacts/mg_recipe_audit_20261007/tutorial_census.json`.
  Thirteen focused ion-recipe tests pass, including odd charges, zero Mg, bare ions,
  added NaCl, both salt/counterion regimes and historical/new protocol notes.
- **Regression:** `just test-smart` chose FAST: 9,978 passed, 90 skipped. FULL
  deferred without a test-dedicated session; retained log in the audit directory.

## ISSUE-62 — Fast relaxation PME cadence contradicts manifest (2026-10-07, OPEN)

- **Observed remotely:** job `8466ccc17eff` has 4 fs relaxation configs with
  `fullElectFrequency 2` (8 fs full electrostatics). Remote hashes match the local
  package. `protocol_fidelity` claims frequency 1 / 4 fs instead.
- **Location:** `md_protocols._common_header` writes literal frequency 2;
  `protocol_fidelity` reports 1. The separate production builder uses 1 at 4 fs.
- **Evidence:** `.development-artifacts/runpod_8466_audit_20261007/audit.json`,
  `remote_hashes.json`, and the submitted `24hb_0xT_04_300K_NPT_MGHH_only_p100.conf`.
- **Scope:** Read-only audit while the pod is minimizing; no dynamics yet, so this
  does not establish observed instability. No active job or production code changed.
- **Follow-up:** Derive cadence from timestep consistently, pin actual generated
  4 fs configs against manifest, and review active prepared inputs before dynamics.

## ISSUE-66 — Add Loops/Skips recomputation retains obsolete marks (2026-10-08, FIXED)

- **Status:** `[x]` Fixed while extending realization to sweeps.
- **Repro:** Seed a routed bundle with a loop at a helix end, then run Add Loops/Skips. The recomputed pattern excludes that end, but the old mark survives.
- **Root cause:** Calculation cleared a local design copy; commit merged the new marks into the original, uncleared design.
- **Fix:** Clear the active bundle helices inside the commit before applying the new pattern. Reference, overhang and linker marks remain preserved. A revision guard rejects a calculation made stale by another edit.
- **Evidence:** `tests/test_sweep_loop_skips.py::test_tool_api_recomputes_atomically_and_supports_history` covers HC/SQ, forbidden sites, repeat application, undo/redo, feature revert and JSON persistence; stale-computation and atomic-failure tests cover transaction boundaries. Existing 75 loop/skip tests pass.

## ISSUE-67 — Build animations reuse current topology and wall-clock video timestamps (2026-10-08, FIXED)

- **Status:** `[x]` Fixed under the user's construction-animation/export request.
- **Repro:** pin two keyframes several feature ticks apart. The old player blended
  only endpoints; earlier routing and deleted sites were rendered using current
  meshes. On Voltron, a future gold particle also remained visible at the initial
  state. MediaRecorder assigned export timing from render wall time.
- **Cause:** endpoint-only bake planning, current-topology mesh ownership,
  ordinary snapshot substitution omitting nanoparticle collections, and a live
  recording encoder used for offline frame stepping. Atom serials also cannot
  identify the same atom across different historical topologies.
- **Fix:** adjacent historical-state planning, external-snapshot DNA/arc/particle
  rendering, nanoparticle snapshot restoration, topology-aware atomistic frames,
  and WebCodecs/WebM encoding with explicit timestamps and frame backpressure.
  Export rejects FPS/timing combinations that cannot sample every build step.
- **Evidence:** `animation_build_sequence.spec.js` visits forward/reverse/held
  states on an isolated Voltron copy and decodes actual downloads. Pure/factory
  tests cover sequencing, snapshot restoration, missing states, encoding errors,
  and atom-identity changes. Evidence: `.development-artifacts/build-animation/`.
- **Final validation:** headed Voltron preview plus decoded Animations/Photo
  exports passed (132/22 frames, both 11s); 7,658 frontend tests passed (1 skipped),
  26 animation and 17 evaluation backend tests passed. FAST: 10,215 passed,
  90 skipped; three existing failures (mutable Benchy count, native VR IPC crash,
  disk forecast) remain. Benchy incident reviewed and acknowledged; native
  placement gate clear. Broad FULL deferred to `.nadoc-slow-pending`.
  Smoke: 23 passed; production build passed. Test artifacts were removed.
  Lint retains one unrelated unused import. Evidence and timing triage are in
  `.development-artifacts/build-animation/validation-status.json`.
- **Boundary:** State pins remain top-level feature-log ticks; routing children
  stay grouped. This does not implement assembly configuration/joint export
  (the separate open work in ISSUE-21).


ISSUE-67 sweep follow-up (2026-10-08): sweep additions now reveal along authored
path order, with reversed ordering for source-start continuations and symmetric
reverse playback. CG/atom sites scale locally; tube/surface triangles use cached
path ordering and draw ranges. Non-sweep transitions retain their existing behavior.
Surface pre-bake accepts the empty initial build state and retains nucleotide
identity for the reveal. Verified headed Full/Cylinders/Ball-and-Stick/Surface
views and decoded WebM; 7,664 frontend tests and 27 focused backend tests passed.
Evidence: `.development-artifacts/build-animation/sweep/` and `sweep-*.log`.
Sweep follow-up final gates: 23 smoke tests and production build passed. FAST:
10,216 passed / 90 skipped / three unchanged baseline failures. The two flagged
slow tests took 0.05s and 0.02s in isolated reruns (no real engine work); no budget
or classification changes. Native placement review gate clear. Test artifacts
removed. Decoded sweep video has exactly 76 frames / 9.5s at 8fps. Full validation
record: `.development-artifacts/build-animation/sweep-validation.json`.

## ISSUE-68 — UI polling falsely stops live headless simulations (2026-10-11, FIXED)

- **Repro:** start native CanDo from a separate process and poll its job through
  the UI API. The polling process's empty thread registry previously classified
  the live job as orphaned. The interrupted Benchy run exposed this defect.
- **User specification:** headless simulation operations must share the ordinary
  user lifecycle; private workspaces must not be necessary to keep a job alive.
- **Root cause:** process-local registries and child PIDs did not establish
  ownership across processes or across preparation, inter-stage and publication
  work; stale stop/recovery writes could also overwrite a new execution.
- **Fix:** `simulation_runtime.py` owns a persistent-inode kernel lease and
  generation-scoped control mailbox. All seven local native engines share it;
  start, stop and orphan writes are serialized. Workspace scope is context-local.
  Detached workers inherit ownership through a publication gate. Read-only
  legacy completed NAMD planning creates no runtime files.
- **Pinned by:** `test_simulation_runtime.py` and `test_simulation_runtime_api.py`
  cover separate processes, HTTP polling, stop/resume, actual owner death,
  workspace isolation, stale generations and detached launch/stop races. Native
  CanDo and SNUPI solver launch checks passed. Scope and limitations are in
  `docs/simulation_runtime.md`; evidence is under
  `.development-artifacts/headless-api-parity-20261010/`.

## ISSUE-69 — Native menu-spacing gate fails on existing Extrude layout (2026-10-11, OPEN)

- Repro: build/run `nadoc-vr-menu-spacing-test`; it throws `extrude: row does not align to content rails` before reaching Join.
- The identical failure occurs with untouched HEAD headers and test source at `d6e10e23aeb7149580575fa4699caf04296340c5`; retained proof: `.development-artifacts/vr-join-20261011/native-spacing-baseline.log`.
- Scope: existing Extrude layout versus the spacing oracle; root cause and intended rail alignment are not yet established. No Extrude behavior or spacing assertion was changed during Join development.
- [ ] Determine whether the layout or oracle is stale, then restore this broad native gate. Join-specific layout, footer and production GL checks pass independently.

## ISSUE-70 — Extra precursor Join connections prevent an otherwise valid brace (2026-10-11, OPEN)

- Repro: `.development-artifacts/braced-corner-20261011/braced-rounded-corner-v3/baseline.nadoc`
  plus `join-request.json`: a rounded 90-degree 1x6 Sweep and separate flat 1x6 brace,
  both ends within the requested 3 nm reach. Native preview rejects atomically with
  `Saved joins form a cycle with no native backbone available for a scaffold nick.`
- Captured root cause: the precursor matcher selects four of seven candidates.
  The two desired end attachments are compatible. Two additional adjacent side
  attachments form a 14-nt cycle containing two original nucleotides and twelve
  connector nucleotides, with no surviving native bond available to nick.
  `maximum_connections(..., routes=None)` optimizes attachment/clearance only;
  `realize_join_constraints` subsequently rejects this selected set correctly.
- Evidence: `validation/cycle-diagnosis.json` records the exact directed cycle.
  Isolated unchanged realization accepts the desired two-pair subset and either
  of two three-pair alternatives. These diagnostic alternatives are not product
  changes. The public workflow succeeds at a narrower reach; Seamed routing
  preserves all Join bonds and produces one scaffold.
- [ ] Make precursor matching respect realizability before final selection;
  retain strict rejection of cycles without a permitted native nick. A braced
  corner primitive also needs explicit two-arm/two-end coverage validation.
- No routing, placement, polarity, phase constant, or validation rule was changed
  during this feasibility investigation. This does not establish that arbitrary
  braced corners are routable in either routing mode.

## ISSUE-71 — Flexible connector geometry changes on native import (2026-10-11, OPEN)

- Repro: the braced-corner fixture at
  `.development-artifacts/braced-corner-20261011/final/routed-seamed.nadoc` passes
  topology and Join-preserving Seamed routing. Ordinary export/import via
  `tests.automation_harness.roundtrip_nadoc` changes `flexible_connections` and
  resolved connector nucleotide positions by 1.16348546 nm in the first process
  and up to 1.97979197 nm in a second process. Plain model
  JSON serialization preserves the original records and does not expose this.
- All original nucleotides, staple strands, forced bonds, rigid cluster poses,
  deformations and lattice frames remain unchanged. Both reciprocal brace-end
  attachments remain present and every exported strand remains a complete
  linear chain. The stricter geometry-preserving persistence audit fails.
  The detailed second probe moves eight connector nucleotides and zero
  nonconnector nucleotides.
- Evidence: `final/independent-validation-detailed.json` and the same-frame
  before/imported models under `final/import-drift/`. One observed connection
  swaps anchors A/B and reverses its bead order; its nucleotide identity and
  contour length are unchanged.
- Suspected mechanism: load/import recomputes the derived cache through
  `derive_flexible_connections`, which discovers marked components and anchors
  through sets. Anchor reversal changes the resolved arc in this fixture.
  Inspect deterministic ownership/ordering and reversal behavior before choosing
  a repair; do not treat arbitrary set order as molecular placement intent.
- [ ] Pin native import and cross-process ordering with a regression, review
  concrete before/after geometry, then restore geometry-preserving persistence.
  No molecular geometry formula, phase constant or topology rule was changed
  during this investigation.

## ISSUE-72 — VR range acknowledgement briefly restores old frame bounds (2026-10-12, FIXED)

- Repro: the slow/fast live range-wheel tour changes End 1225 → 515; the native
  drag trace is correct but the first acknowledged desktop snapshot says 1225.
- Cause: trajectory `configure()` called notifying `cancel()` before assigning
  new bounds, publishing the old range with the new event acknowledgement.
- [x] Suppress that intermediate cancellation notification inside configure and
  publish the completed range once; ordinary Cancel still publishes normally.
- Regression: `vr_simulation_trajectory.test.js` observes exactly one final-range
  notification. Original live failure is retained in
  `.development-artifacts/vr-range-wheels-20261012/initial/`.

## ISSUE-73 — Simulation snapshots close the right VR menu and representation changes discard results (2026-10-12, FIXED)

- User repro: load a trajectory and try to open the right controller menu beside
  the focused left simulation menu. Periodic snapshot adoption closes it again.
- Cause: `SimulationPanel::adopt` explicitly closed the adjacent sidebar; the
  representation lifecycle also cleared simulation overlays and assumed Full-only
  trajectory pages. Local page indices did not encode the sampled source frame.
- [x] Preserve both sidebars, enforce the simulation representation allowlist in
  native and desktop controls, retain physical positions/scalars, and map sampled
  page indices to exact source frames for atomistic reconstruction.
- [x] Materialize standalone/compact FEM and mrDNA views against the job snapshot
  when changing representation. Restore all representation choices on Off.
- Regression evidence: native panel tests, representation/trajectory/fallback
  tests, and the reusable dual-menu simulation tour with submitted stereo review.
  See `.development-artifacts/vr-simulation-representations-20261012/`.

## ISSUE-74 — Disabled transport controls intercept trajectory number-popup hits (2026-10-12, FIXED)

- Repro: open the source-frame popup in the focused VR trajectory menu and point
  at digit 2. Disabled frame/scrubber rows below the raised popup can win the hit.
- Root cause: SidebarMenu returns the first overlapping control; SimulationPanel
  listed the disabled background before the modal controls.
- [x] Order popup controls first, matching their visual foreground ownership.
- [x] Regression sends actual rays to all ten digit centers through SidebarMenu.
- Failed live evidence: `.development-artifacts/vr-trajectory-loop-20261012/initial/`.

## ISSUE-75 — Large exported Flex Stick renders at half headset cadence (2026-10-13, FIXED for the measured workload)

The retained `24hb_0xT` P1 Alpine Aug 7 Flex Stick workload renders about 44.763
new images/s while the compositor presents about 89.526/s. Session/eye/frame/CRC
markers decode all 179 baseline presentations in both eyes: 90 distinct application
images and 89 repeated pairs. Independently tracked molecular features hold on
reused IDs and jump up to 12 pixels on advanced IDs. Applied hand/model translation
agrees within 7.1e-8 m. Rendering cadence explains these software jumps; the user's
monocular optical symptom remains separate physical validation debt MV-44.

Same-map Full/oxDNA and small 2HB Stick render at about 90 Hz. The first exported
Full trial was stationary because recorder preparation expired the two-second
scripted-input lease. Its replacement verifies 15 cm model movement and 179 unique
consecutive IDs in both eyes. The harness now requires fresh post-ACK grip, measured
model span, pose coherence, capture-window containment and successful cleanup.

Two eye passes dominate the original dense Stick GPU interval (about 5.4 ms each),
plus about 2.1 ms shadows. Exact body/cap batch merging was slower; precomputed
normal transforms did not improve cadence. Those attempts remain preserved.
An eligible opaque fragment specialization saves about 2.6 ms but remains at 45 Hz.
Grouping eight tiny instances while preserving batch/instance/triangle order brings
moving total GPU time to 5.64 ms and restores 90 Hz. On the same binary, disabling
grouping gives 11.17 ms and 45 Hz. Shadow time stays about 2.1 ms; eye passes fall
to about 1.3 ms each. This locates the demonstrated cost in the exported eye path.

The optimized final capture decodes 179 consecutive right-eye IDs and 177 left-eye
IDs, with two left-eye component-limit rejections retained as unknown. The disabled
control decodes both eyes completely and reproduces 89 repeated pairs. Original
molecular geometry, colors, draw order and instance data are preserved. Native GL
comparisons cover exact color/depth/object IDs and ordered vertex outputs.
Both optimizations are now defaults for eligible geometry, with explicit environment
`=0` rollback and safe legacy fallback. Final default-path validation passed fast
15 cm movement and all four unchanged human-motion presets for marked/unmarked
large Stick, same-map exported Full, and small 2HB exported Stick. All remain near
90 Hz. The physical double-image symptom remains open as MV-44.

Evidence: Archive `vr-output-capture-20261012/frame-identity-20261013/index.html`.
Reusable entry: Debug → VR Tours & Tests → Controls & layout → Origami tracking.
No scientific geometry/topology changes or global SteamVR configuration changes.

## ISSUE-76 — Normal VR launch reopened the original renderer and recorder (2026-10-13, FIXED for normal-launch integration)

Normal API launch now selects the versioned optimized native build and final-output
recorder through owner-controlled Archive configuration. It provides an inspect
socket, pose journal, recording-only markers and executable provenance. Journal
failure prevents a complete-diagnostics claim; configured recorder failure is
explicit rather than silently using application-eye capture. Fresh status probes
retain the original launch readiness snapshot separately.

The real Tools action saved 179 final images with zero accounting drops; a second
recording on the final physical inspect viewer also saved 179. All-frame pixel
audits verified both clips and durable direct-I/O persistence. Final calibrated
decoding joins all 716 eye images to exact CRC/session/eye/frame records: 179 unique
consecutive IDs per eye per clip, matching both eyes, with zero repeats, gaps or
regressions. The wide ROI and first tight-ROI failures remain recorded. The fix
ignores already subminimum components before the unchanged 64-candidate cap;
other acceptance thresholds are unchanged. ROI calibration used menu frame 0 only;
178 later menu frames and all 179 physical-inspect frames were held out.
These stationary checks validate integration, not the user's torso bug.

Integration checkpoint proof: normal-managed viewer 378253/start 96081361, native SHA256
1e830a7fd2e8c273cec04aba917e64903ccc3b166a692659158314cac8c53b76;
original Stick/Flex placement restored within 2.4e-7 m, scientific export unchanged,
default grouped/opaque programs active, pass timing off. Physical inspect preserves
haptics, desktop pointer/click and touch scrolling; controllers were untracked at
the snapshot. The original NADOC browser tab then reattached to the same PID/session:
real visualization and view-tools sequence publications advanced, with exact
presentation/scientific content and geometry payload preserved; Help shows Exit VR
enabled. This verifies the poller beyond mere events-path presence. NADOC is now
foreground; the original desktop-3D-during-VR preference remains true, and the prior
capture does not certify the combined foreground workload. The one-shot restore
binding was removed, all four global VR config hashes match, and SteamVR was not restarted.

Validation: 101 focused backend tests, four readiness cases and five native v2
checks passed; 175 tracking/decoder checks plus 24 subtests passed. The initial broad FAST run retained 14 failures, 8 errors, 10,830
passes, 92 skips and 2,500 warnings. After three Unix-socket fixture failures were
resolved by shorter Archive paths, final FAST reports 10,832 passes, 11 failures,
8 errors, 92 skips and 2,500 warnings; five timing overruns remain. psfgen path and
CPD stereochemistry failures are documented. No broad-green, clean-worktree,
optical-equivalence or subjective-resolution claim.

Evidence: [integration handoff](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/launch-handoff.json),
[recording review](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/index.html),
[calibrated identity proof](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json),
[final configuration/document verification](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/final-config-document-verification.json),
[browser reattachment](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/browser-reconnect/verification.json).
Worn-headset doubling remains MV-44.

Historical intake (retained):
The private optimized diagnostic viewer exited; ordinary browser launch still selected
the original executable and application-eye recorder. The user’s new torso clip
therefore was not a controlled post-fix recording. Integrate the tested native
renderer/tools into the main checkout and bind normal launch to a pinned Archive
build/layer, private inspect socket, recording-only image markers and pose journal.
Save executable provenance in every new recording; never claim full diagnostic
completion after journal failure. Keep active user design/Flex presentation and
existing VR editing/Join behavior. Validation evidence is in
`.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/`.
Worn-headset doubling remains MV-44.

## ISSUE-77 — Menus/hover coincide with renewed VR lag after the dense Stick fix (2026-10-13, OPEN)

The user reports that doubling is substantially reduced, but lag/frame drops
remain as menus enter view or the other controller aims, hovers or vibrates while
moving the model. Request 962531370889719 saves all 179 final presentations with
zero capture drops. Complete CRC/session/eye/frame decoding joins all 358 eye
images: 144 distinct submitted images and 35 two-presentation runs in each eye
(19.55% of presentations reuse the previous image), matching both eyes, with no
unknowns, forward gaps or regressions. A retrospective bounded ROI-follow trial
improves observation coverage; the original fixed-ROI result 313/358 with 22 proven
pairs per eye and 45 unknowns is preserved. Acceptance thresholds were unchanged.

The journal has 143 predicted-in-window application rows; its 144 distinct decoded
images use a different boundary and must not be conflated with that count. All 242
journal rows report head/hand tracking flags 15: no flagged tracking dropout is
shown, which does not exclude pose jitter. Both menus stay logically open, while
original images show changing visible coverage. The longest input/actions stage
is 1.61 ms; xrEndFrame reaches 20.88 ms with mixed 11/22 ms application intervals. This
locates a long host wait, not its GPU/menu/haptic cause. The old journal lacks
per-frame hover and haptic telemetry.

Exact-ID grouping gives median host/xrEndFrame durations of 22.242/20.259 ms
for reused-image frames, versus 11.104/2.347 ms for single-presentation frames.
This is a correlation with application-image reuse, not a causal haptic/menu test.

Native inspection found event-triggered synchronous xrApplyHapticFeedback calls,
not an unconditional vibration loop; vibration duration is not the API call's
blocking duration. Sidebar hover can invalidate cached textures before the
existing total GPU timer starts. Visible menu rendering includes backdrop copies
and frosted-glass sampling. These are candidates to measure, not established
causes, and no rendering or haptic behavior fix was applied.

The normal viewer now records bounded capture-only hover, actual haptic dispatch
results/durations, texture/cache counters, and per-eye menu/backdrop host spans.
The offline summarize-interactions reader retains unavailable old telemetry and
performs optional exact identity joins. Six native checks passed, including actual
GL hover/cache changes and OpenXR dispatch/result spies; 45 reader checks and 69
marker checks passed. A normal closed-menu recording 963838453284914 saved 179
frames and 288 journal rows with diagnostics enabled, zero clock errors/overflow
and zero UI clock calls, as expected. The initial incorrect expectation of positive
UI clocks is retained as a failed verification; no native change or recapture was
needed. This check does not exercise a physical hover or establish a performance fix.

Current deployment: physical-inspect viewer 545874, session 545874-963676394554697,
native SHA256 65bcd41e1de02d1d6271c19a1aa7d04683087358eb0dd78a17d4eb282cb8a4d3;
existing compositor 2783034. The actual browser reattached, scientific export is
unchanged, and placement normalization differs by at most 1.0547e-7. The reload
closed the menus and did not restore their old positions. Reopen/place them and
capture the reported physical menu/hover motion with the new telemetry; compare a
menus-closed condition. MV-44 remains improved but open. No optical-equivalence,
clean-worktree or broad-green claim is made.

Evidence: [native pathway audit](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json),
[complete identity follow trial](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json),
[frozen native build](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json),
[interaction findings](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-timing-findings.json),
[final deployment verification](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/final-verification.json),
[browser attachment](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/browser-connected.png).

## ISSUE-78 — VR Join remains checking after Cancel and reselection (2026-10-13, FIXED)

The physical Join tour selected the donor again after Cancel, received valid
connection feedback, then could not Apply. A duplicate tool-preview event for
the unchanged pose made `loadTarget` publish checking; `queuePose` deduplicated
the already-validated transform and scheduled no replacement result.

The controller now republishes the cached valid result for that exact pose or
schedules validation when none exists. The event-order regression failed before
the fix and passes afterward. The physical steady-fast tour subsequently
completed Cancel, reselection, Apply, one routed scaffold and Undo. Evidence:
`.development-artifacts/vr-join-20261013/reselection-repro.log`,
`reselection-fixed.log`, and `physical-fixed/steady_fast/`.

## ISSUE-79 — Selecting assembly parts writes animations and rebuilds large Full assemblies (2026-10-13, FIXED)

- Repro: open the seven-part native Benchy, select previously unanimated parts,
  and wait. A hidden animation panel seeds a default animation by PATCHing the
  entire part; invalidation starts a full geometry rebuild. Independent sidebar
  caches fetch the same sources repeatedly and the busy overlay obscures the view.
- Fix: passive selection is read-only; share versioned base-source reads; retain
  selection DOM and unaffected renderer meshes; reuse coordinates on representation
  changes; coalesce refreshes and cancel obsolete builds. Batch indexed sweep axis
  evaluation, preserve unrelated backend cache entries, and reuse compact payloads.
- Color changes repaint retained buffers instead of constructing temporary
  molecular geometry; forced part refreshes block stale authoring callbacks.
- Final Full Benchy run: selection 64–449 ms, recoloring 290 ms (previously
  10.39 s), no basic-action or idle rebuilds/busy overlays, 462,002 nucleotides
  retained, 32 rendered fps during idle. Cold load and explicit mesh builds
  remain expensive and are measured separately in the audit.
- Validation is recorded in `docs/audits/benchy_full_performance_20261013.md`.

## ISSUE-80 — Assembly cold loading and Full frame rates remain costly (2026-10-13, PARTIAL)

- **Status:** `[~]` PARTIAL for measured cold-load/GPU limits. Implementation, final frontend, post-fix smoke, hardware measurements and cleanup are complete. This follows ISSUE-79's resolved selection/recoloring defects and does not reopen them. Sub-five-second cold loading and historical 2,000/5,000-instance targets remain unmet.
- **Baseline / scope:** this session's Benchy has seven distinct sources and 462,002 nucleotides; hinge500 is 500 copies of one source. The earlier hardware workflow measured 69.71 s opening and 22.60 s first Full, with different opening boundaries. Do not substitute repeated-instance performance for unique-source cost.
- **Implemented:** bounded native compact production, lossless NDGB/default-JSON cache interchange, versioned renderer readiness and base/display Design separation, hidden library/panel deferral, semantic backend readiness, exact hull-work reuse, prepared CG primitives and lazy indexes. Ordered optimistic CG saves preserve source versions, rollback and accepted API provenance; atomistic/surface confirmation remains. Inactive volumes/warnings, semantic panel/joint reuse and lazy connectors avoid repeated UI work. Autosave is quiet; manual Save retains progress.
- **Final Benchy measurement:** one document/browser/source-cold run, `release_benchy_766e00d2745c`: 34.203 s navigation→paint / **29.669 s import→paint**; first Full **33.0 ms**, Beads 93.8 ms, Cylinders 76.4 ms, restored Full 35.4 ms. All seven close, 462,002 nucleotides, 91,752,688 triangles/35 calls; steady Full **21.075/21.597 FPS**, Cylinders 59.460. Only startup geometry busy; no errors, Design PATCHes or context loss; hashes/cleanup pass.
- **Final hinge500 measurement:** `release_hinge500_4ea9e7c55fdd`: 10.481 s navigation→paint / **6.119 s import→paint**; first Full **485.2 ms**, Beads 1,058.8 ms, Cylinders 689 ms, restored Full 205.8 ms. Unchanged native camera/LOD, all 500 close, 1,517,472,000 triangles/five calls; Full **2.363/1.855 FPS**, Cylinders 59.210. No errors/busy/Design PATCH/context loss; hashes/cleanup pass. One readiness GET remains pending at close.
- **Measurement limitation:** timings start at the trusted option click, exclude menu navigation, and measure renderer submission/next rAF rather than compositor/input-to-photon. The release hinge first-Full screenshot shows Cylinders selectors despite recorded Full store/renderer state; cause not reproduced. The separate `controls_hinge500_a993d498ff87` run checks 500 controls after each Full/Beads/Cylinders/Full phase with zero mismatches and a Full screenshot; its 5.964 s import/233.8 ms Full is diagnostic, not a replacement for the primary run. No unproven cause or repair is claimed.
- **Remaining background cost:** the intermediate post-map/flatten-reuse profile measures cold hinge500 readiness at 39.604 s before final lifetime cleanup (flatten 6.507 s, standard readiness 5.812 s, fingerprint 0.326 s, roughly 27 s projection/canonical remainder). Bounded 20-copy legacy→new is 1.515→1.343 s with exact report/fingerprint equality. Server cancellation is absent; pending requests may continue competing with foreground work.
- **Correctness:** early representation switches wait by source version/membership/mode, retaining dirty and versionless authority; fresh inline/legacy snapshots restart conservatively. Source failures reject later poll/Show waiters until explicit rebuild start, with no automatic geometry retry. Accepted API provenance confirms equal optimistic snapshots through synchronous clones and excludes unmarked delayed snapshots. Independent reviews are clean; exact seven-source transport/hull parity passes.
- **Final validation:** frontend **8,075 passed, one skipped / 697 files / 314.18 s**; post-fix smoke **23 passed / 2.6 minutes**. Backend FAST **10,603 passed, 22 failed, 21 skipped, four collection errors / 191.09 s pytest / 203 s guard**; failure/error IDs exactly match baseline, zero individual timing violators, aggregate 90 s warning remains. FULL is deferred verbatim in the [audit](docs/audits/assembly_loading_performance_20261013.md). Focused batches overlap; final correctness scope has 122 unique cases and readiness scope 131. Ruff passes 23 changed backend/test files; native gate/diff clean, `main.js` net −2. Aggregate lint retains two pre-existing unused imports; memory lint retains four unchanged-file errors/60 warnings.
- **Final preservation:** `final-cleanup-verification.json` confirms identical 205 project-store paths, five document IDs and nine original source hashes, zero test-prefixed artifacts/bridge credentials, and all 109 frozen app/test hashes unchanged with no added/removed scope files. No acceptance work remains pending. Earlier runs remain checkpoints; PARTIAL is retained for the performance limits and unresolved screenshot observation.


## ISSUE-81 — Long pose histories pay missing-attribute lookup costs (2026-10-14, FIXED)

- [x] Reproduced on pushed `bd9248cc`: the 1,000-pose evaluator cases take about 3.6 ms against a 0.64–0.68 ms frozen reference, failing the existing unchanged timing gate.
- Join/Pattern recovery scanned every pose using `getattr(entry, "op_kind", None)`. On Pydantic variants without that field, repeated fallback/exception handling dominated the work. Empty cluster-creation scans also copied an unchanged design.
- Added feature-type discrimination before snapshot-only access and returned the unchanged design when there are no cluster creations. No molecular algorithms, phase constants, history semantics, or timing thresholds changed.
- All 14 evaluator equivalence/timing gates now pass; 1,000-pose cases are about 0.30–0.32 ms. Join, pattern, creation-history and evaluator focused tests pass. Evidence: `docs/audits/feature_history_20261014/evaluation_benchmark_p2_completion.json` and the preserved failing baseline samples. No app/browser claim; backend-only optimization.


## ISSUE-82 — Producer parameter edits retain stale downstream routing (2026-10-14, PARTIAL)

- The old snapshot editor rebuilt only the selected producer and carried later routing rows forward without executing their commands. A bundle length edit could retain a joint log entry while dropping its authored joint state.
- Fully covered recipes now regenerate from inputs, rebuild recovery data, and publish with an expected revision/source identity. Tests in `test_part_recipe_edit.py` cover downstream joints, poisoned payloads, cascade, undo/redo, invalid references, unlogged changes and concurrent edits.
- Unsupported/legacy histories retain recovery compatibility; their general regeneration remains open. This issue is therefore partial, not globally fixed.
- Broad regression caught newly stamped sweep parameters rejected by the strict request schema and versioned rows in rootless documents routed into native proof editing. Both compatibility boundaries were corrected. Native sweep edits also now persist normalized detachment parameters rather than only normalizing during execution.
- A final focused first-helix test exposed unlogged response-time default-cluster creation. The native helix builder now includes deterministic default placement before recording; the empty-root proof regression passes. This does not claim all response-time authoring bypasses are closed.


2026-10-15 — ISSUE-82 continuation: native contracts expanded to 83 kinds with explicit method/action restrictions. Independent deletion now resolves actual failed commands; producer edits reuse one independently proved prefix. Added empty-root lifecycle, generated-scope, hash-seed/thread-isolation and poisoned-payload regressions. Framed paste retained missing frames; refinement selection was made independent of live session state; older cluster membership setters no longer erase later extrusion membership during recovery. Compound branch generation and unbounded CPD conversion remain unverified, and existing history UI limits are published by capabilities. ISSUE-82 remains PARTIAL; no blanket legacy/agent-enforcement claim.

## ISSUE-83 — Interrupted prepared-model publication can leave a partial commit (2026-10-15, FIXED)

- Audit found that `state.set_design` appended undo, cleared redo and replaced
  the design before publishing its revision, without rollback around that tail.
  An injected exception or cancellation after the swap reproduced the risk;
  this was not an observed user-data incident.
- The extracted replacement transaction preserves the exact source reference,
  full bounded undo/redo stacks, revision and request markers on `BaseException`.
  It retains the existing single undo snapshot and does not change callbacks,
  molecular builders or validation policy.
- Eight state transaction tests and fifteen repair job tests pass, including
  full-stack eviction, empty source, failed snapshot, stale admission, partial
  revision publication, cancellation, and retry of the same evaluated candidate.
  The first test run exposed a fixture teardown still using the injected hook;
  isolated owned-session cleanup corrected that fixture, without a product change.

## ISSUE-84 — Maximum-size saved repair proposals could fail their own roundtrip (2026-10-15, FIXED)

- The retained-draft coating benchmark found that a sparse proposal near its
  byte limit was accepted, but serialization added optional action defaults.
  Undo's dump/validate copy then rejected that larger canonical envelope. No
  user design was involved; prepared publication failed before changing state.
- Four boundary regressions cover node/byte limits for both repair action
  variants. Before the fix, three failed at save/reload and one passed.
  `RepairDraft` now validates its canonical serialized form as well as bounding
  raw input before construction. Limits and undo validation are unchanged.
- All 35 schema, 18 draft API and 16 persistence cases pass after the fix.
  The benchmark's aborted attempt is retained in
  `docs/audits/feature_history_20261014/coating_jobs_draft_boundary_failure_p4.json`;
  performance qualification is reported separately from this correctness fix.

## ISSUE-85 — Evaluated candidates could outlive their document session (2026-10-15, FIXED)

- Source identity and revision alone did not distinguish a dropped document
  session from a recreated session containing that same object/revision. This
  was an audit finding, not an observed user-data incident.
- Evaluation capture now retains a host-only session identity under the same
  lock. Supervision, polling, commit and already-committed handle reuse check
  that identity. Saved files, worker output and request fields cannot supply it.
  Guarded capture/publication refuses a closed session without recreating it.
- All 21 session regressions pass, including close/reopen before admission,
  during worker execution and during candidate decode; missing context; locked
  nonblocking probes; and idempotent commits within the original session.
  Existing verification and default three-value capture remain compatible.

## ISSUE-86 — Browser number serialization rejects unchanged repair expectations (2026-10-15, FIXED)

- Input metadata can contain an exact authored float such as `12.0`, but browser
  `JSON.stringify` returns `12`. The repair planner deliberately distinguishes
  these JSON representations, so the unchanged field incorrectly reports
  `repair_conflict`. Python-only HTTP fixtures had preserved the decimal text.
- The real Node/browser action builder followed by HTTP draft submission
  reproduced both diameter and pose failures: **two failed in 2.71 seconds**,
  each with HTTP 409 at the selected field. This was a development audit finding,
  not an observed user-data incident.
- Input metadata now supplies bounded canonical `expected_old_json` text. The
  browser carries it unchanged; action parsing checks its displayed value,
  restores the exact old representation, and retains the encoding in the draft.
  Duplicate keys, nonfinite numbers, excess depth and aggregate envelope excess
  are rejected. Boolean/number equivalence is never permitted. Strict planning
  expectations, output identities, versions and final regeneration are unchanged.
- Regression coverage includes actual browser/HTTP roundtrips, portable reload,
  rebase, native repair evaluation and rejection without publication. All 43
  codec and eight actual transport cases pass, together with 229 related
  metadata/planning/draft/persistence/source/repair regressions (280 total).
  Invalid-parameter contract recognition remains separate work.

## ISSUE-87 — Repair Apply mistakes a commit receipt for a full design (2026-10-15, FIXED)

- Integration audit found that the actual evaluation commit endpoint publishes
  one revision and returns only job/design/revision metadata. The new desktop
  repair controller passed that receipt into a response adapter requiring a
  complete Design. Its unit mocks returned a full model and concealed the gap.
- The visible consequence would be a successful server commit followed by an
  error and stale displayed geometry. A second Apply or cancellation must not
  be presented as though the model had never been published.
- The correction retains the committed receipt, privately fetches design and
  geometry from the original document, checks exact revision/design identity
  and the original job's session status, then synchronizes once. A failed read
  leaves an explicit refresh action; it does not recommit or cancel publication.
  This uses the compatibility host's existing revisioned mutation contract and
  is separate from future immutable strict storage and candidate previews.
- The first full frontend run also caught six failures in the new metadata
  summary adapter: two absent identities compared equal through optional
  chaining, then dereferenced a null prior summary. The fix must tolerate
  identity-less legacy response fixtures without changing those fixtures.
  Initial full result: 8,155 passed, one skipped, six failed in 308.92 seconds.
  Eight targeted commit/refresh regressions then failed before implementation
  (789 ms); final corrected validation is recorded below.

- Lost/failed commit transport now retains a separate original job identity and
  unknown-publication notice. Explicit status inspection can confirm publication;
  there is no automatic recommit or cancellation of a possibly published result.
- Root review also found the default-document sentinel mismatch: browser null
  differs from server `__default__`. Three of ten refresh tests failed before the
  exact mapping fix (779 ms); absent/null server identities are now rejected.
- Final focused desktop validation: 86 passed across 12 files (4.92 seconds).
  Full `just test-frontend`: **8,181 passed, one skipped, 708 files** in309.16
  seconds. App/smoke remains unrun because Archive is unavailable (MV-45); this
  is tested integration code, not a claim of visual/headset qualification.

## ISSUE-88 — Session cache aliases unsafe document identities (2026-10-15, FIXED)

- Static audit found that `_doc_dir` replaces non-filename characters and
  truncates document IDs to 80 characters. Distinct live identities therefore
  share a cache directory: `a/b`, `a?b` and `a_b`, or any IDs with the same first
  80 characters. Exact `.` and `..` instead address the cache root and its
  parent. This is a development finding, not observed user data loss.
- Regression dossier: `tests/test_session_cache_identity.py` checks refusal
  before state capture or file access, collision and dot-entry deletion against
  pytest-owned sentinel files, unchanged supported paths, and strict creation
  refusing unsafe identities before it creates a session. No workspace files,
  cache lifespan or background threads participate. Parent ran the baseline
  after checkpoint `7d02a5f2`: **29 failed, nine passed in 2.99 seconds**. The
  nine existing-safe-path cases passed; all unsafe-admission cases failed.
- Reviewed correction: require exact nonempty `[A-Za-z0-9_.-]` identities of at
  most 80 characters, excluding `.` and `..`; reject rather than sanitize or
  truncate. A shared pure validator will gate cache paths and new strict HTTP
  contexts. Unsafe autosave must report an explicit unsupported identity and
  allow other valid documents to flush. No existing cache files are renamed,
  migrated or deleted by this correction.
- Current UUID/default identities, browser `shared-arm`, and headless
  `__headless_build_*__`, `__headless_oxdna_*__` and `__headless_assembly_*__`
  all remain exact supported paths. Existing pruning tests do not depend on
  sanitizer behavior. Root cause: a lossy filename sanitizer was used as the
  persistence identity boundary while live sessions retain the original ID.
  Typed immutable-cache namespaces and restore qualification remain separate
  later work.
- The narrow correction passes 122 parent-run regressions: 50 identity, six
  cache pruning, 61 strict HTTP and five scalar revision cases. Cache
  writes now reject before capture, flushes report bounded unsupported-identity
  warnings and continue supported documents, and strict HTTP rejects unsafe
  resolved identities before reading the body. Added canonical-type/whitespace
  and no-body-acquisition cases; no tests were executed by the implementation
  agent. Existing restore and pruning policies are unchanged.

## ISSUE-89 — Inert generator annotations pass admission but fail strict native replay (2026-10-15, FIXED)

- The shared dependency resolver deliberately removes `_generator` annotation
  metadata, and scoped execution does the same. Ordinary `execute`/`execute_long`
  instead pass the annotation into strict native schemas. A valid annotated gold
  row is admitted but cannot regenerate; invalid-input repair exposed this older
  inconsistency. This is a development audit finding, not an observed data-loss
  incident. Metadata must not supply command parameters or output identities.
- The isolated regression dossier `tests/test_part_generator_annotations.py`
  uses valid gold create/patch rows with poisoned recovery, direct and spawned
  independent proof, both executor modes, scoped controls and forged/missing
  native identities/versions. It verifies that recorded annotations are retained
  verbatim and excluded before reference validation/building. Against reversible
  checkpoint `08af575e`, the root-run red target produced **five failed and 11
  passed in 3.68 seconds**, including failed proof in a real fresh worker. Scope
  and forged/missing-authority controls already passed.
- Reviewed correction: after the existing scoped handoff, remove only the inert
  `_generator` key from a private execution-parameter dictionary. Keep original
  recorded parameters, native schemas, `_generated_scope` validation, versions,
  output IDs and actual typed reference resolution unchanged. Do not normalize
  other unknown fields or infer missing inputs from metadata.
- That shared execution filter is now implemented. Unannotated commands avoid
  an extra parameter copy; annotated rows keep their original recorded JSON.
  Parent-run corrective and related regression validation passed 393 cases,
  including all 16 annotation regressions and the 48 invalid-gold repair cases.
  Fresh-worker proof, saved-draft evaluation, source restoration and generated
  scope guards remain covered; no molecular model or version changed.

## ISSUE-90 — Pending NP candidate deletion clears unrelated direct-binding metadata (2026-10-15, API FIXED; LATENCY UNQUALIFIED)

- The existing pending connection delete route called `_sync_np_applied_bindings`
  for the entire design after deleting one unapplied candidate. That helper
  reconstructed surface bindings solely from applied candidate versions, so an
  unrelated legacy direct-bound handle lost its `bound_overhang_id`.
- `tests/test_part_pending_np_connections.py` reproduces the defect with two
  native-created gold/thiol owners, an explicitly retained legacy direct binding
  on the other particle, and two pending candidates. Delete must remove only the
  chosen candidate and preserve the other owner's exact metadata. The parent
  recorded the tests-only red dossier: 31 failed, 18 passed in 3.29 seconds;
  unknown new contracts dominate, while this actual route failure is preexisting.
- The correction bypasses global synchronization for unapplied deletion in both
  the strict pending native builder and compatibility route. Applied workflows
  remain separate and retain existing behavior. This does not certify old direct
  bindings or reconstruct their missing historical inputs.
- Native pending create/rename/delete now retain all exact owner/reference inputs,
  output identity/time and the version discriminator. Lock-owned recording and
  rollback regressions are included. The parent's final target passed 66 cases
  in 4.20 seconds; editing regressions passed 95 in 3.58 seconds, including the
  separately checked seven identity-policy cases: 161 distinct green cases.
  Thirty-repeat measurement passed all ten cases and five native cold proofs.
  Latency remains unqualified: maximum native request/lock/lightweight request
  were 88.57/82.35/86.30 ms; larger native medians were about 24 ms versus 17 ms
  compatibility. The initial larger cold-capture refusal is retained. See
  `validation_pending_np_connections_p4.json`. No app check is claimed; applied
  connections and pending-candidate movement remain separate increments.

## ISSUE-91 — Missing physical-input evidence is indistinguishable from a match in job APIs (2026-10-15, API/SHARED UI FIXED; FULL RECEIPTS/APP OPEN)

- Legacy `out_of_date: false` includes equal, missing and incomparable hashes;
  the shared v4 projection also omits consumed cluster/nucleotide transforms and
  ordinary proteins. Equality cannot establish complete physical freshness.
- Additive `input_freshness` reports stale for a known partial-model difference,
  otherwise unknown with explicit reasons and nullable `model_match`. List/detail
  handlers reuse existing fingerprints once; no additional traversal, hashing,
  disk walk, job rewrite or scientific work. Existing booleans/guards stay compatible.
- The first 29-case target failed before implementation; all 29 now pass, plus
  18 oxDNA and 12 MD regressions. One old MD fixture failed independently with
  unchanged `7886cd42` route/fingerprint modules: its alleged pre-recipe file
  retained a native recipe root. Corrected the fixture and added the complementary
  no-unlogged-topology assertion; production restoration is unchanged.
- API and shared frontend unknown/stale labels are fixed in `764b413b` and
  `6abb5dde`. Frontend validation passed 39 focused cases and the full 8,192
  cases with one skipped. These are automated results, not an app-validation claim.
- Complete engine-specific input/solver/source/restart receipts and
  result-selection qualification remain open under the physical freshness plan;
  MV-46 app validation is also open. No historical simulation receives a current
  certificate.

## ISSUE-92 — Applied NP connection lifecycle leaves stale ownership and constraint metadata (2026-10-15, FOCUSED CORRECTION VALIDATED; APP OPEN)

- Static audit found that `_set_np_version_applied` clears applied/relaxed/
  residual/duplex state on unapply or conflict replacement, but retains
  `constraint_root_nm` and `constraint_radius_nm`. The strict pending contract
  correctly rejects that retained active state, so apply→unapply cannot return
  to native pending-handle motion without a lifecycle correction.
- The same helper calls `_sync_np_applied_bindings` over the whole design. Like
  ISSUE-90's earlier pending delete, this can clear unrelated legacy direct
  bindings absent from the candidate-version table. Applied deletion invokes
  this global synchronization again. Only explicitly affected handles may be
  synchronized; unrelated compatibility metadata must remain untouched.
- Relocation updates the driven strand/domain and auxiliary overhang carrier,
  but leaves the NP surface record's `helix_id` at its removed original helix.
  Refreshing that metadata alone would make `compatible_particle_handle`
  consider a bound handle free; it needs an explicit bound-owner exclusion.
  Native placement, register, inverse-pose and restoration formulas remain
  unchanged. Existing typed saved topology retains the original helix.
- `tests/test_np_applied_lifecycle_ownership.py` is the eight-case tests-first
  dossier: actual apply/unapply constraints, subsequent native motion, unrelated
  binding preservation through apply/unapply/delete, current carrier and saved
  roundtrip, explicit planner exclusion, and displaced-version cleanup. Root
  recorded **eight failed in 2.85 seconds**: two stale-constraint/motion cases,
  three unrelated-binding cases, and one each for carrier, planner and conflict
  cleanup. The existing
  native fixture supplies both owned handles and the ordinary target. No test
  or simulation was run by the implementation agent.
- The narrow correction passed all eight new cases plus related regressions:
  180 passed and one older HTTP-status assertion failed in 29.18 seconds. The
  failing pending-create path was identical to the earlier `a24b60b7` checkpoint;
  it already returns typed 422 invalid_selection with an exact auxiliary target
  reference. Updating that stale 400 assertion to the complete structured
  diagnostic passed in the following focused run (181 distinct green total).
  Only the
  selected handle and actually displaced applied/retained handles synchronize;
  untouched conjugations/records remain unchanged. Unique consistent live
  strand/domain/auxiliary ownership refreshes the surface carrier; ambiguous
  legacy ownership is left visible rather than guessed. Unapply/conflict reset
  clears the inactive constraint root/radius, deletion avoids a second global
  sync, and the generator explicitly excludes bound handles. No geometry
  formula, numerical pin, solver or replay schema changed.
- The parent authorized these local metadata corrections as part of P4 native
  applied lifecycle work. The new replay contract, explicit output IDs, exact
  conflict/restore selectors, bounded admission and cold proof still need their
  own reviewed tests before broader implementation. Assemblies and collective
  relaxation remain outside this checkpoint.

## ISSUE-93 — Private DNA comparison disposal can mutate shared renderer metadata (2026-10-15, FOCUSED FIX VALIDATED; APP OPEN)

- The unshipped private DNA adapter identifies alpha-enabled private geometry
  clones before disposal. Three's `BufferGeometry.copy` shares the `userData`
  object by reference, so clearing `shared` in place also changed the native
  template marker and allowed a later disposal to release that template.
- The first focused run caught a real shared-template disposal failure (alongside
  five obsolete source-text assertions after extraction of the native connection
  constructor): 193 passed and six failed in 3.79 seconds.
- The correction detaches metadata on the proven private alpha clone before
  clearing its private marker. Tests retain the normal scene's matrices, geometry
  identity and shared metadata through private construction/disposal. The five
  constructor-text checks were replaced by behavior checks of exact buffer
  sizes, all RGBA channels, transparency and native quadratic samples.
- Corrected focused run: 195 passed across 11 files in 3.97 seconds. Actual native
  Python packets also pass the Node renderer oracle (14 matrix-parity packets
  and two explicit refusals for metadata-only ligations). Full frontend subsequently passed 8,291 cases (one skipped) across 717 files in
  314.43 seconds. Live app/resource qualification remains separate; no geometry
  formula changed.

## ISSUE-94 — Cold strict DNA decode depends on prior Helix construction (2026-10-15, FOCUSED CORRECTION VALIDATED; MEASUREMENT OPEN)

- The first real strict-byte benchmark completed six gold publications and two
  independent proofs, but mixed DNA and the 50,000-residue source both refused
  before evaluation with `MockValSer` / `SchemaSerializer`. The source remained
  unchanged and the worker/session cleanup passed. Failed measurements remain
  in `benchmark_immutable_part_jobs_bytes_initial.json`.
- A minimal fresh process independently reproduced the failure: validating
  nested Helix data through Design builds the outer schema without completing
  Helix's own serializer, whose LoopSkip type is declared later. Exact
  `serialize_as_any=True` serialization then fails. Direct Helix construction
  in ordinary fixture setup had hidden this initialization dependency.
- Initialize the existing Helix schema once when the strict immutable boundary
  is imported. No schema/geometry field, molecular formula or pinned model file
  changes; exact serialized roundtrip and admission remain mandatory. Add an
  independent subprocess with nested loop/skip data and a real spawned native
  DNA worker regression. Focused validation passed 115 distinct cases after
  correcting one new assertion to compare the complete independent proof report.
  Controlled cancellation during owned decode also reaps within two seconds
  and releases both buffers. Corrected actual HTTP measurement remains pending.

## ISSUE-95 — Copying an oxDNA job drops its packaged sequence parameters (2026-10-15, FOCUSED FIX VALIDATED)

- Preparation freezes `oxDNA2_average_sequence_parameters.txt` in the job package;
  the runner selects that exact file when rendering stage inputs. Copy Job omitted
  it, so a copied job could fall back to the currently installed parameters.
  The copy therefore did not preserve all consumed physical inputs.
- The copy file set now includes the existing shared protocol filename. Existing
  bytes are copied exactly and independently; legacy absence is retained without
  inventing historical evidence. Fresh seeds, protocol overrides, topology, forces,
  lineage and queued state retain their established behavior.
- Tests first: the added present-file case failed with FileNotFoundError; the
  absent-file control passed (3.66 s). Both cases and 42 related physics/freshness
  tests then passed in a combined 4.95 s run; seven unrelated new pending-connection
  early-refusal cases intentionally remained red. No production simulation ran.
- This repairs package propagation only. It does not certify source isolation,
  complete physical receipts or per-attempt solver/restart provenance.

## ISSUE-96 — Three-anchor platform generator rejects its second fitted connection (2026-10-15, BASELINE REPRODUCED; OPEN)

- The focused existing generator regression
  `test_multiple_connections_close_without_moving_centers[platform-HONEYCOMB-3]`
  fails at connection 2/3 for nanoparticle 1 with a fitted-duplex collision. The
  other 289 cases in that run pass, including all 50 initial native application
  contract cases. The two later admission regressions also pass after correction.
- Exact seven pre-extraction nanoparticle route helpers from `acad1d51`, executed
  in a private namespace with the same current generator/native algorithms,
  reproduce the same failure (18.64 s). Evidence:
  `docs/audits/feature_history_20261014/np_application_generator_baseline.json`.
  This isolates the helper extraction; it is not a whole historical binary run.
- Keep this as generated-asset coverage/placement debt. No collision threshold,
  molecular placement, optimizer, test expectation or numerical pin was changed.
  Diagnose the actual collision before any proposed scientific correction.

## ISSUE-97 — Sequence application truncates a shared overhang host (2026-10-15, REPRODUCED; OPEN)

- Two native 12-base overhangs can reuse the same 42-base helix, with reverse
  domains 41→30 and 11→0. The existing connection-version Apply path normalizes
  each sequence to its live domain length, then `_build_overhang_patch` resizes
  the entire host to that sequence length. After the first patch, its range is
  30–41; the other domain remains 11→0 and loses its canonical linker anchor.
- Reproduced from the pending-connection test's authentic bundle/extrusion
  recipe without changing generated coordinates. Both ssDNA and dsDNA legacy
  Apply controls fail with `NativePlacementError` before a new adapter exists.
- Initial registered finite-linker application requires a unique dedicated host
  and a backing domain spanning that host. Shared/partial hosts must refuse
  explicitly before sequence or topology work. Existing native kernels remain
  unchanged; correcting the general shared-host sequence operation is open.

## ISSUE-98 — Cold coating tests author numerical pins in the wrong process (2026-10-15, FOCUSED TEST FIX VALIDATED)

- The two lifecycle modes passed alone but failed after the API/MDAnalysis group
  with `runtime_mismatch`. A minimal inspection established that importing
  MDAnalysis adds a GNU OpenMP library to the parent fingerprint; NumPy/SciPy
  fingerprints otherwise remain identical. Limiting threads does not remove
  this loaded library. The fresh evaluation worker correctly refuses that pin.
- The cold lifecycle test now authors both packing/repacking and their pins in
  the actual isolated append worker, then performs independent cold replay with
  poisoned recovery. A parent runtime probe fails the test. Rigid move/remove
  and retained-input/identity assertions remain; no pin, source algorithm or
  production runtime policy was changed or weakened.
- The formerly failing ten-module order passed **258 tests** (95 existing
  warnings) in 29.43 s. Both lifecycle modes now perform five real workers and
  are classified as intentional slow `namd` integration tests (7.10/7.22 s).
- Primary-source context: threadpoolctl documents that its inventory describes
  libraries loaded into the current process and expands with additional imports:
  [runtime introspection](https://github.com/joblib/threadpoolctl#python-runtime-programmatic-introspection).

## ISSUE-99 — Ordinary grouping can omit its construction inputs (2026-10-15, FOCUSED FIX VALIDATED; APP OPEN)

- The cluster panel and selection menu omit `log`; the ordinary route and
  headless wrapper defaulted it to false. Group membership changed and was
  persisted without a `cluster_create` record, so subsequent moves could depend
  on a group that native history never created.
- New `backend/api/part_group_recording.py` shares the pure `cluster_create`
  builder and always publishes a versioned grouping entry. `log` remains an
  accepted, ignored compatibility argument: omitted, false and true all record
  exactly one group. No recipe root or missing historical construction is
  inferred for legacy documents.
- Source selection, allocation, building, validation and publication use one
  existing non-reentrant state lock. The helper calls the lock-owned replacement
  publisher rather than nesting `state.set_design`; failures and cancellation
  preserve source, undo/redo and revision. Grouping directly owns membership,
  so it adds neither topology reconciliation nor full history proof to the edit.
- Creation at a historical cursor now refuses with explicit HTTP 409
  `historical_cursor` before allocation/building. The user must return to latest;
  the old partial timeline truncation is not retained as an implicit branching
  policy. A grouping entry between two nicks preserves their chronological
  routing boundaries and independently replays.
- The first green focused run passed **101 cases, 108 warnings, 5.57 s**. After one
  additional routing-boundary regression, the group file passed **16 cases,
  16 warnings, 2.88 s**. These overlapping runs establish **102 unique checks**,
  not 117. Ten checks cover deformation lifecycle controls/characterizations;
  they do not mark ISSUE-100 fixed. Two obsolete unlogged-group tests were
  updated while retaining the missing-provenance negative control.
- **Not verified in app, broad suite or performance measurements.** MV-48 owns
  desktop validation. `frontend/src/main.js` delta **0**; no scientific formula,
  numerical pin, capture budget or private rollout gate changed. G1 remains open.

### ISSUE-99 continuation — ordinary group PATCH (2026-10-16, IMPLEMENTED; APP OPEN)

- Sidebar name/style and selection-menu membership omitted `commit`, so the old
  route silently changed authored state without a feature row. Explicit commits
  also read outside ownership and validated after publication. New red tests
  reproduced these paths, missing/ambiguous references and rollback failures.
- Ordinary authored fields now force one recorded transaction and undo. Pure
  pose previews retain their old lifecycle; direct pose confirm shares the owned
  publisher. Typed/bounded selectors and exact emitted-input admission precede
  publication. Membership dependencies include helices/owning strands and a
  conservative topology barrier; no full proof runs during ordinary edits.
- The client persists/broadcasts these operations and consumes embedded matching
  geometry for membership/mixed-pose edits. Pure style and gizmo pose commits
  remain lean. Legacy group inference is excluded from owned responses; it must
  not silently rewrite a just-recorded candidate.
- Existing tests that intentionally expected cosmetic edits outside history
  were replaced with undoable/replayable style checks. Saved v1/v2 builder
  semantics and numerical pins remain unchanged. See
  [checkpoint evidence](docs/audits/feature_history_20261014/validation_group_edit_recording.json).
- FH-18 remains open for logged deletion, placement-preserving regrouping and
  auxiliary group lifecycle. MV-48 remains open; no app/performance claim.

### ISSUE-99 continuation — recorded group dissolution (2026-10-16, ADMITTED SUBSET IMPLEMENTED; APP OPEN)

- The old DELETE filtered a live group without recording its inputs. Imported
  group omission looped through those deletes and ignored failures before Save;
  timeline creation/pattern/Join restoration could resurrect removed groups.
- `cluster-dissolve` v1 now records an atomic selected-ID batch under the shared
  group transaction. Single DELETE and batch POST share bounded typed incoming
  reference and native placement admission. One undo/revision, input-only replay,
  producer-edit/cascade and exact new-row recovery payload preservation are tested.
  The old unlogged-delete implementation and sequential import-removal loops were
  removed; their tests now assert recorded behavior and failure preservation.
- Only identity/zero-pivot nonempty groups and eligible empty identity groups
  are admitted. Posed, repivoted, child/duplex-owned or deformation/pose-overlapping
  groups refuse rather than move their members. This is an explicit supported
  subset, not completion of the original placement-preservation milestone.
- Recovery merges selected presence/order from already decoded snapshots and
  filters chronological removals after all existing restorers. Later explicit
  recreation clears a prior removal; histories without this new command retain
  their existing creation-restoration path and avoid new inventory limits.
  Rootless response normalization also respects authored removal histories; a
  later read cannot silently bootstrap their removed groups or refill membership.
- Moves, Join and pattern baselines now respect explicit recreation lifetimes;
  imported initial groups and original pattern poses survive backward seek.
  Missing/evicted dissolution bodies refuse timeline seek with typed 410 before
  publication; malformed/over-budget metadata refuse with 409. All dissolution
  PRE/POST bodies are required by this conservative reader, including end seek;
  native input regeneration remains independent. Ordinary histories retain
  their prior recovery behavior.
  A pattern that implicitly reuses a removed ID without explicit creation is
  refused rather than silently losing its new wrapper during recovery.
- Sidebar **Dissolve** preserves hidden state on refusal/stale responses. Import
  omission is one all-or-none request and stops Save on error/cancellation or a
  superseded result. See [evidence](docs/audits/feature_history_20261014/validation_group_dissolve.json).
  FH-18 remains open for posed/regrouped and auxiliary lifecycle; actual desktop,
  serialization/undo/geometry cost and interaction latency remain MV-48/FH-27.

### ISSUE-99 continuation — auxiliary grouping recording (2026-10-16, IMPLEMENTED; APP OPEN)

- Unassigned-component grouping previously authored incomplete unversioned rows
  and could publish over newer state. It now emits complete native v2 inputs,
  computes privately with reference/graph bounds, and publishes once after an
  exact source/session/revision/policy check. No-op keeps state and undo intact.
- Duplex pivot selection previously changed pose without a feature input. It
  now records the native absolute pose rebase as v1, preserving original recovery,
  physical and presentation data. Geometry work is preflighted and stays outside
  the state lock; unchanged native helpers remain the oracle.
- Frontend pivot failures and stale replies preserve pending moves and selection.
  Later rootless reads respect recognized authored group intent, so empty
  membership is not silently refilled. Unversioned legacy inference is unchanged.
- Removed duplicate unowned route publication/truncation code; shared preparation
  and the existing failure-atomic publisher own both paths. See
  [U5 evidence](docs/audits/feature_history_20261014/validation_group_auxiliary_recording.json).
  FH-18 remains open and has reached three checkpoints: task growth is explicitly
  flagged, with a finite [migration plan](docs/audits/feature_history_20261014/group_placement_migration_plan.md).
  Count remains 18/38, no changed exit/denominator. MV-48/FH-27 retain desktop and
  measured latency acceptance.

## ISSUE-100 — Bend/twist history preview replaces canonical state before Apply (2026-10-15, REPRODUCED; OPEN)

- `tests/test_geometry_history_preview_lifecycle.py` mirrors the current desktop
  sequence on a tiny native part: delete the committed deformation with preview
  mode, add/update a temporary preview, then discard it before history Apply.
  The feature log still names the original operation, but the canonical design
  no longer contains it. Apply correctly refuses with HTTP 409
  `recipe_not_reproducible`, leaving that already-altered source in place.
- Cancel's timeline seek restores the committed overlay but adds an undo entry
  and clears redo. The added undo point contains the peeled, unreproducible
  state. These are reproduced integration defects, not desired semantics.
- All **10 bend/twist cases** pass as a mixture of bug characterization, direct
  native-edit/undo controls, failure atomicity and a guard against full proof on
  preview drag. Their green result does **not** certify preview correctness.
- Root cause: the legacy preview workflow uses canonical silent setters as its
  working state; the newer history editor correctly requires a reproducible
  source. Next implement a bounded, source-bound private preview whose Cancel
  only discards temporary state and whose Apply commits native inputs once.
  Preserve current geometry calculations and keep full replay off drag paths.
  See the [proposed G1 preview lifecycle](docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md).
- No preview implementation fix, app check or performance qualification is
  claimed in the grouping checkpoint. MV-48 retains desktop lifecycle debt.
- Subsequent G1 work implements the private bounded prefix/local evaluator with
  34 passing cases and 46 native controls. No live host lifecycle, render DTO or
  frontend integration is enabled, so this issue remains open. Follow the
  [continuation evidence](docs/audits/feature_history_20261014/validation_geometry_integrity_continuation.json).

- October 16 private continuation adds source/session/revision/policy-bound host
  leases, guarded Apply and a complete bounded native preview DTO. All 27 host
  and 27 DTO cases pass with related controls. There is still no public route
  or editor wiring, broader core-prefix/control parity or app/latency evidence;
  ISSUE-100 remains open.

## ISSUE-101 — Forced ligation can replace an intervening authored edit (2026-10-15, FOCUSED FIX VALIDATED; APP OPEN)

- The ordinary route selected strands and built `_ligate` output before taking
  the recording lock, then returned that prebuilt design while ignoring the
  recorder's current source. A deterministic intervening nick was discarded.
  Protected-loadout refusal also occurred after native building had already run.
- `part_routing_recording.record_forced_ligation` now owns selection, actual
  endpoint labels, affected-helix scope, extension fallback and one `_fl_id`
  allocation under the existing state lock. It invokes the shared pure ligation
  builder through lock-owned `record_minor`, with a session/source/revision
  guard. No nested lock, extra snapshot or replacement publisher is introduced;
  the recorder retains one snapshot, reconciliation and pending-ligation retry.
- Tests first: **3 failed / 11 passed, 14 warnings, 3.26 s**, exposing unlocked
  building, the lost interleaved nick and protected-loadout work. All **107
  forced-ligation-related cases, including the 14 new cases,** are now green. The
  combined 141-case run had 139 passes and two unrelated preview-fixture failures
  (86 warnings, 5.23 s); correcting those fixtures yielded two further passes.
  These are overlapping runs, not an additional 14 beyond the 107.
- Coverage preserves exact errors, extension full-response fallback, periodic
  seams, native authoring parity, one undo/revision, input-only replay with
  poisoned recovery, interleaved work, protected refusal and rollback of values,
  stacks and request markers. Rollback keeps the existing detached-snapshot
  semantics; it does not promise original source-object identity after failure.
- Scientific formulas and valid geometry are unchanged. Batch-nick suppression,
  resize terminal-reference admission and prebuilt auto-crossover publication
  remain separate follow-ups; this fix does not close G1. **No app, broad-suite
  or performance qualification**; MV-48 remains open and `main.js` delta is **0**.
  See [continuation evidence](docs/audits/feature_history_20261014/validation_geometry_integrity_continuation.json).

## ISSUE-102 — Live Fine Routing silently accepts invalid batch selections (2026-10-16, FOCUSED FIX VALIDATED; APP OPEN)

- Batch nick reused the tolerant legacy builder, silently skipping missing,
  terminal, repeated or otherwise inapplicable targets. Resize did not apply the
  native history terminal-reference guard; a wrong helix or empty-domain target
  could become an apparently successful recorded operation. Nick response scope
  was also collected before acquiring the recording lock.
- `part_routing_recording` now uses the existing strict sequential nick builder
  and resize reference admission with one lock-owned `record_minor` transaction.
  Missing references return typed 404 diagnostics; inapplicable selections return
  typed 422 diagnostics with parameter paths. A failed later selection preserves
  design values, history/redo, revision and request markers. Valid native building,
  one snapshot/reconcile/retry, partial geometry and empty-batch behavior remain.
- Red: **10 failed / 19 passed, 29 warnings, 3.80 s**. Green: **174 passed,
  101 warnings, 7.09 s** across eight related files, including 31 adapter cases.
  Coverage includes poisoned-recovery replay, undo/redo, multi-helix splits,
  deterministic interleaving and absence of full-history proof in these edits.
- The old tolerant builder remains for legacy compatibility and its direct
  regression is named accordingly. No molecular formulas or source pins changed.
  **Not verified in app or broad/performance testing**; MV-48 remains open.
  `main.js` delta is zero. Auto-crossover and live preview integration remain
  separate work; these focused fixes do not close G1.

## ISSUE-103 — Automatic crossover publication can discard newer edits (2026-10-16, FOCUSED FIX VALIDATED; APP OPEN)

- The native fixed-point builder received the live mutable source before the
  recorder acquired its lock. Its prebuilt result could replace an intervening
  nick; protected-loadout checks ran after native work. A failing builder could
  also leave mutations through the live alias.
- The ordinary adapter now captures one detached full source under the state
  lock, builds outside it, and checks document/session identity, source object,
  revision and construction-policy generation before `record_feature`. Changed
  inputs return 409 without overwriting newer work. Strict/protected refusals
  precede capture and calculation. Native fixed-point logic, seed, statistics,
  labels, full response and one recording snapshot/reconcile/retry are preserved.
- Red: **4 failed / 6 passed, 10 warnings, 3.41 s**. Green related run:
  **117 passed / 1 skipped, 65 warnings, 10.43 s**, including 12 new cases;
  72 of those passes overlap the earlier nick/resize run. The retained skip is
  an existing native-router conditional, not a new disabled regression.
- The extra full source copy is a real additional cost; larger-design lock and
  request latency are not qualified. The expensive native calculation remains
  outside the state lock. No scientific algorithm or numerical pin changed.
  App testing remains MV-48; `main.js` delta is zero.

## ISSUE-104 — Typed error explanations appear as raw JSON (2026-10-16, AUTOMATED FIX VALIDATED; APP OPEN)

- `errorDetailToMessage` understood a direct `msg`, but new native reference
  diagnostics use `detail` and other refusals use `message`. The browser therefore
  displayed serialized codes/reference metadata instead of the explanation.
- Two direct string checks now prefer `msg`, then `detail`, then `message`.
  Existing strings, validation arrays, empty/non-string fields, circular values
  and unknown-object diagnostics keep their established behavior; there is no
  recursive reinterpretation or new truncation rule.
- Tests-first red: **6 failed / 16 passed, 1.65 s**. Full frontend passed
  **8,300 cases / 1 skipped across 717 files in 345.21 s**, including all 22
  error-detail cases; see the [checkpoint evidence](docs/audits/feature_history_20261014/validation_core_geometry_lifecycle.json).
  App error-display checks remain MV-48; `main.js` delta is zero.

## ISSUE-105 — Historical bend/twist group changes retain old affected helices (2026-10-16, BACKEND CORRECTED; DESKTOP OPEN)

- The ordinary popup offers group selection, but the historical commit sends
  the saved context's cluster IDs. Even with new IDs passed directly,
  `part_overlay_commands.edit_entry` retains `affected_helix_ids` from the
  original operation. Native deformation evaluation and membership filtering
  still use that list, so changing group metadata does not reliably retarget
  the operation. This is a selector/recording gap, not a molecular formula gap.
- Authored group changes now resolve through existing plane/scope selectors
  against the owned prefix and record explicit affected IDs. Unchanged group
  membership, including reordering, retains historical custom affected IDs.
  Saved v1 replay is unchanged. Missing, duplicate and empty-intersection groups
  refuse; native `[]` retains its unscoped meaning. Frozen strand/domain targets
  remain protected; only unscoped operations advertise `change_clusters=true`.
- Tests-first red: 11 failed/7 passed in 3.06 s. Eighteen retarget cases now pass
  inside the final 373-case run, including two disjoint moved groups, initial
  and final JSON roundtrip, preview/Apply/native-selector parity and cold replay.
  A prior green attempt exposed ISSUE-106's invalid source fixture; correcting
  that setup retained the real save/reload checks and recorded the defect.
- The gated popup submits current checked IDs and retains failed Apply. Actual
  desktop All/None, group/plane reversals, undo/redo and save/reopen remain MV-48;
  do not claim ordinary desktop closure until the integration gate is qualified.

## ISSUE-106 — Grouping every helix removes a retained lattice-frame owner (2026-10-16, PREVENTION + LIVE/SAVED REPAIR IMPLEMENTED; APP OPEN)

- `part_overlay_commands.build("cluster_create", ...)` drops the default group
  when its final helices move into named groups. A retained
  `LatticeFrame.placement_cluster_id` still names that group, so the resulting
  model fails real JSON save/reload validation with **lattice frame placement
  cluster is missing**. Ordinary `create_group` uses this same builder. The
  failed retarget validation run exposed six save/reload failures; membership
  editing itself had passed. The source fixture was invalid before that edit.
- The dedicated [characterization](tests/test_group_frame_ownership_characterization.py)
  constructs a valid native bundle, groups all helices and demonstrates the
  dangling reference. It deliberately records invalid legacy behavior, not an
  acceptance criterion. Input-only reproduction previously returned `verified`
  because the same builder recreates the invalid output; this does not establish
  structural validity. The isolated characterization passes inside the final
  373-case run; its passing result reproduces the defect and does not fix it.
- Keep ISSUE-105's acceptance fixture valid using its named arm plus the real
  surviving default group, both moved through native inputs; retain initial
  and final full JSON roundtrips. Do not remove the save/reload check.
- New grouping uses `cluster_create` v2, retaining all existing identities and
  order even when membership becomes empty. Saved v1 remains exact and is now
  flagged as structurally invalid separately from successful reproduction.
  Final history-edit/repair candidates require bounded frame-reference closure;
  direct deletion cannot remove a referenced placement owner. No full model
  validation or structural inventory enters the isolated slider path.
- Generated joins select the stem by ID; namespaced grouping uses a deterministic
  v2-only identity seed. Ordinary empty/missing group selections no longer create
  bend/twist operations whose empty affected list means all helices. These are
  authoring guards, not changes to native deformation math or saved v1 replay.
- The schema extension uses an explicit exact-manifest compatibility policy for
  the three affected numerical families; no stored pins, numerical kernels,
  constants, data or geometry goldens are rewritten. Proof discloses transitions.
- The explicit `upgrade_cluster_creation` action now replaces only a recognized
  v1 typed row's version. Its complete original-definition digest survives saved
  proposals and explicit rebase. The repair panel offers the action separately
  from numerical upgrades; Evaluate rebuilds the full recipe in the existing
  worker, and Apply publishes one valid candidate with one undo. Native tests
  cover downstream move/bend/twist, save/reload/cold proof, stale revisions,
  cancellation and session changes. Source-free overlay discovery no longer
  serializes typed definitions under the state lock.
- Subsequent FH-19 delivery implements bounded saved-file recovery as a separate
  downloaded copy. FH-18 U4 adds broader typed incoming group-reference refusal
  and recorded admitted dissolution. Still open: actual desktop save/reopen,
  selection and latency, plus general posed/regrouped membership and auxiliary
  group lifecycle. Retention does not solve grouped-end continuation.
- Validation: **563 distinct backend passes**, including three fresh-process
  numerical compatibility cases. [Evidence](docs/audits/feature_history_20261014/validation_grouping_structure.json)
  retains red/integration failures and cleanup. MV-48 desktop/latency and broad
  regression debt remain open. That prevention checkpoint changed no frontend;
  the later repair checkpoint adds the explicit panel choice. No scientific
  golden or molecular algorithm was changed.
- Repair validation: **631 focused backend passes/14 warnings**, full frontend
  **8,464 passed/one skipped**, scoped Ruff/diff clean, `main.js` delta zero.
  [Repair evidence](docs/audits/feature_history_20261014/validation_grouping_repair.json)
  includes preserved red failures and cleanup. **NOT VERIFIED IN APP**; this
  does not clear invalid-file recovery, broad backend or interaction timing debt.

## ISSUE-107 — Standalone geometry responses lack a revision contract (2026-10-16, SOURCE-AUDITED; OPEN)

- `crud.get_geometry` captures a Design but its response has no document/revision
  identity; `client._applyGeometryResponse` applies completed GET results without
  a design-revision check. Two same-document reads can therefore finish out of
  order. Document-reset cancellation alone does not address that interleaving.
- Required reproduction before a general fix: hold GET A from revision A, apply
  revision B and GET B, then release A. Verify the newest Design and geometry
  stay paired. Include complementary partial reads and metadata-only revisions;
  a global newest-request token could incorrectly discard useful partial data.
- FH-18 membership/mixed authored-pose PATCH avoids this seam by embedding exact
  accepted candidate geometry in the revision-bearing design response. The
  client regression reverses those PATCH responses and retains the newest pair.
  This does not fix standalone GETs or the older-server fallback.
- General capture/response/merge qualification remains within the existing
  FH-27 milestone, not a new estimated update. No live app reproduction or
  general fix is claimed; MV-48 retains the interaction acceptance work.

## ISSUE-108 — Native crossover growth drops authored helix metadata (2026-10-16, REPRODUCED; OPEN)

- **Trigger:** single/batch crossover motion extends beyond a helix's stored
  range. Both native growth branches reconstruct `Helix` with a partial field
  list, omitting `lattice_frame_id`, `label`, `direction`, `native_source` and
  `native_residues`. In a two-junction batch, intermediate growth uses original
  opposite endpoints even when the final middle domain fits its stored range.
- **Evidence:** native controls in `tests/test_group_lineage_crossovers.py`
  reproduce ordinary metadata loss and the original-opposite-endpoint case.
  Corresponding new-organization tests refuse before builder invocation and
  preserve the source. Both HC/SQ in-bounds native parity remains covered.
- **Current containment:** private organizational replay refuses affected
  metadata-bearing helices when the source/final endpoint envelope could enter
  the native growth branch. It also refuses inverted/overlapping moved output.
  Existing native builders and legacy behavior are unchanged; this does not fix
  their omission or establish complete crossover consumer support.
- **Required exit:** preserve authored fields through native growth, verify
  complete native output/frame/source behavior and batch intermediate cases,
  then remove the qualified refusal. Keep molecular placement unchanged; any
  actual scientific change requires the existing A/B authorization gate.
  This belongs to existing core geometry/Fine Routing qualification, not a new
  counted overhaul milestone. Desktop acceptance remains open.

## ISSUE-109 — Repair capture rejects native deformation direction enums (2026-10-16, FIXED IN FOCUSED CHECKS)

- **Trigger:** a recipe contains a resolved scoped deformation. Its typed
  `DeformationRange.direction` is the native `Direction` enum; cloning the
  definition for repair inspection or a saved proposal raised the generic
  "typed definitions and JSON inputs only" error. This also affected repairs
  of another row when the capture included that deformation definition.
- **Cause and fix:** `_Copier.clone` admitted exact strings and typed models but
  omitted their closed immutable direction scalar. It now admits only the exact
  native `Direction` type, charges its value against the existing byte budget,
  and preserves the enum. Arbitrary enums remain rejected; there is no generic
  stringify fallback, serialization under the source lock, or budget increase.
- **Evidence:** `tests/test_part_deformation_repair.py` includes the native enum
  control, an unrelated string-enum refusal, resolved named bend/twist recipes,
  and their repair lifecycle: 31 core cases and eight repair-job cases pass.
  Complete checkpoint evidence records 967 distinct focused backend passes
  and 8,601 frontend passes/one existing skip in
  `docs/audits/feature_history_20261014/validation_named_deformation_lifecycle.json`.
- **Scope:** this fixes capture of existing native definitions. Named target
  editing, historical display intervals and owned publication are the separate
  U11 integration around it. **NOT VERIFIED IN APP**; rollout gates remain
  disabled, MV-48/FH-27 remain open, and FH-18 checkpoint 9 does not change the
  overall **18/38** milestone count.


## ISSUE-110 — Move Apply discarded refused pending placement input (2026-10-16, FIXED IN SOFTWARE CHECKS)

- **Trigger/source evidence:** the gizmo's sequential commit awaited
  `patchCluster` without checking its nullable response, counted the request as
  accepted, then cleared every pending transform. A failed request could therefore
  close the tool and lose the preview without a recorded edit. No live-app
  reproduction is claimed; the original source is preserved in the parent commit.
- **Correction:** extracted placement commit checks each acknowledgement and
  removes only the exact accepted local inputs. Legacy partial acceptance reports
  accepted IDs for geometry reconciliation and retains all unaccepted/newer inputs.
  Active organized parts use one bounded atomic existing-placement command with
  complete matching geometry; the tool avoids a second geometry transform.
  Failure keeps the current editor open. Document/reset/attempt guards retire
  obsolete replies and local tool state without restoring an old design.
- **Evidence:** actual gizmo factory, shared commit, tool lifecycle, API adoption
  and HTTP/native cold-replay/undo tests are recorded in
  `docs/audits/feature_history_20261014/validation_group_placement_ui.json`.
  The first attempted factory red run failed on an InvalidURL mock/import seam,
  not this behavior; it is explicitly not counted as a behavioral reproduction.
- **Remaining:** ordinary earlier placement editing is still guarded for active
  organization pending FH-23's isolated editor. New-group movement ownership,
  desktop/VR and latency acceptance remain open. No placement arithmetic changed;
  the public organization gate stays false. MV-48 still applies.


## ISSUE-111 — Queued visibility rollback and same-ID reload (2026-10-16, CORRECTED BEFORE U12 CHECKPOINT)

- Final review of the new organized visibility adapter found two cases:
  an earlier successful save advances the document revision before the latest
  queued save fails, invalidating a gesture-time rollback token; and old pending
  saves suppress hydration when a replacement uses the same design ID.
- Bind rollback to serialized dispatch while retaining the gesture's prior
  visibility/undo and local edit epoch. Count pending saves per document-reset
  generation, force replacement hydration, and ignore old completion bookkeeping.
  An empty named-group selection also avoids building a topology index.
- Focused regressions hold the requests and assert both visible bases and undo
  after success/failure/reset interleavings. U12 evidence records actual results.
  This was corrected during implementation, not a claimed released-app defect
  or a new milestone. Desktop/latency acceptance remains MV-48/FH-27.

## ISSUE-112 — Held deformation Prepare blocks reopening after reset (2026-10-16, FIXED IN SOFTWARE CHECKS)

- **Trigger:** reset the document while private Prepare is pending and its
  transport ignores cancellation. The controller retired the lease immediately,
  but the app owner kept its local `opening` flag until that request settled.
  Opening another tool was refused despite the replacement document being ready.
- **Cause/correction:** the render listener returned before observing closed
  controller state while `ready` was false. Track the current opening's first
  open emission, then retire its generation on a later closed emission. Ignore
  the controller's initial invalidation; late packets/finalizers cannot affect
  a replacement editor. Shared creation/history ownership uses the same fix.
- **Evidence:** the held-Prepare reset/reopen regression failed at the immediate
  `active() === false` assertion, then passed with a new tool opened before the
  old response arrived. The 20-case app/editor focused pass includes this case.
  Full checkpoint results are in
  `docs/audits/feature_history_20261014/validation_deformation_creation.json`.
  Other intermediate fixture failures are recorded separately, not counted as
  behavioral reproductions. No live-app reproduction or rollout is claimed.


## ISSUE-113 — Strand visibility queried by rebuilding every mask (2026-10-16, FIXED IN SOFTWARE CHECKS)

- With a hidden placement, each spreadsheet strand query iterated the complete
  geometry to rebuild a visibility mask already held by the controller.
- A deterministic iteration-counter regression observed 40 extra geometry scans
  during 40 queries; use the prepared effective mask instead. It also includes
  named-group hiding and existing explicit show exceptions.
- This removes repeated query work; larger-part latency remains unqualified.
  U14 evidence records the failing regression and final software checks.

## ISSUE-114 — Saved Join decorations ignore endpoint hiding (2026-10-16, FIXED IN SOFTWARE CHECKS)

- Native candidate selection used the effective endpoint visibility callback,
  but saved dashed bridges checked placement IDs only. Hiding their bases or
  named group could leave those lines visible.
- Saved lines now retain tiny endpoint/placement references; visibility changes
  toggle the existing line without rebuilding/disposal. Regressions assert line,
  geometry and material identity, placement masks and inert disposal.
- This is display behavior only. Native Join admission, port generation and
  calculations are unchanged; organized Join publication is still unqualified.

## ISSUE-115 — Save/export can race queued presentation writes (2026-10-16, FIXED IN SOFTWARE CHECKS)

- Hide persists asynchronously; immediate Save/Save As/export previously read
  the server before that write completed. A reset during a held save could also
  assign an old path or download the replacement document.
- File I/O drains the current presentation queue, including newly appended
  writes, and binds the operation to the original document incarnation. Guard
  each asynchronous read/writer boundary and late path/status/mirror/download;
  remove the now-unused duplicate client export function.
- Failing held-write/reset regressions precede the fix. An already dispatched
  server write or committed file close cannot be recalled by these guards.
  U14 evidence and MV-48 retain software/app distinctions.

### ISSUE-111 reopened during U14 — both queued saves fail (reopen count: 1)

The prior cases covered either an earlier success or a later success. When both
requests failed, restoring the latest gesture's before-state retained the earlier
unsaved hide. Two null/throw regressions failed on the still-hidden bases. Keep
one acknowledged presentation/undo checkpoint per document generation; an eligible
latest refusal restores it. A later accepted complete save retains both user
gestures and their undo. Existing source/revision/reset guards remain intact.
This corrects the same queue defect before rollout; it reopens no completed
milestone because FH-18 remains open. App qualification remains MV-48/FH-27.


## ISSUE-116 — Empty new display field breaks prior strict recovery bytes (2026-10-16, CORRECTED BEFORE U14 CHECKPOINT)

- During schema review, adding the default-empty group mask made serialized
  designs differ from otherwise valid prior strict records. Three tests failed
  at canonical-byte equality, stored preparation and real spawned recovery.
- Omit only this new empty field during serialization; retain all existing
  fields and nonempty group masks exactly. The strict preservation projector
  validates the new list is empty before retaining its original three-field
  digest. No normalization exception, cache rewrite or integrity weakening.
- Tests include ordinary snapshots, nonempty roundtrip and unknown/missing-field
  refusal controls. Exact original bytes/lease survive worker materialization.
  This was an unreleased intermediate regression; no completed milestone reopens.

## ISSUE-117 — Pattern refusal/reset and delayed geometry adoption (2026-10-16, FIXED IN SOFTWARE CHECKS)

- Pattern panels previously closed after a null response and retained old previews
  during a same-ID reset while committing. Preserve refused drafts, retire reset
  previews and bind source/document/revision/feature identity before dispatch.
- Design-only responses delegated to a second unbound geometry fetch; a delayed
  fetch could overwrite geometry from a later edit. Count-preserving history
  edits could also return a partial response to the full-response dispatcher.
  Pattern creation and owned historical edit now embed current/straight geometry
  from the exact candidate. Publication and response formatting remain separate.
- The shared legacy geometry-fetch path outside patterns is not changed here.
  MV-48 retains desktop/latency acceptance; software evidence is in U15.

## ISSUE-118 — Copied Sweep consumes original operation identities (2026-10-16, CORRECTED IN ORGANIZED PATTERNS)

- Pattern copies assign new deformation identities. Sweep's consumed-operation
  list must follow those identities so a copied earlier Bend/Twist is not applied
  again. The organized copier remaps only operations actually copied; historical
  selectors and the native numerical evaluator retain their existing meaning.
- Independent coordinate checks pass for linear and circular copies of a Sweep
  with a preceding Bend. This correction is confined to the new organized path;
  legacy pattern behavior is unchanged. MV-48 retains visual qualification.


## ISSUE-119 — Historical continuation keeps stale source receipts after input edits (2026-10-16, CORRECTED IN OWNED EXTRUSION EDITOR)

- Changing continuation cells or its source frame can select different prefix
  helices, while generic identity preservation retains `_source_helix_ids` from
  the old definition. That receipt must describe the edited input dependencies.
- The private extrusion evaluator refreshes only the selected continuation's
  receipt from the independently rebuilt pre-feature design, after preserving
  output identities. It rejects missing frame/helix selections with typed input
  paths. Untouched rows, native builders and output identity rules are unchanged.
- Source binding, full historical reconstruction, failed-edit atomicity and real
  worker transport are covered by the U16 checks. Desktop acceptance remains
  FH-27/MV-50; no additional milestone credit is assigned to this correction.

## ISSUE-120 — Native Sweep preview used legacy downstream rebasing (2026-10-16, CORRECTED IN GATED EDITOR)

- The legacy history preview proportionally rebases routing addresses and follows
  attachments using recovery snapshots. Native Apply rebuilds saved command
  inputs. Those two meanings must not share an authoritative preview claim.
- The owned editor rebuilds the historical prefix and selected Sweep privately,
  labels the feature stage, and checks the complete source/suffix only at Apply.
  A later nick retains its recorded address. Removing its helix now gives a typed
  reference issue and the failing feature ID, without changing the source/draft.
- The first backend pass exposed the missing single-nick reference check and
  lost feature attribution. Corrected checks pass; native geometry formulas and
  still-used legacy recovery behavior remain unchanged. Rollout stays disabled.

## ISSUE-121 — Preview Apply could exceed deadline during preservation (2026-10-16, CORRECTED)

- The legacy-source branch checked the deadline before preserving presentation
  and validating dependencies but could publish after that work exceeded it.
- Recheck the deadline, original source and lease immediately before publication,
  using lock-owned checks rather than reacquiring the non-reentrant state lock.
  Failure restores the ready lease and preserves source/undo. A deterministic
  post-preservation expiry regression covers the shared host.

## ISSUE-122 — Legacy picker callbacks and newer-view ownership during Sweep (2026-10-16, CORRECTED IN GATED EDITOR)

- A hidden Extrude button/Enter handler could still call canonical authoring
  while the picker held Sweep's private prefix. Private context now refuses
  legacy extrusion/placement callbacks; releasing it restores ordinary behavior.
- Closing an old editor must not hide a newer camera/view's picker. Picker
  release and panel cleanup retain exact context ownership, including camera
  transitions. Held Prepare can be cancelled from Escape or another tool.
- These are isolation corrections within FH-22, not new milestones. Actual
  controls and ownership regressions are included in U17; desktop remains MV-51.

## ISSUE-123 — Native move history could discard requested inputs or retain stale reset targets (2026-10-16, CORRECTED IN NATIVE HISTORY API)

- Placement edits ignored unknown fields and target changes; nucleotide edits
  accepted coerced booleans and empty batches. A reset target change kept the
  former nucleotide's target receipt. Generic output protection also incorrectly
  treated an extra-base movement's crossover reference as an output identity.
- The four ordinary movement roles now share strict selected-row inputs and
  prefix binding. Preserve actual output/proof identities; resolve references
  explicitly and refresh reset receipts from that prefix. Typed failures identify
  the selected or downstream failing feature and leave source/revision/undo intact.
- Initial red tests reproduced all of these API failures. Native placement math
  and pinned identity factory are unchanged. This is FH-23 implementation progress,
  not closure of the complete controls/display or new-group movement contract.

## ISSUE-124 — Sweep test generated random collection IDs under xdist (2026-10-16, CORRECTED)

- The U17 protected-identity test generated its parameter UUID at import time.
  Separate pytest workers collected different node IDs, stopping the standard
  fast suite before execution. Use a fixed distinct UUID for this test case.
- The standard run also encountered the separately unavailable Archive-backed
  CPD fixture during collection. Fixing the test ID does not clear that environment
  failure or deferred FULL-suite debt; focused multiworker validation is separate.

## ISSUE-125 — Historical constrained movement omits linked owner writes (2026-10-16, OPEN)

- Code audit: `cluster_gizmo._paintLinks` queues solved absolute poses for linked
  owners, while `translate_rotate_tool`'s history branch edits and clears only
  `editCtx.clusterId`. Detach does not discard the other pending owner transforms.
  This is an audited mismatch; no application reproduction is claimed yet.
- The existing flexible-relax snapshot also records only the cluster ID list,
  not accepted poses or complete solver inputs, so it is not a replay substitute.
- The complete FH-23 contract retains all linked/joint/tether controls. Implement
  an explicit complete multi-owner input operation and atomic private ownership;
  preserve old single-row meaning and never infer coupled historical rows by
  proximity or adjacency. Do not call the ordinary single-owner host a fix.
- Required regression: selected + linked + fixed owners through actual control
  solve, failed Apply/cancel, downstream edits and cold proof. Archive-dependent
  app qualification remains FH-27. This issue is existing scope, not a new milestone.

U20 progress: the gated owned editor now records all emitted native poses in
`placement-poses`, with explicit old-row upgrade, frame/source guards and one
publication. Focused tests cover complete queued auxiliary writes and fixed-owner
refusal; native compound Apply/cold-replay/undo checks pass. Actual linked-control
solve matrices and qualified rollout remain open, so the still-used legacy path
and this issue are not declared resolved.

## ISSUE-126 — Connection-version DS application can retain duplicate bridge occupancy (2026-10-16, OPEN)

- The native mixed-end fixture with `root-to-root-dsdna-linker` produces two
  FORWARD bridge domains on the same virtual helix. This is existing output,
  already visible as duplicate-occupancy warnings in
  `benchmark_finite_connection_apply_route_warning_diagnostic.json` in the
  feature-history audit. U19's complete transform inventory detects it again.
- `overhang_ops._check_linker_compatibility` has a DS mixed-polarity check, but
  the legacy/finite connection-version application path does not call it. This
  audit does not authorize changing native strand polarity or existing outputs.
- Retain a native-output characterization and whole-display refusal regression.
  Qualify positive DS display using an existing compatible authored connection
  type, not edited strands or relaxed occupancy checks. Complete application
  admission/repair remains the original ordinary-connection milestone FH-25;
  no new milestone or completed credit is created.

## ISSUE-127 — Four regression expectations lagged grouping and dependency contracts (2026-10-16, CORRECTED TESTS)

- Standard FAST exposed a v1 grouping pin after the v2 recorder change, two
  generic missing-owner expectations after typed reference resolution, and an
  authored Bend scope test still expecting silent removal of a missing group.
- Update those existing tests to exact v2/structured-reference/409 contracts.
  Keep no-partial-candidate and feature attribution checks; strengthen rejected
  scope checks to preserve source, revision and undo/redo contents and identities.
  A finalizer removes the test's synthetic redo branch even after assertion failure.
- Observed red cases pass in focused reruns. No production behavior is relaxed.
  The broad run also reported a repair-job setup error that did not reproduce in
  its eight-case file; retain it as unresolved broad-suite debt. Other recorded
  environment/scientific failures and deferred FULL validation remain separate.


## ISSUE-128 — Late Apply reply could obscure confirmed publication (2026-10-16, CORRECTED)

- A Cancel reply could confirm publication while the original Apply remained in
  flight. A subsequent malformed Apply reply retained the receipt but set
  `publicationUnknown` again, obscuring an already confirmed save.
- Preserve confirmed authority while reporting the conflicting reply. The shared
  controller regression was observed failing and now passes; do not infer a
  second commit from transport failure. Transform receipts require their full
  exact origin/role; legacy small-receipt enrichment keeps its prior contract.

## ISSUE-129 — Private joint drag preview/final pose used incomplete callback state (2026-10-16, CORRECTED PRIVATELY)

- Actual offset-axis ring tests exposed an interim translation mismatch and a
  release-time callback that preceded the native final pending pose. An accepted
  preview response could also replace the native gesture's starting owner pose.
- The owned adapter composes the existing native live delta against its captured
  baseline and adopts the native finalized pending pose after pointerup. Preview
  redraws preserve that baseline until release. Active-drag Apply refuses;
  reset/dispose/lock/newer numeric motion invalidates queued completion.
- Independent world-point oracles and real native gesture-to-host tests retain
  native joint limits, exact complete linked poses, source isolation and cleanup.
  No molecular solver/math change. Paired rollout remains off; MV-52 app debt stays.

## ISSUE-130 — Terminal extension CRUD bypassed feature-history inputs (2026-10-16, CORRECTED PRIVATELY)

- Ordinary terminal sequence/modification create/update/batch/delete changed the
  design without executable feature inputs. New closed top-level upsert/delete
  commands retain authored IDs, typed strand/extension failures and cold replay.
- All supplied batch items validate before valid repeated termini coalesce;
  omitted update fields and explicit clearing retain ordinary semantics. Delete
  keeps its synthetic-only response and skips topology reconciliation/retry.
- Historical upsert v1 retains global postprocessing and its dependency barrier.
  U25 adds extension-only v2 plus the owned organized transaction. Placement arrays,
  overlapping/opposite-domain owners, parent/driver frames and empty frame owners
  stay exact. V2 upserts/deletes order through the extension inventory; unrelated
  placement edits do not acquire a topology barrier. Gates remain false.
- Ordinary five-URL CRUD captures bounded source inputs, then publishes only
  extensions and one row through the existing permit/undo transaction. No-op edits
  return an explicit same-revision receipt. Native full upsert geometry belongs to
  that candidate; deletion keeps synthetic-only geometry. Shared 2D/3D controls
  preserve failed input. Desktop/performance remains MV-48/MV-52/FH-27.
- Legacy rootless documents are not automatically certified. New commands add no
  public strict-policy bypass; repair UI/catalog completion remains FH-26/FH-29.

## ISSUE-131 — Private movement display rejected junctions owned by flexible arcs (2026-10-16, CORRECTED PRIVATELY)

- Actual empty-root three-arm flexible/joint histories exposed a completeness
  check that counted only rigid cones/connectors. Native flexible arcs own the
  internal forced-ligation bonds, so valid packets were refused before rendering.
- The private adapter accounts for actual consecutive flexible-path keys and
  reuses the ordinary display's suppression of duplicate anchor-to-anchor chords.
  Do not weaken junction completeness, alter authored topology or replace native
  flexible coordinates. Real source→renderer→gesture→Apply proof is the exit.

## ISSUE-132 — Reaped verification workers could release admission before buffer cleanup (2026-10-16, CORRECTED)

- The shared supervisor treated three cleanup failures after process death as
  sufficient to release its single worker slot. Process death does not prove
  that shared-memory mappings have closed or named buffers have been unlinked.
  Repeated failures could therefore admit further allocations while leaking old
  transport. This matters before reusing the supervisor for numerical previews.
- Keep the job visibly stopping and retain admission until `close()` succeeds,
  with the existing polling interval. Remove the obsolete three-retry constant;
  the file-recovery supervisor already follows this stronger ownership rule.
- A failing regression reproduced the premature release. Coverage includes five
  repeated close failures, real shared-memory unlink retries, live-child cleanup,
  cancellation and source changes. A persistent OS cleanup failure deliberately
  leaves admission occupied; the service must not pretend that resources are free.


## ISSUE-133 — Numerical preview phase transitions could lose results or authorize a duplicate retry (2026-10-16, CORRECTED PRIVATELY)

- Integration review reproduced four backend races: a stale Apply bound a newer
  sequence, a busy claim erased a completed packet, receipt-timer failure removed
  an already published result, and a failed ready timer retained a prefix/result
  alongside terminal failure. Fixed request binding, admission-before-retirement,
  authoritative receipt retention and terminal-prefix cleanup close these cases.
- Frontend regressions reproduced a Status404 clearing unknown-publication state
  and local display validation being credited back to the lease. Status transport
  refusal proves no publication outcome; only a validated terminal worker refusal
  permits retry. Local receive time anchors the final lease budget.
- Timer callbacks bind to their own deadline; numerical computation, ready inputs
  and scalar receipts have distinct lifetimes. Polls never renew them. Targeted
  red/green evidence lives in the U23 numerical lifecycle report. The ordinary
  editor limits and scientific builders are unchanged; rollout stays gated.


## ISSUE-134 — Extension requests and dialogs could lose ownership or report false success (2026-10-16, CORRECTED)

- The old dialog treated a null API result as success and closed; keyboard Delete
  cleared selection before acceptance. The new shared dialog retains failed input,
  and accepted deletion clears only the still-matching selection. Held responses
  cannot affect a reset document or replacement dialog. Protected edits never
  activate another loadout and retry old strand IDs.
- Transport regression reproduced a same-source/session-object incarnation reset
  during body acquisition; bind the scalar session identity as well. Publication
  already checks source/revision/policy, candidate identity, cancellation and expiry.
- Review found unchanged nonempty upserts wrongly required an incremented revision.
  Explicit host no-op receipts acknowledge unchanged Apply without an extra row;
  false/malformed same-revision packets remain refused. Empty partial deletions
  preserve geometry caches rather than entering the generic full-replacement branch.
- No-op upserts, including empty batches, still return full geometry and therefore
  require native-work admission. The bounded host validates closed input before
  snapshots/publication. U25 evidence retains regression failures and corrections;
  desktop behavior and representative latency remain unverified.

## ISSUE-135 — Saved terminal-nucleotide pose moves atomistic tail but not Full tail (2026-10-16, OPEN)

- Native empty-root 8-bp duplex → two extension-upsert v2 sequence tails → one
  terminal nucleotide rotation/translation reproduces the disagreement at both
  5′/3′ ends and in both directions. The selected terminal moves in both outputs;
  the Full tail moves 0 nm, while its atomistic counterpart moves 3.01685–6.71209 nm
  in these examples. Unselected atoms/Full records, atom identities and bonds
  remain exact. This is not a comparison between coarse and atomic coordinates;
  it is a comparison of each representation's response to the same saved pose.
- Cause: extension atoms retain the terminal helix/bp/direction and fall through
  `atomistic.apply_nucleotide_transforms`' ordinary-base lookup. Full extension
  records have synthetic helix IDs, and their construction anchors precede the
  later nucleotide-pose pass. They therefore miss the same transform.
- Reproduction: `just test-affected tests/test_part_motion_native_characterization.py --tb=short -s`.
  Four passing characterization cases describe the bug, not desired semantics.
  Replace their discrepancy expectation when an explicitly demonstrated common
  molecular policy is authorized; do not silently make either representation
  the oracle or update a geometry golden.
- No production correction is made in U26. The full member-motion companion/frame
  matrix and inspectable molecular authorization remain required. This issue is
  within existing FH-18/FH-23 scope and adds no milestone. See
  [U26 evidence](docs/audits/feature_history_20261014/validation_member_motion_order.json).


## ISSUE-136 — Ordinary routing calculations could use a different source than their history row (2026-10-16, CORRECTED)

- Loop insertion and loop/skip twist/bend computed an updated design before
  acquiring the recording lock, then ignored the callback's current source.
  A concurrent edit could be overwritten while the history row described inputs
  applied to another design. Crossover movement calculated twice, with response
  scope/no-op decisions from the first source and recorded geometry from the second.
- `part_routing_recording` now selects the source under the existing recording
  lock and invokes each native operation once. Source/session/incarnation/revision,
  policy and protected-loadout checks precede work and publication. Existing
  recorders still own reconciliation, retry, one history row and undo/rollback.
  No-op moves remain no-ops. Missing explicit twist/bend helix IDs now refuse;
  silently omitting them would record inputs that strict replay cannot reproduce.
- Red ownership coverage: 17 failed / 25 passed before the correction. The final
  expanded 47-case ownership suite passes, including legitimate empty intervals,
  stale-mark removal and no full recipe proof on ordinary routing gestures.
- Native molecular calculations and constants are unchanged. Representative lock
  time and desktop responsiveness remain FH-27; this fix earns no extra milestone.

## ISSUE-137 — Native routing failures could lose the actual failing history child (2026-10-16, CORRECTED)

- Regeneration attributed typed reference failures, but a native `ValueError`
  (for example nicking an already nicked site) escaped without its child identity.
  Two legacy/organized owned-editor tests reproduced the lost row attribution.
- Wrap native input failures at the executing row, preserving the actual later
  child's identity when a downstream step fails. Resource/time/cancellation
  outcomes retain their distinct semantics and do not become invalid-geometry
  accusations. The candidate remains private and undo/redo remain untouched.
- Bounded routing HTTP edits also refuse partially specified source guards rather
  than falling through to address-only legacy editing. Full FH-26 repair remains
  a separate unfinished milestone; these diagnostics do not close it.


## ISSUE-138 — Owned history edit responses could retain stale browser recovery bodies (2026-10-16, CORRECTED)

- Routing, extrusion and organized pattern edits regenerate later snapshots/diffs
  while retaining feature IDs. Their HTTP replies preserved only the selected
  row's body. The browser's partial-history merge would restore older later-row
  bodies by ID and persist them in its recovery cache.
- Eight HTTP regressions reproduced incomplete history replies across all three
  families, including a response formatted after another source change. These
  owned regeneration replies now use the existing full-history response option;
  their history and geometry describe the same accepted candidate. Ordinary
  append responses keep their existing slimming, and the explicit 2D skip
  contract is unchanged. The existing cumulative recovery allowance is 8 MB.
- No new cache authority or alternate snapshot replay path is introduced. Native
  input replay remains authoritative; response-size/desktop qualification remains
  FH-27. This adjacent regression correction does not add milestone credit.


## ISSUE-139 — Combined Connect default naming mutates held source versions (2026-10-16, CORRECTED)

- `model_copy(deep=True, update={...})` applies update objects without deep-copying
  them. Combined Connect supplied the original connection-version records, then
  default naming mutated their blank names through shared references.
- Canonical failure rollback already restores the recorder snapshot; this issue
  affects holders of the original source object, including successful callbacks.
  Two actual native parity controls and a real failed-publication control exposed
  the mutation. No molecular helper is mocked or changed.
- Copy the version records supplied in the update before naming, including the
  proposed new version. Keep the existing whole-design copy, one undo and native
  calculation order. Exact authoring parity and held-source/revision/history/redo
  regressions pass in the111-case focused run. Combined native history remains
  unfinished under FH-25; this correction does not grant a new replay capability.


## ISSUE-140 — Direct replacement retains Duplex ownership and relocation (2026-10-16, CORRECTED)

Ordinary connection-version Apply removed conflicting bindings/linkers but never
removed their display Duplex records or restored unequal-length Duplex-owned
topology. Native bundle/extrusion controls reproduced all eight equal/unequal,
direct-type and finite/indirect replacement cases. Cleanup now uses existing
binding and Duplex restoration before patching replacement sequences, then drops
all conflicting direct records. No new molecular placement is introduced.
Twenty new cases cover explicit/blank sequences, direct type switching, complete
restoration and source isolation; six-file regression157passed. Full direct
history contracts remain FH-25 work. App/visual qualification remains unverified.


## ISSUE-141 — Conditional direct binding IDs make downstream replacement brittle (2026-10-16, OPEN)

An equal-to-unequal upstream extrusion edit changes native direct ownership from
binding+display Duplex to a bound Duplex. Exact consumer conflict lists retain the
conditional binding ID, so downstream replacement fails with a typed missing
reference. Native regression proves attribution/source isolation and an explicit
isolated recipe correction followed by independent verification. That does not
qualify manual internal-ID editing as acceptable UX. Resolve stable logical creator
selection or reviewed prefix rebinding before FH-25/FH-26 rollout; preserve literal
saved contracts, strict missing/ambiguous ownership checks and native algorithms.
Research/evidence: [U35](docs/audits/feature_history_20261014/ordinary_connection_completion_plan.md#branch-changing-upstream-edits-issue-141-remains-open).

ISSUE-141 U36 update: new direct v2/linker v4 recipes select the stable creating
namespace and validate its rebuilt native owner set. Equal/unequal branch edits
no longer require internal binding-ID repairs. Old literal recipes intentionally
retain their saved meaning; reviewed legacy rebinding and public qualification
remain open. No molecular builder or restoration snapshot format changed.

## ISSUE-142 — Ordinary Unapply/Delete UI omits Duplex teardown and is non-atomic (2026-10-16, OPEN)

Source audit: `frontend/src/ui/overhang_connections_panel.js::_onApply` and
`_deleteVersion` call `_teardownPair` and then patch/delete saved metadata in
separate requests. `_teardownPair` deletes only the first pair linker and binding;
it never selects a Duplex. Unequal native direct connections have a bound Duplex
and no binding, so this helper cannot restore their driven topology. Equal native
connections also retain a display Duplex unless separately removed. An earlier
request may commit before a later failure. U37's metadata-only recipes deliberately
do not disguise this as geometric disconnection.

Required existing FH-25 exit: one source-bound, failure-atomic explicit
Unapply/delete-with-disconnect operation over exact owned pair materialization,
using shared native restoration admission; preserve metadata-only CRUD semantics
for explicit API use. Wire the UI to that operation, qualify both direct branches
and finite/indirect types, incoming-owner refusal, undo/reload/cold replay and
failed-publication source preservation. Do not broaden pair teardown to unrelated
third-endpoint conflicts or reinterpret `applied=false` as a successful removal.
No molecular placement change is authorized by this finding.

ISSUE-142 U38 update: explicit registered exact-pair disconnection now restores
linker/binding/Duplex owners and changes saved metadata in one transaction.
Private source-bound HTTP and shared UI Unapply/Delete controller are wired;
the unused `_teardownConflicts` helper was pruned. Native family/branch replay
and third-endpoint preservation pass. Both rollout gates remain disabled;
MV-54 desktop/latency acceptance is outstanding, so the public defect is not
claimed resolved. Existing metadata-only API semantics remain unchanged.

## ISSUE-143 — Unequal direct relocation leaves stale Duplex registers (2026-10-17, OPEN)

U41's owned connection matrix proves both direct types with A-longer/B-longer
endpoints reproduce native output that fails `Design.model_validate`: a Duplex
end still references its pre-relocation bp interval while its backing domain has
moved. Equal complementary endpoints pass. The unorganized native oracle fails
the same validation, so organization ancestry is not the origin of the defect.
`relocate_duplex` calls `apply_bind_topology`, then sets the snapshot/bound flag
without updating the Duplex end register. Examples: right interval[7,0] against
backing[34,41], or left[41,30] against backing[4,15]. Root cause lead: relocation
updates domain addresses without transporting this dependent register.

Reproduction/containment: `tests/test_connection_recipe_recording.py`, unequal
`test_owned_apply_disconnect_one_undo_and_replay` cases assert both the native
schema failure and the owned worker's `invalid_connection_output` refusal, with
unchanged source/revision/undo. This is NOT fixed and the four unequal direct
cases are not qualified successes. Input replay parity alone is insufficient.

Required FH-25 exit: preserve the intended molecular pairing through relocation,
restore and subsequent edits, then prove schema/reload/geometry/sequence parity
and the complete matrix. Do not clamp ranges, skip validation or drop a Duplex.
Any correction affecting pairing/geometry needs the established concrete A/B
molecular review before deployment. The current checkpoint only strengthens
worker diagnostics and leaves native molecular algorithms unchanged.

ISSUE-141 U43 update (2026-10-17): an explicit `upgrade_connection_owners` repair
now migrates recognized direct v1/linker v3 consumers to creator selection v2/v4.
An exact command-input receipt guards the target; only unique preceding native
producer definitions can identify an owner. Output IDs, seeds, time and unrelated
inputs remain fixed. Draft discovery reads no recovery and performs no producer
scan/hash; full repair regenerates the root and suffix before publication. The
repair panel offers a reviewed proposal, not an immediate mutation. Both shorter/
longer dependency branches and finite/indirect restoration pass; a native worker
case commits once and reloads. Ordinary historical recipes are not rewritten on
load. Desktop qualification and ISSUE-143's independent unequal native output
failure remain, so this is private migration evidence, not a full public closure.
