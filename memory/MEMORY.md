# NADOC — Memory Index

Pointer-only. Open a topic file when it matches the task. Hard rules + commands live in `CLAUDE.md` (repo root).

**Context economy.** Ledgers and big topic files are split into a lean *head* (current state, invariants,
open items, handoff) plus an `*_archive.md` (history). **Never read an archive in a routine loop** — mine it
only when you need a specific past decision. Keep this index lean and edit it rarely: it sits in the always-loaded
prompt prefix, so every change to it invalidates the prompt cache for all sessions.

## Read first when relevant

- **[LESSONS](LESSONS.md)** — anti-patterns by failure mode. Now an index: scan it, open only the matching entry.
- **[REFERENCE_DNA_TOPOLOGY](REFERENCE_DNA_TOPOLOGY.md)** — strand/scaffold/polarity rules. Always.
- **[architecture_decisions](architecture_decisions.md)** — binding cross-cutting laws (DTP-PMD-1/2). Don't drift without sign-off.
- **`FEATURE_DEVELOPMENT.md`** (root) — module-first guardrails. READ BEFORE ADDING ANY FEATURE.
- **[tech_debt](project_tech_debt.md)** — code flagged for review/removal; now the `TD-NN` driver for the `/audit-debt` burn-down loop (head + `_archive`).
- **[reference_assembly_test_fixture](reference_assembly_test_fixture.md)** — `workspace/Belt_test1.nass`, any assembly test.
- **[reference_efield_crossval_fixture](reference_efield_crossval_fixture.md)** — `workspace/6hb_e_test.nadoc`, E-field cross-val.
- [test_parallelization](project_test_parallelization.md) — **`just test-smart` is the DEFAULT per-change loop**; full `just test` = pre-push gate only.

## Session loops (root files; each head is lean, read its handoff first)

| Loop | Files | Slash |
|---|---|---|
| Fix next issue | `issues_ledger.md` + `issues_fix_log.md` | — |
| Backend god-file carve-up | `backend_router_carveup.md` + `backend_router_extraction_log.md` | `/carve-router` |
| Manual-validation debt | `manual_validation_debt.md` | — |
| Design automation | `design_automation_{backlog,log}.md`; `{harness,metrics}` on demand | `/automate-feature` |
| Sim/feature coverage | `SIM_COVERAGE_PLAN.md` + `sim_coverage_plan.json` + `sim_coverage_log.md` | `/continue-coverage` |
| Stale-plan audit | `plan_audit_ledger.md` | `/audit-plan` |
| Tech-debt burn-down | `memory/project_tech_debt.md` (+ `_archive`) | `/audit-debt` |

## Path-scoped architecture maps

`.claude/rules/*.md` auto-load when a matching file is read — don't open manually. They are versioned
and shared across both computers (see `CLAUDE.md` → Memory layout).
`api-and-state` · `rendering` · `selection` · `cadnano-2d` (K-key view mode) ·
`cadnano-editor` (the separate editor app) · `unfold` · `deformation` ·
`animation` · `scaffold-and-loops` · `main-init` · `strand-anim`

(`physics-fem` was retired with the FEM/XPBD code — see `archive/physics_xpbd_fem/physics-fem-rule.md`.)

## Domain references (load on demand)

[CONSTANTS](REFERENCE_CONSTANTS.md) lattice + B-DNA ·
[MODELS](REFERENCE_MODELS.md) domain conventions, `Design` ·
[PHASE_STATUS](REFERENCE_PHASE_STATUS.md) historical ·
[CADNANO](REFERENCE_CADNANO.md) v2 import/export ·
[ATOMISTIC](REFERENCE_ATOMISTIC.md) PDB/PSF ·
[FEM](REFERENCE_FEM.md) derelict, revival only ·
[DEFORMATION_THEORY](REFERENCE_DEFORMATION_THEORY.md) DTP-6 / loop-skip ·
[SQUARE_LATTICE](REFERENCE_SQUARE_LATTICE.md) DTP-SQ ·
[CROSSOVER_AUTOBREAK](REFERENCE_CROSSOVER_AUTOBREAK.md) ligation, circular ·
**[AKSIMENTIEV_PROTOCOL](REFERENCE_AKSIMENTIEV_PROTOCOL.md)** — the canonical origami NAMD protocol (read from its own scripts) + our delta; read before touching solvation/ENM/barostat ·
[PLAYWRIGHT](REFERENCE_PLAYWRIGHT.md) troubleshooting only, never routine ·
**[RUNPOD_RUNBOOK](REFERENCE_RUNPOD_RUNBOOK.md)** — READ + run `preflight.py` BEFORE renting any GPU

## User feedback (open the one matching your area)

Files are `feedback_<name>.md`. Match the name against what you're editing; each is short.

**General:** **refer_to_jobs_by_part_and_time** (name a sim job by its part + creation time — the UI shows no job ids) · **runpod_downloads_to_archive** (big downloads → `/media/jojo/Archive`, not the full system disk) ·
**concurrent_sessions** (shared worktree — never `git stash`/`reset`/`restore`; forbid git in subagent prompts) ·
**no_live_server_mutation_for_verify** · **use_completion_triggers** (never foreground sleep/poll) ·
**runpod_babysitter_must_act** (must KILL the pod on failure, not just log) · aksel_abandoned · crossover_no_reasoning · phase_constants_locked · native_files_preserve_positions ·
**staples_are_user_intent** (unstapled scaffold = intentional ssDNA loop) · design_renderer_visibility_rule · overhang_definition · interrupt_before_doubting_user · busy_popup_threshold ·
user_todo_smoke_tests · **gpu_value_is_two_axes** ($/ns AND ns/day) · playwright_fixtures_location · display_toggle_visual_verify · no_bulk_reformat ·
loopskip_no_crossover_ends · browser_console_debugging

**MD / simulation:** c1_pair_builder · wc_calibration · cg_pipeline_lessons · gromacs_debugging · sd_em_constraints · no_parallel_gromacs · mrdna_gromacs_atomistic · mdanalysis_live_reload · pbc_trajectory_alignment · bundle_param_extraction · namd_pdb_serial_limit · namd_cufix_oc_stub · namd_anisotropic_barostat ·
**namd_4fs_production_only** (4.0 fs is the ONLY production dt — fix the clash, never lower dt)

## Active topic files

Files are `project_<name>.md`. Bold = read before touching that area.

**Cluster/joints:** cluster_joints · cluster_reconcile · cluster_autodetect · **deformation_cluster_scope** (LIVE REF — scope is frozen into `affected_helix_ids`; geometry never reads `cluster_ids`) · cluster_copy_paste

**Feature log / anim:** feature_log_overhaul · animation_fade · animation_all_reprs · assembly_configurations

**Workspace / UX:** **ux_overhaul** (P2 — sole owner of file-browser/library/sidebar/modal/toast ground; read before any UI-chrome work. `drag_scrub.js` + `overhang_binding_lines.js` are gone despite the archive)

**Display / representation:** ssdna_ball_joints · photo_mode · hull_prism · **mixed_representation** (SHIPPED; P1 — deformed cylinders + impostors uncovered, suspected photo-export bead bug) · strand_animations · reference_geometry · protein_attachment (SHIPPED incl. conjugation picker; P2 — only Phase 3 assembly-scope left) · headless_build · sphere_impostors

**Sequences:** **strand_sequence_edit** (hand-edit a strand's bases; targeted vs design-wide re-derive)

**Crossover topology:** **crossover_catenation** (extra bases were built CATENATED, Lk=±1; detector + build gate + repair — read before touching extra-base placement or the joint solve) ·
**extra_base_spacing** (MD-measured interhelical spacing per extra base + the View toggle; the 2.25 nm lattice is ~2 Å tighter than equilibrium even with NO inserts — read before any clash/declash conclusion) ·
**measured_atomistic** (SHIPPED — all-atom templates re-extracted from free NAMD, both strands measured separately in one bp frame; read before touching atomistic placement or the New Positioning toggle)

**Overhangs / linkers:** **overhang_duplex_foundation** (P1 — the pairing MODEL of record; read before any overhang pairing. Geometry still runs on `OverhangBinding`; Phase 6 untouched) · **overhang_duplex_cluster** (SHIPPED — the duplex pose IS a child cluster, gizmo + taut drag; P2, only feature-log migrate-on-load left) · **overhang_subdomains** (P2 — SubDomain model + Domain Designer tab, shipped; rotation UI deleted 2026-05-11 but its geometry chain is still live; bind-locks-joint was REVERTED 05-14) · overhang_connections · overhang_binding_extensions · assembly_overhang_bindings · assembly_linker_relax · bond_relax · ct_tab · **overhang_connections_panel** (SHIPPED — the ConnectionVersion + Connect/Apply/Relax pipeline of record; P2, the one real gap is that different-length direct connect only works from the UI, not headlessly) · ssdna_linker_relax · oh_binder · overhang_lookup_infra · overhang_generation · **mate_connectors** (blunt-end connector geometry — read before touching overhang tips) · domain_ends_refactor · **overhang_sequence_display** (P2 — the one sequence assembler per side, JS/Py mirrored; read before touching overhang sequence display. 3 consumers still bypass it or its length source)

**Primitives / export:** plates_and_tubes · extrude_preview · primitive_library · stl_export

**Cadnano editor:** periodic_boundary · cadnano_resize · domain_shift_feature · xover_base_lerp

**Scaffold / seam / autostaple:** **hinge_autoscaffold** (regression gate) · **autoscaffold_single_strand** (section_router / dumbbell+teeth) · seamless_router

**Cluster submission (Alpine):** **alpine_cluster_submission** (read its "Resume model" block before touching resume)

**MD (NAMD+oxDNA):** **cpd_umbrella_sampling** (free energy of the designed extra-base UV weld; Phase 0 says it never forms unbiased — read before any colvars/US/free-energy work) · **reference_local_namd_build** (use the Dec-2025 git build via `NADOC_NAMD_BIN`; 3.0.2 crashes GPU-resident — read before any local NAMD run) · lammps_oxdna · oxpy_binding_patch · proteins_in_simulation · oxdna_efield · oxdna_relaxation · benchmark_tuning · md_engines_panel

**MrDNA / ARBD:** mrdna_arbd_setup · **mrdna_bead_model** (1 DNA bead per bp, not per nt) · mrdna_panel · mrdna_extensions (guard `__ext_`, NOT `__` — `__lnk__` is real duplex)

**oxDNA CG:** oxdna_benchmarks · oxdna_extra_bases · surface_strands (immobilization; P3 residual) ·
**strand_extensions_sim** (5′/3′ tails in oxDNA+NAMD — read before touching the nucleotide walk
or the native seed) ·
skip_twist_selfconsistency · **regional_autorefine** (LIVE REF — the always-on 1–5-edit skip fine-tuner; wholesale regional placement shelved) · skip_twist_curvature_sweep · md_twist_validation

**Native FEM shape predictor:** cando_fem · **snupi_mimic** (DONE, `material="snupi"`) · snupi_frontend_tab (SHIPPED) · **snupi_gaps** (A–D DONE) · **snupi_reference_compare** (real SNUPI at `~/SNUPI`; comparator loop) · **snupi_dynamics** (Langevin / Nat Commun 2023) ·
**snupi_ssdna** (PLAN SS-0…SS-5: bridging ssDNA + free tails)

**BLADE — ARCHIVED 2026-07-20:** **project_blade_frontend** (shipped then removed by user decision; code dormant, one-line revive) · **atomistic_propagator** (the science + why it's shelved: ~60× too slow)

**Multi-resolution / CG bridge:** multiresolution_roadmap · **crossover_parameterization** (the mrDNA crossover-param pipeline of record — live DB feeds every mrDNA relax) · bundle_stiffness_params · session_handoff

**NAMD production / solvation:** **periodic_md** (governed by [architecture_decisions](architecture_decisions.md)) · btube_benchmark · periodic_cell · namd_solvate · water_shell_carve · 3x4sq_md_run · exp30_18hb_production ·
**extra_base_4fs_geometric_fixb** (winning seed = GEOMETRIC build + Fix B, NOT the oxDNA position-seed) ·
**voltroncore_fullbox_bench** (11.3M-atom RunPod bench; >10M-atom PSF needs EXT format)

**Atomistic skip-site / GROMACS:** atomistic_skip_backbone · skip_site_gromacs_fix · langevin_heating · gromacs_package_structure · atomistic_calibration · o3prime_investigation · gromacs_export

**MD job system / runners:** md_job_system · md_prep_relaxation · oxdna_metrics_card

**Simulate-panel overhaul:** simulate_panel_overhaul (P1 — Phases A/B shipped; Phase C half done: mrDNA+CanDo lack the contextual Run/Stop/Resume button and still paint their own progress bars)

**MD visualization / overlay:** md_viz_tools · md_panel_status · md_sidebar_audit · md_live_model_cache ·
**oxdna_occupancy_clouds** (top-N configurations superposed; verdict switching/drift/unimodal — read before touching ensemble clustering) ·
**atomistic_base_orient** (`base_orient="oxdna_a3"`, default-on; pending in-app visual check)

**Automation / jobs infra:** staleness_diagnostics · job_activity_spinner · job_disk_usage · job_archive

**Dev infra:** dev_server_shutdown_hang · nadoc_overview · **context_economy_split** (head/archive rule)

**Imports / validation:** sq_importer_fix · crossover_distance_script · clash_detector · corner_primitive

**Assembly overhaul:** **path_to_thousands** (shared renderer DEFAULT; read before touching assembly) · assembly_part_context (P2 — camera+anim part-context live; part-mode anim PLAYBACK unbuilt, feature-log path is dead code) · assembly_groups (SHIPPED; P2 — group `representation` is a dead control no renderer reads; Escape-pop still unwired) · gear_relations · belt_paths · route_for_polymerization · polymerize_origami · session_recovery

## Maintenance

Finishing a feature → update its topic file *head*, not this index. Repeated mistakes → add to **LESSONS.md**.
When a head file grows past ~200 lines, move its history to the matching `*_archive.md`.
