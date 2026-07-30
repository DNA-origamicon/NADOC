# Plan-Audit Ledger — reconcile stale plans against live code

Driver for the `/audit-plan` loop. **One plan per iteration.** Each iteration takes one
`memory/project_*.md` (or root plan file), probes the codebase for the concrete things it
names, decides whether it is still real, and then **either deletes it or keeps it with a
priority rank.** This is the head; move closed rows to `plan_audit_ledger_archive.md` when it
passes ~200 lines.

## Why this loop exists

The survey of 2026-07-24 found ~40 plan/topic files in three states — abandoned, unfinished,
done — but "abandoned per the file's own words" is not proof: a plan can *say* it's stalled
while the code it describes is live (e.g. `bundle_stiffness_params` 0T data, `periodic_md`
backend), or *say* it's a plan while a newer, undocumented module already shipped it. Only a
**codebase probe** settles it. This loop makes that probe systematic and drives each plan to a
terminal state: deleted, or kept with a rank and a refreshed open-items list.

## Verdict taxonomy (pick exactly one per plan)

| Verdict | Test | Action |
|---|---|---|
| **DERELICT** | Feature dropped/disabled; the code path it describes is gone, dead, or explicitly switched off with no intent to resume, AND nothing live depends on the doc. | **Delete** the file + scrub its `MEMORY.md` pointer. Record row. |
| **SUPERSEDED-DOCUMENTED** | The work was replaced, and the replacement is already covered by another topic file / REFERENCE. | **Delete** + cite the successor slug in the row + scrub pointer. |
| **SUPERSEDED-UNDOCUMENTED** | Replaced by shipped code, but that code is *not* well documented anywhere. | **Migrate** the load-bearing facts (paths, symbols, invariants) into the right topic/REFERENCE file *first*, then delete + scrub. The migration is the point. |
| **LIVE-REFERENCE** | The plan's "abandoned" framing is misleading — it documents code that is **live and in use**. | **Keep.** Trim the dead-plan narrative to a lean reference; drop the "unfinished" framing. **No rank.** |
| **UNFINISHED-ACTIVE** | Genuinely incomplete, and the remaining work is still wanted and still applies to the current codebase. | **Keep.** Assign a **priority rank** (below) + refresh the head's open-items list to match reality. |
| **DORMANT-REVIVABLE** | Shipped then intentionally shelved; code kept dormant for a one-line revive. | **Keep** with an `ARCHIVED (date)` banner + the revive path. **No rank.** |

Guard rail (the `bundle_stiffness` trap): **never delete a plan whose named files/symbols are
still live and wired** without first migrating what the doc uniquely explains. Grep before you
delete.

## Priority rubric (UNFINISHED-ACTIVE only)

Rank = **value × closeness × still-relevant**, mapped to one bucket:

- **P0** — high value, most of the way done, still clearly wanted → do next.
- **P1** — worth doing, non-trivial remaining work, still relevant.
- **P2** — nice-to-have, or large remaining work, or relevance softening.
- **P3** — someday/maybe; keep the doc but don't pull it forward.

Put the rank in the plan's head (`**Rank:** P1 — <one-line why>`) and in its `MEMORY.md` hook.

## How one iteration runs

See `.claude/skills/audit-plan/SKILL.md`. Short form: pick target → probe codebase (delegate
the grep sweep to a read-only, no-git subagent — it returns anchor-by-anchor alive/dead + any
superseding module) → classify → act → record row → overwrite handoff. Doc-only work; no tests
unless a migration touches code.

---

## Results (audited)

| Date | Plan | Codebase evidence | Verdict | Action |
|---|---|---|---|---|
| 07-24 | project_sequence_clear_fix | Reversal already shipped (`routes_assign_sequences.py`, pinned by `test_assign_staple_preserves_overhang_seq.py`); plan's own head says SUPERSEDED | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_advanced_staple_disabled | `optimize_staples_for_scaffold` bypassed at call site (perf); feature switched off, no resume intent | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_assembly_overhaul | "Planning — no implementation started" (2026-04-17); superseded by the shipped assembly system (`path_to_thousands`, `assembly_part_context`) | SUPERSEDED-DOCUMENTED | Deleted + pointer scrubbed (successors documented) |
| 07-24 | project_ball_joint | "Scoped only; no code yet" Phase-2 UX; `ClusterJoint.joint_type` still `Literal['revolute']` — never widened | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_blade_frontend | Already ARCHIVED 2026-07-20; modules kept dormant, one-line revive | DORMANT-REVIVABLE | Kept; banner firmed up |
| 07-25 | project_mate_connectors | Probe: create-mate route + router registered (`routes_assembly_joints.py:326`), `createMate`→`_alignAndAddJoint` single round-trip, `_defineAssemblyMate` wired to UI, blunt ends live on BOTH renderer paths. Of 4 listed defects: cache-invalidation MITIGATED (`invalidateInstance` now called after `patchOverhangRotationsBatch`, though `_sourceKey` still blind to ovhg rotation); other 3 unchanged in code. Head's "extracted, shared by both" claim STALE — legacy keeps its own ~270-line inline copy | UNFINISHED-ACTIVE | Kept; **rank P1**; head status banner + open-items rewritten against the probe; stale extraction claim corrected; no-test-pin gap recorded |
| 07-25 | project_surface_strands | Probe: anchors 1–9 EXISTS+WIRED (builder→runner→route→field-exclusion→display→UI/overlay+tests). Feature shipped 2026-07-17, not deferred. Gaps: `oxdna_design_fingerprint` omits capture state; `validate_capture_build` tests-only | UNFINISHED-ACTIVE | Kept; **rank P3**; head banner + open-items rewritten; **fixed stale MEMORY.md hook** (said "DEFERRED to Phase 2" — was shipped) |
| 07-28 | project_mixed_representation | Probe: PATH A **shipped**, not in-progress — model+`Design.representation_overrides` [models.py:1054,2275], routes moved crud.py→`routes_display_metadata.py:117/142` (registered), 13 backend tests (doc said 9), `resolveRepOverrides`+`editOverridesForSegments`, `_installInstanceAlpha`/`_applyRepOverrides`, `_applyRepresentationOverrides` (setDetailLevel re-sync intact), `_appendRepresentationMenu` ×6 sites, F-key master reset moved main.js→`ui/representation_switcher.js:256`, `initAtomSurfaceDisplay` wired at main.js:2442. UI was listed "pending" — it shipped. `editOverridesForStrands/ForClusters` named as shipped **do not exist** (column pivot replaced them). Real gaps: curved `_curvedCylGroup` + impostor beads uncovered, `iLinkerBindingCylinders` global-LOD only, no `representation_overrides.test.js`, photo mode reads overrides nowhere (+ suspected bead-`discard` bug from `_withHighDetailGeometry` swapping in `hd.bead` with no `instanceAlpha`). No superseding mechanism exists | UNFINISHED-ACTIVE | Kept; **rank P1**; head banner + code-location table rewritten, stale symbol/test-count/path claims corrected, 8-item live open-list appended; MEMORY.md hook updated |
| 07-28 | project_simulate_panel_overhaul | Probe: Phase A/B **shipped+live** (`#simulate-body`←main.js:2413, `collapsible:false` ×6 panels, `engine_selector` tabs+strip, periodic_md_panel/overlay ABSENT). Phase C **half done**: foundation `job_run_control.js` live (3 importers), oxDNA `_runControl`:1201 + NAMD `mdRunControl`:176 (always-RUN, `#md-jobs-job-ctl-btn` handler:2214) wired — but **mrDNA + CanDo entirely unstarted** (no `job_run_control` import; coarse/fine/stop trio at mrdna:202/cando:268). Master card partial: `#md-jobs-progress` GONE, but `#mrdna-jobs-progress`/`#cando-jobs-progress` still un-hidden+painted (mrdna:416, cando:603) → two bars visible; `masterStepText`:187 exported with no consumer outside its test. Doc's test paths wrong (`tests/`, not `backend/tests/`); anchors event payload richer than documented (halo reads `highlighted`). No supersession — `md_sidebar_audit` owns only NAMD's half | UNFINISHED-ACTIVE | Kept; **rank P1**; 880-line file split → lean head + `_archive.md`; head rewritten as status banner + 15-row code-location table + 7 live open items; MEMORY.md hook updated |
| 07-30 | project_dumbbell_autoscaffold | Probe: **every anchor GONE** — `rg auto_scaffold lattice.py` = 0, `seam_line` = 0 repo-wide. `_HC_SCAF_VALID`, `_expand_helices_for_seam`, `_assemble_dumbbell_path`, `_build_seam_line_domains`, `_route_standard_virt_seg`, `_scaffold_direction_from_helix_id`, `_HC_XOVER_PERIOD`, `loop_targets`, `coverage_regions`, `has_merged_seg` — zero hits each. Replaced by shape-dispatch: `auto_scaffold_seamed/_matched` (`seamed_router.py:1224/1305`), `auto_scaffold_seamless` (`seamless_router.py:111`) → `section_router.route_sections` (`:354`) gated by `has_multisection_helix` (`:77`); routes `routes_scaffold_routing.py:86/112/140`; no `mode=`/`scaffold_loops` anywhere (headless `headless_build.py:564` takes a bool `seamless`). Successor documented in `project_autoscaffold_single_strand` (dumbbell explicitly: section shape, `route_sections(seamless=)`, 6-RING known limit). Surviving valid-position set is the *different* 6-element `_HC_SCAF_BOW_RIGHT` (`seamed_router.py:40`), not the plan's 12-element set. Dumbbell tests moved+rewritten: 6 in `tests/test_section_router.py` on `tests/fixtures/10-6-10hb_seamed.nadoc` asserting coverage/gap/nick-burial — **still no assertion on crossover-bp validity or negative-bp loops**, the two things the plan was about | SUPERSEDED-DOCUMENTED (successor: `autoscaffold_single_strand`) | Deleted + pointer scrubbed. Migrated first: the *lesson* was undocumented → new **LESSONS.md H18** (5 green tests over a wrong dumbbell; wrong oracle; approach later deleted wholesale). Repointed the 2 live citations (`issues_ledger.md:253`, `tests/test_section_router.py:16`) at H18. Logged the dead-API stragglers to `project_tech_debt` (2 unrunnable scripts + auto-loaded `.claude/rules/scaffold-and-loops.md` still teaching `seam_line`) |
| 07-30 | project_scaffold_router | Probe: the CSP router the doc is named for is **entirely GONE** — no `backend/core/scaffold_router.py`, and all 15 of its symbols (`RouterDomain`, `CandidateXover`, `Routing`, `extract_router_domains`, `build_candidate_graph`, `validate_routing`, `_csp_backtrack`, `_solve_routing`, `_route_bulge`, `apply_routing_to_design`, `_domain_segment`, `max_backtracks`, `seam_tol`, `end_tol`, `preserve_manual`) have zero hits outside `memory/`. Its `POST /design/auto-scaffold` is gone (3 live routes: `routes_scaffold_routing.py:86/112/140` `-seamed/-matched/-seamless`); `tests/test_scaffold_router.py` (27 tests) gone. Its tolerance-window model (`seam_tol`/`end_tol` ±5bp) did NOT survive under another name — the live routers use exact modular residue sets (`_HC_SCAF_BOW_RIGHT` `seamed_router.py:40`) + `crossover_positions.py`. Only surviving named symbols are `HC/SQ_SCAFFOLD_CROSSOVER_OFFSETS`, which were never router-owned (`constants.py:259/285`, consumed by ~14 modules) → no rescue needed. The doc's OTHER half (Hamiltonian budget/pruning, `_ham_path_search`, `_HAM_PATH_BUDGET`, the `(len(adj[n]), n)` tiebreaker, matched-ends) is all live but is a *summary* of `project_seamless_router.md:27-31` (deeper, correct line anchors, 2026-07-13 resolution) + `project_autoscaffold_single_strand.md` (matched-ends, ragged faces, P). Zero inbound citations from code/tests/`.claude/` | SUPERSEDED-DOCUMENTED (successors: `seamless_router` + `autoscaffold_single_strand`) | Deleted + pointer scrubbed. Migrated first: the **matched-ends far-crossover-LEFT rule** (user rule 2026-06-02) lived only here as prose → moved into `project_autoscaffold_single_strand` (far−near ∈ {P, P-1}, bow-right step, no-circle + ragged-face corrections, pinned by `test_seamed_router.py:60`). Repointed 2 inbound wikilinks (`project_headless_build.md:264`, `exp40 ASYMMETRIC_SCAFFOLD_HANDOFF.md:55`) at the successors. Logged new dead-API stragglers to `project_tech_debt`: 4 E2E specs POST the removed `/design/auto-scaffold` (404 at runtime), `autoScaffoldMatched()` orphaned in 2 client files, stale mode list in `autoscaffold_picker.js:2` |
| 07-30 | `.claude/rules/scaffold-and-loops.md` (off-taxonomy: path-scoped rule, no verdict) | Probe of all ~55 anchors. **Dead:** all 6 `lattice.py` routing symbols (`auto_scaffold`, `compute_scaffold_routing`, `_build_seam_line_domains`, `_build_end_to_end_domains`, `_helix_adjacency_graph`, `_greedy_hamiltonian_path`), the `seam_line`/`end_to_end` mode concept, `compute_loop_skip_deformations` (0 hits repo-wide), 4 of 12 documented routes (`/design/auto-scaffold`, `-scaffold-nick`, `-extrude-near`, `-extrude-far`), `tests/test_scaffold_geometry.py`, `MAP_SCAFFOLD_ROUTING.md`. **Wrong-not-dead:** hotkey table off-by-one from `[4]` on + `[2]`/`[7]` wrong outright (actual: 1 Autoscaffold / 2 Full Autostaple / 4 Add Loops-Skips / 5 scaffold seq / 6 staple seq; 7 unbound; two binding sites `cadnano-editor/main.js:1436` + `keyboard_shortcuts.js:392`); `LoopSkip.delta` is plain `int`, **not** `Literal[-1,+1]` (no type-level guard); `ROUTING_ENTRY_POINTS` is in `tests/test_scaffold_invariants.py:53`, not `scaffold_invariants.py`; validator string is `location(s)`; seam window is `_SEAM_BP_WINDOW=1` w/ `seam_margin` 7/8. **Moved by carve-up:** `full_autostaple_endpoint`+`_linearize_staple_precursors` crud.py→`routes_assign_sequences.py:346/216`; 5 of 7 loop-skip routes crud.py→`routes_loop_skip.py` (but `apply-deformations`/`clear-all` stayed). **Still-true:** the entire autostaple half (`nick_all_major_ticks`/`grow_staples`/`_has_sandwich`/anti-sandwich/56-cap) + `auto_crossover`/`_place_auto_crossovers`/`_desplice_strands_for_crossover` in crud.py. **Structural defect found independently:** frontmatter globs (`scaffold*.py`, `seamless*.py`, `loop_skip*.py`) never matched `seamed_router.py` or `section_router.py` — the rule failed to auto-load on the primary router file it exists to describe | REWRITTEN (n/a — rule, not plan) | Full rewrite against the probe: 3-router table w/ line anchors, corrected hotkeys, per-route file column, `_ham_path_search`/`_HC_SCAF_BOW_RIGHT` map, `CELLS_*`-are-not-shared warning, and a **"Removed API — do not resurrect"** block naming every dead symbol. Globs widened to all 3 routers + both route files. Struck the entry from `project_tech_debt`; logged 1 new debt item (`CELLS_6HB`/`CELLS_18HB` copy-pasted with divergent cell lists across 9 files). No `MEMORY.md` edit (rules are listed by name only; name unchanged) |
| 07-30 | project_protein_attachment | Probe: feature **ships end-to-end**. Routes carved out of crud.py → `routes_protein.py` (9 routes, registered `main.py:272`); only `pdb-auto` + `_import_protein_free` stayed in `crud.py:1771/1843`. Frontend closure extracted → `scene/protein_subsystem.js` (renderer+gizmo+**store-driven** refresh, `:76-81`) — main.js keeps 1 redundant ad-hoc call. Of the 2 "NOT built" items, **one shipped**: conjugation-atom picking is a 563-LOC Conjugate Manager (3D marker picking) + `backend/core/conjugation.py` SASA candidates + `POST /design/protein/conjugate` + 5th op kind `protein-conjugate` — all undocumented here. `infer_bonds_by_distance` (doc: "Phase 4, not written") is built AND called (`atomistic.py:1197`). Tests 36 not 28 (+7 conjugation, +5 vitest). Only Phase 3 (assembly) truly unbuilt — `kind=="assembly"` explicitly skipped `routes_protein.py:132`, zero `protein` hits across all assembly modules front+back. Stale claims both directions: `menu-file-import-protein` gone (correct), `test_delete_earlier_protein_import_lists_dependent` renamed+inverted, discriminator is `"overhang"` not `"design"`, gotcha "no auto-refresh on design load" fixed by the subsystem extraction | UNFINISHED-ACTIVE | Kept; **rank P2**; 89-line work-log head split → lean head + `_archive.md`; head rewritten as status banner + 20-row code-location table + 5 live open items; **migrated in** the undocumented conjugation subsystem; cross-linked MD side to `proteins_in_simulation`; MEMORY.md hook updated. New code defects recorded as open items (not tech_debt — the plan owns them): `ProteinAsset.bonds` never populated (`protein.py:191` hard-codes `[]` → bond-free preview render), `Assembly.protein_*` are orphaned serialized slots, `routes_protein.py:97` docstring promises a fallback the code removed |
| 07-30 | `.claude/rules/cadnano-2d.md` (off-taxonomy: path-scoped rule, no verdict) | **Frontmatter triage of all 9 unaudited rules first** (see handoff table). Worst: `cadnano-2d`'s glob `frontend/src/cadnano/**/*.js` matches **zero files** — that path has never existed; the real dir is `frontend/src/cadnano-editor/`. Body probe of ~40 anchors: **Moved** — init site `main.js:878`→`:1542`; reapply subscriber `~952`→`:2499` (+ a **second, undocumented** compensator at `:2517` on `straightGeometry`); K/U bindings now `ui/keyboard_shortcuts.js:259-271` via injected deps (`main.js:4510`). **Renamed/gone** — `scene/blunt_ends.js`→`scene/domain_ends.js` (and its `reapplyIfActive` grew a *positive* `_lastCadnanoParams` re-apply branch the rule never had); `_clearSliceHighlights()`→`sliceHighlighter.clear()`; `_helixCtrl.clearFemColors()` gone. **Whole narrative dead** — the "Known culprit (fixed 2026-04-01) FEM clear-stale-results subscriber at main.js:2475" no longer exists, and `clearFemOverlay()` now has **zero callers**. **Wrong-not-dead** — init signature is 8 params not 7 (undocumented vestigial `_getCrossoverLocations`, always `null`); `captureCurrentCamera` listed as required but never called; `_restoreSideEffects()` is *also* a no-op (rule implies it works); ortho frustum is `fh = 2·dist·tan(fov/2)` (full height), no `halfH` at construction; `reapplyPositions()` list omitted the `_computeCadnanoPosMap()` recompute + empty-map abort. **Still-true** — merge-only `_unfoldPosMap` verbatim (incl. `__xb_`/`__ext_` skips), glow `refreshAllGlow()` invariant, 250 ms two-stage anim, YZ skip quats, `keepUnfold`, ortho shift-right capture fix, all 3 cross-feature guards. **Undocumented finds** — atomistic-mode entry block (`main.js:2614`), `end_extrude_arrows.js:382` cadnano-Z override, the 12-module `cadnanoActive` consumer list, **zero unit tests for `cadnano_view.js`** (and neither `e2e/cadnano_*.spec.js` covers this mode — one tests the importer, one the *editor*) | REWRITTEN (n/a — rule, not plan) | Full rewrite: dead glob dropped, `loop_skip_highlight.js` added (was matched by **no** rule); file table w/ line anchors, corrected 8-arg signature, 10-step `reapplyPositions`, both subscribers, honest "there are no tests" section, and a **"Removed API — do not resurrect"** block (7 dead names). Scope banner added disambiguating this K-key view mode from the separate `cadnano-editor/` app. 5 code stragglers → `project_tech_debt` (dead `clearFemOverlay`, duplicated `PERSP_FOV_DEG=55`, vestigial init param, editor's 1.7% test coverage, and `ui/overhang_pathview.js` importing the editor's layout+palette constants — a three-way invariant w/ `constants.py` + `helix_renderer.js`). No `MEMORY.md` edit (rules listed by name; name unchanged) |
| 07-25 | project_mate_connectors | Probe: ALL implemented anchors EXIST+WIRED (create_mate→route, _propagate_fk_inplace/_compose_add_joint shared, `assembly-create-mate` in SnapshotOpKind, shared+legacy `getInstanceBluntEnds` both live, no `()=>[]` stub). Feature ships. Locations drifted (routes_assembly_joints/geometry.py, scene/, ui/overhang_orientation_panel.js). 1 of 4 "known issues" (cache invalidation) FIXED — `_ooApplyDelta` now calls `invalidateInstance`+`rebuild`; 3 connector-placement bugs survive | UNFINISHED-ACTIVE | Kept; **rank P2**; head banner + relocations + open-items rewritten (cache issue struck as RESOLVED); MEMORY.md hook updated |

## HOLD — flagged to user, decision pending

- **project_bundle_stiffness_params** — user said "delete", but the 0T track is a **completed,
  live parameter DB** (`backend/data/parameters/bundle_stiffness.json`) and this file is the
  only prose for its schema/units/provenance. Provisional verdict **LIVE-REFERENCE** (trim to a
  0T reference, drop the abandoned-1T narrative), NOT delete. Awaiting user OK.
- **project_periodic_md** — user said "archive pending revival", but the **backend workflow
  (`periodic_cell.py`, `namd_solvate.py`) is live**; only the frontend previewer was removed
  (already noted in-file, 2026-07-08). Provisional verdict **LIVE-REFERENCE**, NOT archive.
  Awaiting user OK.

## Audit queue (unaudited — rough priority top-first)

Genuinely-unfinished-with-intent candidates (likely UNFINISHED-ACTIVE, need rank):
- project_regional_autorefine, project_deformation_cluster_scope,
  project_cadnano_overhaul, project_assembly_part_context, memory/trajectory_keyframes —
  Phase-1-shipped, later-phase-deferred (rank each)

Small-tail / verify-if-superseded:
- project_overhang_sequence_display (caveat),
  project_assembly_groups (Escape not wired), project_ux_overhaul (deferred flow work),
  memory/pipeline_validation_log (NOT YET VALIDATED), photo_mode_audit_plan (root),
  memory/project_overhang_duplex_foundation (bulges deferred)

Ongoing loop-drivers — **out of scope, do not audit** (they're never "done" by design):
backend_router_carveup, main_js_carveup, design_automation_backlog, issues_ledger,
manual_validation_debt, SIM_COVERAGE_PLAN, project_cando_fem, project_atomistic_propagator.

## Path-scoped rule sweep — frontmatter triage (done 2026-07-30, reuse it)

Glob-vs-`ls` check of all 9 unaudited rules. **Don't re-run this; it's the ranking.**

| Rule | Frontmatter verdict |
|---|---|
| ~~`cadnano-2d`~~ | **REWRITTEN this pass.** Glob `frontend/src/cadnano/**/*.js` matched **zero files** |
| `selection` | ⚠️ single glob `scene/selection_manager.js`; **misses** `scene/selection_bbox.js`, `scene/selection_level.js`, `ui/selection_filter.js` — all extracted siblings |
| `animation` | ⚠️ `backend/api/animation*.py` matches **zero files**; also misses `scene/animation_text_overlay.js` |
| `api-and-state`, `rendering`, `deformation`, `main-init`, `unfold`, `strand-anim` | globs all resolve; no structural tell (body still unaudited) |

**Do not widen a stale rule's globs without auditing its body** — that just auto-loads wrong guidance
onto *more* files. Glob fix and body rewrite go together, in one pass, per rule.

## Next-session handoff

▶ **NEXT: write a new `.claude/rules/cadnano-editor.md`.** This pass's probe found the largest
documentation hole in the repo: `frontend/src/cadnano-editor/` is **10,713 LOC** — a second Vite app
(`frontend/cadnano-editor.html`, entry `vite.config.js:30`, own `editorStore`, own `api.js`, reached by
`window.open` from `main.js:4223/7875`) — with **zero `.claude/` coverage** (the only mention repo-wide is
one line anchor in `scaffold-and-loops.md:29`) and ~1.7% unit-test coverage. `pathview.js` alone is 4977 LOC,
the second-largest JS file after `main.js`. Its smaller sibling sandbox app `strand-anim` already has a rule.

It is **architecturally disjoint** from `scene/cadnano_view.js` (probe was definitive: they share no module
and neither imports the other) — one rule cannot cover both, and the rewritten `cadnano-2d.md` now says so.

Probe evidence is already gathered — **do not re-probe from scratch**; the rule needs to carry:
globs `frontend/src/cadnano-editor/**/*.js` + `frontend/cadnano-editor.html`; the separate-app model
(own store explicitly NOT shared — `cadnano-editor/store.js:4`; cross-tab sync = BroadcastChannel via
`shared/broadcast.js` + backend-as-ground-truth; `shared/doc_id.js:16` branches on the pathname); the
13-file map (`pathview.js` 4977 / `main.js` 2554 / `api.js` 724 / `strands_spreadsheet.js` 657 /
`sliceview.js` 631 / `ligation_debug.js` 433 / `zoom_scope.js` / `element_keys.js` / `store.js` /
`sequence_layout.js` / `pathview/palette.js`); the **reverse-coupling trap** (`ui/overhang_pathview.js:32-54`
imports the editor's `BP_W/CELL_H/PAIR_Y/GUTTER` + 15 `CLR_*` — palette is a three-way invariant with
`backend/core/constants.py` `STAPLE_PALETTE` and `scene/helix_renderer.js`); the **element-key codec law**
(bp indices **can be negative** — `\d+`-only regexes silently no-op; this bug has been fixed twice, see
`project_cadnano_resize.md`); the backend surface (**no dedicated router** — shared `crud.py` etc.; only
`/design/helix-at-cell` and `/design/scaffold-domain-paint` are editor-specific, pinned by
`tests/test_cadnano_editor_api.py`, now **25** tests; conventions `X-NADOC-Skip-Geometry: 1` on undo/redo
and `docHeaders()` doc-scoping on every call); and the hotkey table (`R` cycle tool, `N`/`P` nick/paint with
`P`-again nudging colour, `1/2/4/5/6` scaffold+staple actions at `main.js:1436-1442`, `Tab` filter cycle,
`Ctrl+Shift+D`/`Ctrl+Shift+L` debug panels, pathview-local `Escape`/`Shift`-ghost/`D`/`Delete`).
Do **not** absorb `project_cadnano_overhaul.md`'s Phase 3–5 planning content — that's a separate audit target.

Then continue the rule sweep at **`selection`** or **`animation`** (both have a structural tell, table above),
and only after that resume the plan queue at **`project_regional_autorefine`** (queue top).
Also newly visible: **`project_cadnano_overhaul.md`** is stale as an architecture map (last dev-log entry
2026-05-25; code last touched 2026-07-28; its "Remaining Work" gate still says "confirm all 17 API tests pass"
when there are 25) — it is already queued, and the ranking should reflect that it is a *plan*, not a map.

*New this pass (cadnano-2d) — the frontmatter triage works, and it is nearly free.* Nine rules, one
`awk` over the frontmatter plus one `ls`, and it ranked them correctly on the first try: the rule with the
zero-match glob was also the rule whose body was most wrong. **Run the triage table above before choosing a
rule to rewrite** — and note what a zero-match glob actually means. It is not "a file got renamed"; it means
**the rule never loaded on the code it describes, for its entire life**, so nothing has ever corrected it.
That is why the glob defect predicts body rot rather than merely accompanying it.

*Also new — a rule can be wrong about an entire causal story, not just a symbol.* The worst thing in
`cadnano-2d` wasn't a moved path; it was a 15-line "Known culprit (fixed 2026-04-01)" section prescribing a
guard against a **subscriber that no longer exists**, in a function (`clearFemOverlay`) that now has **zero
callers**. Deleted-symbol checks don't catch this — every name in the section still resolved; only the
*wiring* was gone. When a rule explains WHY something is done, probe the call graph, not just the identifiers.
Corollary reinforced twice now: the "Removed API — do not resurrect" block is the highest-value part of a
rewrite. Also: **state test coverage honestly and by name.** `cadnano_view.js` has *no* unit test, and the two
`e2e/cadnano_*.spec.js` files sound like they cover it but cover the importer and the *separate editor app* —
a filename that implies coverage it doesn't provide is worse than no test at all.

*New this pass — audit the path-scoped rules, not just the plans.* A stale `project_*.md` costs a session
only when someone opens it. A stale `.claude/rules/*.md` is **auto-loaded**, so it teaches every session
that touches the area, unprompted — strictly worse decay for the same rot. This one had ~55 anchors and was
wrong in four distinct ways at once: symbols deleted (all 6 `lattice.py` routing fns), symbols *moved* by the
carve-ups (crud.py → `routes_assign_sequences.py` / `routes_loop_skip.py`), facts that were never true or
drifted silently (hotkeys off-by-one from `[4]`; `LoopSkip.delta` documented as `Literal[-1,+1]` when it is an
unconstrained `int` — a doc that promises a guard the model doesn't have is worse than silence), and a
**structural** defect no anchor-by-anchor check would have caught: its `paths:` globs never matched
`seamed_router.py`/`section_router.py`, so the rule silently failed to load on the one file it most describes.
Check the frontmatter, not only the body. Corollary for rewrites: end a rule with an explicit **"Removed API —
do not resurrect"** block. The deleted names outlive the code in scripts, e2e specs, and older memory files,
so a session will meet them again; naming them as dead is what stops the next re-derivation.

*Pattern from the two preceding passes (kept — still load-bearing):* a plan that has outlived its subject
splits into a **dead half** and a **still-true half that belongs to a younger doc**; probe the halves
separately, and "some of this is still true" is not a reason to keep the file. Before any delete, grep the
head for "user rule / user decision / user accepted" — a user decision whose signature looks like a bug
(the matched-ends `far−near ∈ {P, P-1}` off-by-one) is the highest-risk thing to lose. Every pass so far has
also turned up **stale non-plan artifacts** the doc was innocent of (dead-API scripts, e2e specs POSTing a
removed route, `CELLS_6HB` copy-pasted with divergent geometry) — those go to `project_tech_debt`.

*Pattern worth carrying (4 for 4 among the KEPT plans — `surface_strands`, `mate_connectors`,
`mixed_representation`, `simulate_panel_overhaul`):* the plan's own status text is stale in **both** directions.
`mixed_representation` claimed "UI pending" (it shipped) *and* claimed two shipped helpers that no
longer exist; `simulate_panel_overhaul`'s newest block claimed four progress bars were all still
rendered-but-hidden — NAMD's was deleted and mrDNA's/CanDo's are *visible*. Diff every head claim
against the probe line-by-line; never trust the top-line banner. Corollary: probes keep finding
**paths** moved by the carve-ups (crud.py → routes_*, main.js → ui/*) and **test paths** that were
never right — a code-location table in the head is worth more than the prose around it.

*New this pass:* a plan whose head has grown into a reverse-chronological work log (880 lines here)
should be **split head/archive as part of the audit** — the rank and the live open-items list are
unreadable buried under 40 dated ⚡ blocks. Splitting is mechanical and is the audit's deliverable
as much as the verdict is.

*New this pass (protein_attachment) — the "remaining work" list is the least trustworthy part of a head.*
Both of this plan's two `## Remaining (NOT built)` bullets were wrong in the same direction the banner was:
one had shipped as a **563-LOC subsystem with its own backend module, route, undo op-kind and tests**, and a
helper the doc called "not yet written" was built *and* on a live call path. A feature can outgrow its plan
without anyone editing the plan — so **probe the NOT-built list first**, before the shipped list; it's where
a stale doc most actively misleads (it invites you to rebuild something that exists). Corollary: when a probe
finds a whole undocumented subsystem, the audit's real deliverable is **migrating it into the head**, not the
verdict. Also new: this pass's genuine findings were **code defects, not doc defects** (a declared-and-consumed
field that is never populated; a serialized model slot with no producer; a docstring promising behaviour the
function removed) — a good probe audits the code as a side effect, so give those a home (open item or
`project_tech_debt`) instead of dropping them.

**Standing HOLDs (user-owned decision, do not touch):** `project_bundle_stiffness_params`,
`project_periodic_md` — both LIVE-REFERENCE, parked in the HOLD block above.
