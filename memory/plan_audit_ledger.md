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

## Next-session handoff

▶ **NEXT:** the **path-scoped-rule sweep** (promoted ahead of the remaining plans). Do the cheap triage
first — for each of the 9 unaudited rules, grep only its frontmatter `paths:` globs against `ls` of the
directories it claims; a glob matching no current file, or missing the module the rule is *about*, is a
10-second tell the body is stale. Rank the 9 by that signal, then full-rewrite the worst one this pass.
Justification for the promotion: `protein_attachment` just showed that **the carve-ups are the main
source of doc rot** (every route moved crud.py→`routes_protein.py`, the whole frontend closure moved
main.js→`scene/protein_subsystem.js`) — and the path-scoped rules are exactly the docs that point at
file paths *and* auto-load. Same rot, worse blast radius.

After the sweep, resume the plan queue at **`project_regional_autorefine`** (queue top).

Original note (still applies): the **other 9 path-scoped rules** (`api-and-state`, `rendering`, `selection`,
`cadnano-2d`, `unfold`, `deformation`, `animation`, `main-init`, `strand-anim`) have never been audited, and
`scaffold-and-loops` proved they rot in a uniquely expensive way — see the new pattern note below. Cheap
triage: for each rule, grep just its **frontmatter `paths` globs** against `ls` of the directories it claims;
a glob that matches no current file (or misses the module the rule is *about*) is a 10-second tell that the
body is stale too. Do that sweep before committing to a full per-rule rewrite.

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
