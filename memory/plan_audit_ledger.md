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
| 07-30 | `.claude/rules/cadnano-editor.md` (off-taxonomy: **new** path-scoped rule, no verdict) | The repo's largest documentation hole, filled. `frontend/src/cadnano-editor/` = **10,713 LOC / 13 files**, a second Vite app (`vite.config.js:30`, entry `cadnano-editor.html:1723`), with **zero `.claude/` coverage** before this pass. Probe corrected 5 handoff claims: the file list is 13 not 13-with-different-sizes (`element_keys.test.js`/`sequence_layout.test.js` are 2 of the 13); `store.js`'s not-shared line is **:5** not :4; hotkey **`3` is NOT bound** (folded into `2`; comment :1437-1438) while `F`/`?`/`F1`/`S`/`Backspace`/`Space`/`Ctrl+O`/`Ctrl+S`/`Ctrl+Shift+S`/`Ctrl+Y` are and weren't listed; `Ctrl+Shift+L` lives in `ligation_debug.js:403` not `main.js`; and the palette's third copy is `scene/helix_renderer/**palette.js**:23-26`, **not** `helix_renderer.js` (which only imports it :33). Element-key law CONFIRMED and already correctly implemented — all 4 regexes use `-?\d+` (`element_keys.js:79-82`), header :6-11 cites ISSUE-7, and a full-frontend sweep found **zero `\d+`-only offenders**. New load-bearing finds the handoff didn't have: the stale-response **revision watermark** (`api.js:24-56`, `_lastAppliedRev`; `resetRevisionWatermark()` must fire on backend restart or the editor freezes), the **mutations-must-go-through-`mutate()`** law and its documented failure (`api.js:655-660` — bare fetch → wrong doc → "Feature index N out of range"), `doc_id.js:16/28` **editor tabs never mint a doc id** (fall back to `__default__`), per-strand-id staple-colour pinning (`palette.js:91-102`), the periodic auto-shift user law (`pathview.js:4930-4944`), negative-bp handling in `_fitToContent` (:882-889), `pathview` is **render-only** (imports no `api.js`; 24 `on*` callbacks), and `update()` clearing selection. Tests: **25** backend (`test_cadnano_editor_api.py`, 3 classes), **2** vitest files = 176 of 10,512 production LOC (**1.6%**); `cadnano_crosssection.spec.js` does **not** touch this app | NEW RULE (n/a — rule, not plan) | Wrote `.claude/rules/cadnano-editor.md`: globs `cadnano-editor/**` + the HTML + both `shared/` sync modules; 13-file map w/ LOC + entry points, separate-app model, doc-scoping asymmetry, full backend surface (2 editor-only routes in `crud.py:1964/2315`, no dedicated router) + both header conventions, element-key codec law, geometry/layout w/ the bp→x cell-boundary convention, 8 invariants, the reverse-coupling trap, corrected hotkey table, honest coverage section, "Removed API" block. Cross-linked from `cadnano-2d.md`. **7 code defects → `project_tech_debt`**, incl. a *new* palette entry: a **4th, divergent** `STAPLE_PALETTE` in `ui/spreadsheet.js:54-60` (3D spreadsheet paints strands differently from the canvas) + all 3 sync-pointer comments naming files that no longer hold the constant. MEMORY.md rule list updated (one edit) |
| 07-30 | `.claude/rules/animation.md` (off-taxonomy: path-scoped rule, no verdict) | Probe of ~50 anchors. **Third zero-match glob, third rotten body** — `backend/api/animation*.py` has never existed. **Whole feature never existed:** Phase 3 "Configurations 🔴 needs debugging" described a *design-scoped* config system — `DesignConfiguration`, `ClusterConfigEntry`, `/design/configurations`, `POST …/go-to`, `api.goToConfiguration`, `Design.configurations`, `ui/config_panel.js`/`initConfigPanel`, `update_configuration`: **zero hits each, repo-wide**. Configurations shipped **assembly-scoped** (`AssemblyConfigurationSnapshot` `models.py:1291`, `routes_assembly_configs.py`, 10+ `.nass` files carry them, 3 tests) and are in production use. **Signature drift:** `initAnimationPlayer` takes **23 deps**, not the documented 5 (`deformView`/`getConfigPanel` don't exist; `designRenderer`→`getDesignRenderer`); `initAnimationPanel` 9 deps not 2; only `initCameraPanel` was right. **Init sites wrong on every count** — real: player `main.js:1561`, camera `:6357`, panel `:6714` (spread over 5000 lines, not "~3507–3530 after clusterGizmo"; `initClusterGizmo` is `:4614`). **Routes all moved** crud.py→`routes_camera_poses.py`/`routes_animations.py` (+ a `keyframes/reorder` PUT the rule lacked); the 3 display-pose/strand-anim-setup PATCHes stayed in `crud.py:7850/8828/8867`. **`AnimationKeyframe` has 27 fields**, not "{id, config_id?, camera_pose_id?, …}" — and field is `configuration_id`. Four whole undocumented features: trajectory keyframes, text overlays, spin keyframes, the pre-bake pipeline (`routes_feature_log.py:112/138/168` — which is also the real answer to bug-suspect #5). **`_restoreBaseClusters` is on the PLAYER** (`animation_player.js:688`), not the renderer, and contains **no slerp** (identity quat, `dummy===center`) — suspect #2 diagnosed math that isn't there. Suspect #4 already resolved (`set_assembly_silent` at `routes_assembly_configs.py:212/240/288`). **9 animation files matched by NO rule glob anywhere**, incl. 3 the rule *names in its body* (`camera_panel.js`, `export_video.js`, `overhang_unzip_overlay.js`). Banner (strand-anim, 2026-05-29) was the **most accurate section** — every anchor live+wired — but overstated one thing: `buildStrandGeometry` is sandbox-only (`app.js:42`); the editor imports `createStrandRenderer` only. Undocumented 2nd overhang path found: `strand_anim_phi`→`overhang_strand_anim.js` (711 LOC), disjoint beads from the `binding_states` overlay | REWRITTEN (n/a — rule, not plan) | Full rewrite: 3 globs → 16 (all 9 uncovered files + the 5 real backend route files); file map w/ LOC + init line numbers, 23-dep player signature + internals table, corrected 27-field model list, 18-row route table w/ registration lines, both overhang paths documented side-by-side, honest coverage section (**~2900 LOC with zero tests, zero e2e**), and a **"Removed API — do not resurrect"** block naming the 8 phantom design-config symbols. Phase-3 bug-suspects section deleted from the rule (it duplicated the runbook — `CLAUDE.md` forbids). **`RUNBOOK_ANIMATION.md` rewritten too**: all 5 suspects + all 4 diagnosis trees named dead symbols; replaced with real symptom→diagnosis incl. the design-vs-assembly-mode first question. Fixed `memory/REFERENCE_MODELS.md:25` (`Design.configurations` phantom field). 4 stragglers → `project_tech_debt` (`docs/triage/05_animation.md` is 193 lines of fiction + 11 unaudited siblings; the ~2900-LOC test hole; `captureClusterBase`'s two incompatible signatures). No `MEMORY.md` edit (rules listed by name; name unchanged) |
| 07-30 | `.claude/rules/selection.md` (off-taxonomy: path-scoped rule, no verdict) | **Narrow-glob tell confirmed — 4 for 4.** Single glob `scene/selection_manager.js` missed 3 extracted siblings; body probe of ~60 anchors. **Dangling** — `MAP_SELECTION.md` (the "Related" link) has **never existed** anywhere in the repo. **Mechanically wrong** — the `deformToolActive` invariant claims "main.js blocks canvas events"; the real mechanism is a subscriber (`main.js:4318-4335`) that saves `_savedSelectableTypes` and **zeroes every `selectableTypes` flag** — events still arrive, every capture filter returns false. There is no capture-phase interception on this path, and `isDisabled` (`main.js:982`) doesn't check `deformToolActive` at all (it's `slicePlane.isContinuation() \|\| forceXoverActive`). `RUNBOOK_SELECTION.md:17,51` repeated the same error. **Undercounted** — opts documented 8 of **26** (missing `isDisabled`/`getCamera`/`onDrillLevel` + all 11 right-click callbacks; the in-file JSDoc `:1647` is stale the same way); returned API 19 methods, 2 documented; `selectableTypes` 8 of **11** fields (missing `clusters`, `crossoverArcs`, and `overhangs` — the last is required by the rule's OWN overhang-precedence text); `selectedObject.type` 3 of **10** real values across 85 assignment sites (`store.js:69` carries the same stale triple); `multiSelectedOverhangIds` undocumented. **Line-wrong** — init site `main.js:~175`→**:820**. **Still-true** — the whole selection-level model verbatim (`LEVELS`, `TAB_CYCLE` w/ cluster excluded, `_v2Handle*`, no-fallback fixed levels), all arc/preview constants (`PREVIEW_ARC_RADIUS`=0.147, 12 radial segs, DoubleSide, depthTest:false, `0xffe000`, `_NEAR_HOVER_PX`=80), the full `_toggleAtLevel`/`_promoteSelectionToMulti` 5-branch description, `lassoCaptureType` precedence, Shift-alias/Shift-drag-noop, `_effectiveColors`. Deleted-API note **verified dead** (`_autoDrill*`/`_drillLock`/`_manualFilters`/`NADOC_DRILL_V2` = 0 frontend hits). **Undocumented finds** — Tab/Esc live in `ui/keyboard_shortcuts.js:285/707` not main.js; `#select-filter` is **static markup** (`index.html:6255-6298`), JS only wires it; right-click has largely LEFT selection_manager (7 menu-owning modules + 4 rival canvas contextmenu listeners, one capture-phase); `_ctrlBeads` is closure-scoped not module-scoped; `_toggleClusterById`; `beadLevel` is a dead hard-coded `false`; `toolFilters` is on the **`ui`** subscriber channel, not `selection`; isolate mode (`isolatedStrandId`, 7 consumers) has no doc anywhere. **Coverage** — `selection_manager.js` is **4179 LOC with zero unit tests**; the 3 pure siblings carry all 65 | REWRITTEN (n/a — rule, not plan) | Full rewrite: globs 1→**10** (3 siblings + 4 menu owners + measurement + keyboard_shortcuts); file map w/ LOC+tests, full 26-opt + 19-method surface, corrected store table (11 flags, 10 types, 4 pools + channel split), 6 corrected invariants, a **"Traps — code comments that contradict the code"** section (4 sites, so nobody "fixes" the code to match), honest zero-test section, and a **"Removed API — do not resurrect"** block (8 dead names incl. the phantom `MAP_SELECTION.md`). **`RUNBOOK_SELECTION.md` rewritten too** — its worked example used `_handleExtrude` (**never existed**), `_bluntInfo` (dead) and `_pendingEntry` (moved to `main.js:1117`), and its measurement tree still said Ctrl+click 14 months after it became Alt+click; replaced with a 9-symptom index. Fixed off-rule rot: `memory/project_mixed_representation.md` still described `_autoDrill*`/`_drillLock` as live in 7 places → dated terminology banner added. **7 code defects → `project_tech_debt`** (the 4179-LOC test hole, 4 contradicting comments, the incomplete deform `setState`, dead `beadLevel`, ~40 uncovered modules incl. **`state/store.js` — the whole-app store has no rule coverage**, and undocumented isolate mode). No `MEMORY.md` edit (rules listed by name; name unchanged) |
| 07-30 | **Coverage sweep** (all 11 rules) + `.claude/rules/api-and-state.md` (off-taxonomy: path-scoped rule, no verdict) | **Sweep first (the new metric):** matched every prod `.py`/`.js` under `frontend/src`+`backend` against all 11 rules' `paths:` globs → **205,091 of 306,950 LOC (67%) covered by nothing**. Uncovered by dir: `backend/core` **91k** · `ui` **53k** · `scene` **38k** · `physics` 11.7k. Worst individual holes: `lattice.py` 4923 (**holds the LOCKED `_PHASE_*` constants**), `models.py` 3314 (the `Design` schema), the ~10k-LOC assembly render stack. **Then the rule.** `api-and-state` is the *widest* glob (82 files/50.7k LOC auto-loaded) and described ~13% of it. **The model itself was wrong, not just the symbols:** the rule + runbook are built on `_active_design` and a module-level `_history` — **neither exists**; state is per-document (`_sessions: dict[str,_DesignSession]` [state.py:87], `X-NADOC-Doc` header → `doc_context.get_current_doc()`:72, `_DesignSession.history` :77). **Route index rotted to unusability:** 84 entries vs **567 live routes** (13%), **10 dead** — confirmed `POST /design/auto-scaffold` (→3 suffixed routes), `scaffold-nick`, `-extrude-near`, `-extrude-far`, the whole `/design/configurations` group (moved to `/assembly/configurations`), **plus 2 the handoff didn't predict**: `POST /design/prebreak` and `PATCH /design/extensions/{id}` (no PATCH decorator exists). 493 live routes missing incl. every assembly/MD/oxDNA/SNUPI/CanDo/mrDNA/BLADE/protein/feature-log route + all of `ws.py`; index also omits that **all 62 routers mount at `/api`**. **API undercount, again:** `state.py` has **35 public functions**, rule named 6 (20%) — and the omitted `mutate_with_reconcile`:264 is **mandatory** for cluster-scope topology mutations, contradicting the runbook's "`mutate_and_validate` is the ONLY correct way" → following the runbook silently skips `reconcile_cluster_membership`. `assembly_state.py` (726, full parallel undo + diff snapshots), `session_cache.py`, `doc_context.py` all inside the glob, unmentioned. `_request` is 4-arg not 3; `_syncFromDesignResponse` writes **10** store keys and is gated by a **revision watermark** the rule never mentioned; response shape omitted `revision` + `unligated_crossover_ids`. `MAP_API_FLOW.md` (the "Related" link) **never existed** — the rule was its only mention repo-wide. Runbook :43-45 ("no automatic persistence, state lost on restart") **false on both halves** — `session_cache` restores on boot, `persistDesign()` writes localStorage per doc; and restore-on-boot means **a restart may not clear stale state**, weakening the rule's flagship advice. `store.js`: 541 LOC, 53 keys, **7** slices, 31 importers, **zero tests**; its own `subscribeSlice` JSDoc :460 omits the live `assembly` slice | REWRITTEN (n/a — rule, not plan) | Full rewrite. **Deleted the route index outright** — replaced with a "Finding a route" recipe (`rg` patterns + the `/api` prefix law) + a 7-family router map over the 63 `routes_*.py`; an enumeration at 13% coverage is worse than none. Added the per-doc session model, a **mutation-contract decision table** (which `mutate_*` for which situation, with the cluster-reconcile trap), corrected client/response/store sections, 6 invariants, a **Traps** section (the store JSDoc), honest coverage, and a **"Removed API — do not resurrect"** block (13 dead names/routes). **Glob widened to `frontend/src/state/**/*.js`** — closes the `store.js` hole the last pass flagged. **`RUNBOOK_API.md` rewritten** (50→9-symptom index): the doc-id-vs-stale-state first question, the watermark, the reconcile trap, the persistence correction. **2 tech_debt entries**: the 67% coverage sweep w/ candidate new rules, and `api-and-state` stragglers (`_design_response` imported by 34 modules keeps `crud.py` structurally central; store.js zero tests; the JSDoc trap; the bug-causing runbook line). No `MEMORY.md` edit (rules listed by name; name unchanged) |
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
| ~~`cadnano-2d`~~ | **REWRITTEN 07-30.** Glob `frontend/src/cadnano/**/*.js` matched **zero files** |
| ~~`cadnano-editor`~~ | **NEW 07-30** — 10,713 LOC that no rule covered at all |
| ~~`animation`~~ | **REWRITTEN 07-30.** `backend/api/animation*.py` matched **zero files**; body described a feature that never shipped |
| ~~`selection`~~ | **REWRITTEN 07-30.** Single glob missed 3 extracted siblings; body had a dangling `MAP_SELECTION.md`, a mechanically wrong deform gate, and 4 undercounted API surfaces |
| ~~`api-and-state`~~ | **REWRITTEN 07-30.** Globs resolved fine — the *body* was built on two symbols that don't exist, and its route index covered 13% of the API with 10 dead entries |
| `rendering`, `deformation`, `main-init`, `unfold`, `strand-anim` | globs all resolve; no structural tell (body still unaudited) |

**Do not widen a stale rule's globs without auditing its body** — that just auto-loads wrong guidance
onto *more* files. Glob fix and body rewrite go together, in one pass, per rule.

## Next-session handoff

▶ **NEXT: `.claude/rules/main-init.md`.** Of the 5 remaining unaudited rules (`rendering`,
`deformation`, `main-init`, `unfold`, `strand-anim`) this one has the highest expected rot **and**
the highest blast radius: its single glob is `frontend/src/main.js`, a file that is *actively being
shrunk* by the carve-up loop (16.5k → 8,059 LOC today), so **every line anchor in it drifts on every
extraction**. It is also the only rule `CLAUDE.md` sends sessions to by name ("the streamlined
extraction-loop in `.claude/rules/main-init.md`") — a stale extraction loop damages the carve-up
directly. Probe: (a) does its extraction-loop procedure match what `/carve-router` and the
`main_js_carveup` ledger actually do now; (b) every `main.js:NNNN` anchor (this pass already found
5 wrong ones in `animation.md` alone); (c) count the init calls in `main.js` vs the doc; (d) the
verbatim-vs-adapted pin rule from `CLAUDE.md` — is it stated there? Then `rendering.md`
(5 files / 8.4k LOC, `design_renderer` + `helix_renderer` — the files `mixed_representation` P1 says
have uncovered curved/impostor paths).

**The coverage sweep is done — don't re-run it, use it.** Full numbers + method in
`project_tech_debt` → "Rule coverage is 33% of production LOC". Headline: **205,091 of 306,950 prod
LOC (67%) matched by no rule glob**; `backend/core` **91k**, `frontend/src/ui` **53k**,
`frontend/src/scene` **38k**. The sweep script is ~20 lines (minimatch semantics: `a/**/*.py` must
match `a/x.py` — naive `fnmatch` under-reports and will tell you `api-and-state` matches 0 files).

**New-rule candidates, in value order** (the "missing rule is worse than the stale rule" lesson,
now with a metric behind it): `models-and-schema` (`backend/core/models.py` 3,314 — the `Design`
schema the whole app reads; `REFERENCE_MODELS.md` covers it but is **not auto-loaded**);
`assembly-render` (`scene/assembly_renderer_shared.js` 3,940 + `joint_renderer.js` 3,224 +
`assembly_joint_renderer.js` 2,839 ≈ 10k LOC, no rule); `md-jobs` (`backend/core` MD stack +
`ui/md_jobs_panel.js` 3,707 + `oxdna_jobs_panel.js` 2,554). Lower urgency than it looks:
`lattice.py` — the locked-`_PHASE_*` warning lives in `CLAUDE.md`, which is always loaded.

Then resume the plan queue at **`project_regional_autorefine`** (queue top). Still standing:
**`project_cadnano_overhaul.md`** is stale as an architecture map (last dev-log 2026-05-25; code
touched 2026-07-28; its gate still says "confirm all 17 API tests pass" when there are **25**) —
rank it as a *plan*, not a map, and note its architecture content is now superseded by
`.claude/rules/cadnano-editor.md`.

*New this pass — an enumeration inside a rule is a liability, and the fix is to delete it, not
refresh it.* `api-and-state`'s route index listed 84 of **567** routes with 10 dead. Refreshing it
would buy weeks before the next carve-up broke it again, and a 100%-accurate 567-row table would be
unreadable and would still rot. It was replaced by a **recipe** (the `rg` patterns that find any
route + the "every router mounts at `/api`" law) plus a coarse family map that only changes when a
whole subsystem appears. **Rule of thumb: if a doc section is a list whose length tracks the
codebase, it belongs in a grep command, not in the doc.** Apply this on sight to any remaining rule
that enumerates routes, files, or hotkeys.

*Also new — the model can be wrong, not just the symbols.* Past passes found dead names inside a
correct architecture. Here both the rule and its runbook were built on `_active_design` + a
module-level `_history`: the backend has been **per-document** (`_sessions` keyed by an
`X-NADOC-Doc` header) for long enough that no such globals exist. Every downstream sentence — "the
active design", "stale server state", "the undo stack" — inherited the error, and the runbook's
flagship advice ("restart the server") is now *wrong in a new way* because `session_cache.restore()`
re-hydrates the bad state on boot. **Tell: when a doc says "the X" and the code says
`dict[key, X]`, stop auditing symbols and re-derive the model.**

*And the worst find is still a doc that causes a bug, not one that wastes a session.*
`RUNBOOK_API.md:20` asserted `mutate_and_validate` was "the ONLY correct way to mutate" while
`mutate_with_reconcile` had become **mandatory** for cluster-affecting topology edits. A session
following the runbook writes code that silently skips `reconcile_cluster_membership`. Logged to
`tech_debt` with a note to grep past cluster-membership bugs against it. **When a doc says ONLY /
ALWAYS / NEVER, verify that claim before anything else in the file** — it is the sentence most
likely to be obeyed and the one that does damage when wrong.

*Corollary confirmed again (6 for 6):* best outputs were negatives — `MAP_API_FLOW.md` never
existed (the rule was its sole mention repo-wide), `_active_design` never existed, and 2 of the 10
dead routes (`prebreak`, `PATCH /design/extensions/{id}`) were ones the handoff had **not**
predicted. Predicted-dead lists scope the probe; they never bound it.

## Standing lessons (carry forward — compressed from earlier passes)

- **Audit the path-scoped rules, not just the plans.** A stale `project_*.md` costs a session only
  when someone opens it; a stale `.claude/rules/*.md` is **auto-loaded** and teaches every session
  in the area, unprompted. Same rot, strictly worse decay.
- **A bad glob means the rule never loaded on the code it describes, for its entire life** — so
  nothing has ever corrected it. That is why it *predicts* body rot rather than accompanying it.
  **4 for 4, and now exhausted** (a *narrow* glob that misses extracted siblings predicts just as
  well as a zero-match one — `selection`). Remaining rules need the LOC-without-coverage metric.
- **Delete enumerations; keep recipes.** A list whose length tracks the codebase (routes, files,
  hotkeys) is guaranteed to rot and is unreadable when correct. `api-and-state`'s route index was
  84 of 567 with 10 dead; it was replaced by the `rg` patterns that find any route plus the
  invariant that makes them work (`prefix="/api"` on all 62 routers). Coarse family maps are fine —
  they change only when a subsystem appears.
- **Re-derive the model before auditing the symbols.** `api-and-state` and its runbook were both
  built on `_active_design` + a module-level `_history` in a backend that is per-document
  (`_sessions[doc_id]`). Every sentence downstream inherited the error. **Tell: the doc says "the
  X", the code says `dict[key, X]`.**
- **Verify ONLY / ALWAYS / NEVER sentences first.** They are the most-obeyed and most-damaging
  lines in any doc. `RUNBOOK_API.md` said `mutate_and_validate` was "the ONLY correct way to
  mutate" after `mutate_with_reconcile` became mandatory for cluster-affecting edits — following it
  writes a silent cluster bug.
- **Count the API surface; don't sample it.** `selection.md` listed 8 of 26 init opts, 2 of 19 API
  methods, 8 of 11 store flags and 3 of 10 enum values — every listed item *correct*, so any
  spot-check passes and the gap is invisible. Compare integers (destructure length, return-object
  keys, literal fields) against each doc table. And check whether a stale **source comment** shares
  the doc's root: 3 of those 4 undercounts were mirrored in the code itself, so fixing only the rule
  leaves the seed. Log the comment to `tech_debt` and give the rule a "Traps" section so nobody
  "fixes" the code to match its own wrong comment.
- **The missing rule is worse than the stale rule, and it is invisible.** A stale rule announces
  itself when a session hits a dead symbol; an absent one produces no signal and the area gets
  re-derived forever. Tell: when a rewrite makes you write "not this rule: X", check whether X has a
  rule. That found `cadnano-editor` (10,713 LOC, zero coverage).
- **Verify the handoff's own anchors.** Pre-gathered evidence carried into the `cadnano-editor` pass
  had **5 wrong claims** (off-by-one line, an unbound hotkey, 3 keys in the wrong file, a constant in
  the wrong module). Reuse a handoff to *scope* the probe; re-verify everything you write down — a
  wrong rule is auto-loaded, so it is worse than the hole it fills.
- **A rule can be wrong about a causal story, not just a symbol.** `cadnano-2d`'s worst content was a
  "Known culprit (fixed 2026-04-01)" section guarding against a subscriber that no longer existed, in
  a function with zero callers. Every identifier still resolved; only the wiring was gone. When a
  rule explains WHY, probe the call graph.
- **State test coverage honestly and by name.** A filename that implies coverage it doesn't provide
  is worse than no test (`e2e/cadnano_*.spec.js` cover the importer and the *editor*, not the view;
  `test_cluster_config.py` is Alpine HPC, not cluster transforms).
- **Plan status text is stale in BOTH directions** (4 for 4 among kept plans). `mixed_representation`
  claimed "UI pending" (shipped) *and* claimed two helpers that no longer exist. Diff every head
  claim line-by-line; never trust the top-line banner. **Probe the `NOT built` list first** — that is
  where a stale doc most actively misleads (`protein_attachment`'s two "not built" bullets were a
  563-LOC shipped subsystem and a helper on a live call path).
- **A plan that outlived its subject splits into a dead half and a still-true half belonging to a
  younger doc.** Probe the halves separately; "some of this is still true" is not a reason to keep
  the file. Before any delete, grep the head for "user rule / user decision / user accepted" — a user
  decision whose signature looks like a bug (matched-ends `far−near ∈ {P, P-1}`) is the highest-risk
  thing to lose.
- **A code-location table beats the prose around it.** Probes keep finding paths moved by the
  carve-ups (crud.py → `routes_*`, main.js → `ui/*`) and test paths that were never right.
- **Split head/archive as part of the audit** when a head has grown into a reverse-chronological work
  log (880 lines in `simulate_panel_overhaul`). Mechanical, and as much the deliverable as the verdict.
- **Every pass turns up stale non-plan artifacts the doc was innocent of** — dead-API scripts, e2e
  specs POSTing removed routes, `CELLS_6HB` copy-pasted with divergent geometry, a 4th divergent
  `STAPLE_PALETTE`, `docs/triage/` fiction. Those go to `project_tech_debt`. A good probe audits the
  code as a side effect; give the code defects a home instead of dropping them.

**Standing HOLDs (user-owned decision, do not touch):** `project_bundle_stiffness_params`,
`project_periodic_md` — both LIVE-REFERENCE, parked in the HOLD block above.
