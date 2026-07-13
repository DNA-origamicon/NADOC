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

**Rebuilt 2026-07-13 (docs-cleanup audit).** The previous table was frozen at 2026-06-08 and listed only
ISSUE-1/2/3/4/8/9 — it had never been updated with ISSUE-11/12/13/14/15, four of which are still open. It
also still said "→ NEXT: ISSUE-1", written before those issues existed. Ranked below by *severity*
(silent corruption first), not by intake order.

| Order | Issue | Type | Size | Needs UX research? |
|-------|-------|------|------|--------------------|
| done | ~~**ISSUE-9**~~ ✅ FIXED 2026-07-13. **Not teeth-specific** — a plain 4HB bundle ratcheted `168→189→199→210` bp and `6→9→12` crossovers over three routes, on both routers. Cause: the router derived the face it extends from its OWN previous output (`_scaffold_coverage`), and the extenders are monotone. Fixed by normalising the INPUT, not the algorithm: `scaffold_reset.py` retracts each helix + re-seeds the scaffold to the **staple**-defined extent (staples are the structure; autoscaffold never touches them) so `reset(route(fresh)) == fresh`. Also fixed a second bug: `create_near_ends`/`create_far_ends` crossovers survived every "clear" (only the `auto_scaffold_` prefix was matched). | routing correctness / **data loss** | medium | no (algorithmic) |
| done | ~~**ISSUE-14**~~ ✅ FIXED 2026-07-13. NOT a console error and NOT an app bug — the spec died in the **test harness** during setup (a `waitForTimeout(500)` racing File→New's backend POST → 404 "No active design", plus a dead `/design/auto-scaffold` route 405-ing since `e9d6750`). Both fixed in `e2e/helpers/scene_harness.js` (shared by 9 specs). `just smoke` also now refuses to run under a live production sim, which was separately starving the heavy specs into timeouts. | test harness | — | — |
| **→ 2** | **ISSUE-16** `predict_shape(with_rmsf=True)` is **nondeterministic** — every `eigsh` in `fem_solver.py` omits `v0=`, so ARPACK picks a random start vector and identical inputs give RMSF differing by up to **3.7e-3 nm**. Surfaces as an intermittent `test_g12_salt_ignored_by_cando` failure, but the flaky test is only the messenger: the FEM RMSF output isn't reproducible, which undermines every SNUPI-vs-CanDo/MD comparator that diffs RMSF floats. Fix: seed `v0`. **Coordinate — the other machine is actively working in SNUPI/FEM.** | correctness / reproducibility | small | no |
| 3 | **ISSUE-11** Deformed-continuation helices carry `grid_pos=None` (`make_bundle_deformed_continuation` is the only builder not setting it). Any design with a deformed continuation **crashes** `canonical_topology`/`assert_roundtrip_stable`. Blast radius: `grid_pos` also drives cluster reconciliation, overhang-neighbor lookup and `loop_skip_calculator`. **ASK-FIRST** — the obvious one-line fix is suspected of being a Three-Layer trap (a non-None `grid_pos` may make `_helix_lattice_params` recompute lattice x/y and clobber the baked deformed world coords). | data model / three-layer | small IF approved | no (topology decision) |
| 4 | **ISSUE-8** Autoscaffold multi-section single-strand routing. Section router codified in `backend/core/section_router.py` behind default-OFF `NADOC_SECTION_ROUTER`. **BLOCKED on a user decision**, not on code: window end-turn lands *just-inside* (≤6 bp tooth-tip coverage gap) or *just-outside* (few-bp extension into the physical gap, full coverage). Not silently wrong today (default-off + warn-only). Parent of ISSUE-9; can't close without it. | routing correctness | medium | **needs user call** |
| 5 | **ISSUE-13** `resize_strand_ends` axis re-trim uses a different endpoint convention than `create_bundle` (`(max_bp − min_bp)·rise` vs `length_bp·rise` — one rise, ~0.334 nm, shorter). First resize of any end on a fresh bundle silently shifts `axis_end` and never reverts. Nucleotide count unaffected, but it breaks `canonical_topology` identity for a `+δ/−δ` inverse pair → a correctness hazard for any oracle that fingerprints axis floats. Same three-layer family as ISSUE-11. | geometry off-by-one | small | no (ask-first) |
| 6 | **ISSUE-12** Feature-log panel catch-all `else` mislabels `cluster_create` entries as "move/rotate" and wires the edit button to the *transform* editor (wrong tool, may error). Low impact today, but the catch-all will silently swallow any future new `feature_type` — a latent class bug. | functional bug | small | no |
| 7 | **ISSUE-1** Context-menu proliferation — Phase 1 ✅ + 2a-binding ✅ + 2a-orientation ✅ (2026-06-05). Phase 2a-blunt / 2b–2e / Phase 3+ open. 18 builders, 3 dismissal mechanisms, z-index sprawl 1000→9999→10000. Tech debt / UX, not correctness. | UX + tech-debt | large, multi-phase | yes (done) |
| done | ~~**ISSUE-15**~~ ✅ FIXED 2026-07-08 (surfaced-by-review; see fix log). Dossier belongs in the archive. | — | — | — |
| done | ~~**ISSUE-2/3/4/5/6/7/10**~~ ✅ closed and archived. | — | — | — |

This order is a recommendation; the user may name a different issue. Note ISSUE-8 and ISSUE-11 are both
gated on a decision only the user can make — don't burn a session trying to infer either.

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
- **Caution:** this is the area `memory/project_dumbbell_autoscaffold.md` documents as repeatedly producing
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

## ISSUE-17 — `polymer_router` SYNTHESIZES staples over bare scaffold ends (violates "staples are the user's intent"; ask-first)

- **Status:** `[ ]` OPEN — surfaced 2026-07-13 by a read-only audit while fixing autostaple (see LESSONS J6 /
  `feedback_staples_are_user_intent`). Not touched: it is a user-invoked topology op and the desired behaviour
  is a design call, not a mechanical fix.
- **The rule it breaks:** scaffold with no staple opposite it is a **deliberate ssDNA loop** — it suppresses
  aggregation by blunt-end stacking, and essentially every origami wants one at each duplex end. Staple
  placement is the user's intent; no code may treat missing staple coverage as something to fill.
- **What it does:** `backend/core/polymer_router.py` reads scaffold coverage, finds each unpaired scaffold run
  that touches a helix cap, and manufactures a STAPLE exactly complementary to it — `_complement_strand`
  (~:146-157) builds `Strand(strand_type=STAPLE)`, appended at ~:277. It also raises *"No unpaired scaffold ends
  found — nothing to route"* (~:270-274) as a hard **error** — i.e. it treats the *absence* of an ssDNA end as
  the failure mode and its *presence* as a thing to be filled. Net effect: it blunt-caps precisely the loops the
  rule protects.
- **Mitigating facts (for the decision, not an excuse):** it only fills cap-adjacent runs (interior runs are
  explicitly skipped), and it is invoked explicitly ("Route for polymerization"), never from a scaffold
  auto-route. Blunt ends may even be *wanted* here — polymerization is stacking-driven.
- **Fix shape (ASK FIRST):** most likely make the cap-end fill **opt-in** and rename/reclassify the module as an
  explicit *staple* operation (never callable from a scaffold-routing path). But if polymerization deliberately
  wants blunt ends, the right answer may be "document it and leave it" — confirm with the user before changing.

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
- **Fix shape:** gate both on `strand_type == SCAFFOLD and not is_reference` — mechanically the same guard the
  lattice-level equivalents already carry. Low risk, but it changes scaffold-routing behaviour on designs with
  linkers/overhangs, so pin it with a repro first (route a design carrying a linker whose complement sits in the
  scaffold slot; assert no staple/linker strand is nicked or fused).

## Next-session handoff

_Living pointer — each session overwrites this. **Last updated 2026-07-13 (docs-cleanup audit — no issue
worked).**_

**⚠ THIS LOOP IS DORMANT.** The last work done by the loop's own protocol was **2026-06-08** (ISSUE-7).
Everything filed since is drive-by intake from sibling loops (`/automate-feature`, `/continue-coverage`) plus
one opportunistic fix (ISSUE-15). Net flow over the last month: **+4 open, −0 worked.** The intake channel is
alive; the fix channel is not.

**2026-07-13: ISSUE-14 ✅ and ISSUE-9 ✅ both shipped this session** (the loop is no longer dormant).

**NEXT PICK: ISSUE-13 or ISSUE-12** — both small and unblocked. ISSUE-13 (`resize_strand_ends` axis re-trim
uses a different endpoint convention than `create_bundle`) is the more valuable: it is the same three-layer
family as ISSUE-11 and it silently breaks `canonical_topology` identity for a `+δ/−δ` inverse pair, which is a
correctness hazard for any oracle that fingerprints axis floats. ISSUE-12 (feature-log catch-all `else`
mislabels `cluster_create`) is smaller and purely cosmetic today, but the catch-all will swallow any future
`feature_type` — a latent class bug.

**Owed from ISSUE-9:** a user eyeball — run Auto-scaffold **twice** on a teeth design and confirm the tooth
faces do not move. Backend-only and fully unit-pinned, but it rewrites helix geometry, so it wants one look.

**Two issues are blocked on YOU, not on code** — don't let a session try to infer either:
- **ISSUE-8** — window end-turns just-inside (≤6 bp tooth-tip coverage gap) vs just-outside (few-bp extension
  into the physical gap, full coverage)?
- **ISSUE-11** — is setting `grid_pos` on deformed continuations safe, or does it clobber baked deformed
  world coords via `_helix_lattice_params`? (Three-Layer question.)

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
