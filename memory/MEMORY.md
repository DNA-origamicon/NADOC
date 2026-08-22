# NADOC — Memory Index

Pointer-only. Open a topic file when it matches the task. Hard rules + commands live in `CLAUDE.md`.

**Context economy.** Big topic files split into a lean *head* (current state, invariants, open items,
handoff) plus `*_archive.md` (history). **Never read an archive in a routine loop** — mine it only for
a specific past decision. Keep this index lean and edit it rarely — it's always-loaded, so any change
invalidates the prompt cache for all sessions.

Topic heads use `type`/`status`/`authority`/`review_after` frontmatter when useful (statuses: `active`,
`blocked`, `shipped`, `retired`, `historical`; authority: `canonical`/`supporting`).

## Read first when relevant

- **[LESSONS](LESSONS.md)** — anti-patterns index; open only the matching entry.
- **[REFERENCE_DNA_TOPOLOGY](REFERENCE_DNA_TOPOLOGY.md)** — strand/scaffold/polarity rules. Always.
- **[architecture_decisions](architecture_decisions.md)** — binding laws (DTP-PMD-1/2). Don't drift without sign-off.
- **`FEATURE_DEVELOPMENT.md`** (root) — module-first guardrails. READ BEFORE ADDING ANY FEATURE.
- **[tech_debt](project_tech_debt.md)** — `TD-NN` driver for `/audit-debt` (head + `_archive`).
- **[reference_assembly_test_fixture](reference_assembly_test_fixture.md)** — `workspace/Belt_test1.nass`.
- **[reference_efield_crossval_fixture](reference_efield_crossval_fixture.md)** — `workspace/6hb_e_test.nadoc`.
- [test_parallelization](project_test_parallelization.md) — **`just test-smart` is the DEFAULT**; full `just test` = pre-push gate only.

## Session loops (root files; read handoff first)

| Loop | Files | Slash |
|---|---|---|
| Fix next issue | `issues_ledger.md` + `issues_fix_log.md` | — |
| Backend god-file carve-up | `backend_router_carveup.md` + `_extraction_log.md` | `/carve-router` |
| Manual-validation debt | `manual_validation_debt.md` | — |
| Design automation | `design_automation_{backlog,log}.md` | `/automate-feature` |
| Sim/feature coverage | `SIM_COVERAGE_PLAN.md` + `.json` + `_log.md` | `/continue-coverage` |
| Stale-plan audit | `plan_audit_ledger.md` | `/audit-plan` |
| Tech-debt burn-down | `project_tech_debt.md` (+ `_archive`) | `/audit-debt` |
| Response-diffing burn-down | `project_response_diffing.md` + `_log.md` | — |

## Path-scoped architecture

`.claude/rules/*.md` auto-load when a matching file is read — don't open manually.
`api-and-state`·`rendering`·`selection`·`cadnano-2d` (K-key view)·`cadnano-editor` ·
`unfold`·`deformation`·`animation`·`scaffold-and-loops`·`main-init`·`strand-anim`
(`physics-fem` retired — see `archive/physics_xpbd_fem/physics-fem-rule.md`)

## Domain references

[CONSTANTS](REFERENCE_CONSTANTS.md) lattice+B-DNA·[MODELS](REFERENCE_MODELS.md) `Design` conventions ·
[PHASE_STATUS](REFERENCE_PHASE_STATUS.md) historical·[CADNANO](REFERENCE_CADNANO.md) v2 import/export ·
[ATOMISTIC](REFERENCE_ATOMISTIC.md) PDB/PSF·[FEM](REFERENCE_FEM.md) derelict, revival only ·
[DEFORMATION_THEORY](REFERENCE_DEFORMATION_THEORY.md) DTP-6/loop-skip·[SQUARE_LATTICE](REFERENCE_SQUARE_LATTICE.md) DTP-SQ ·
[CROSSOVER_AUTOBREAK](REFERENCE_CROSSOVER_AUTOBREAK.md) ligation, circular ·
**[AKSIMENTIEV_PROTOCOL](REFERENCE_AKSIMENTIEV_PROTOCOL.md)** — canonical NAMD protocol + our delta; read before solvation/ENM/barostat ·
[PLAYWRIGHT](REFERENCE_PLAYWRIGHT.md) troubleshooting only ·
**[RUNPOD_RUNBOOK](REFERENCE_RUNPOD_RUNBOOK.md)** — READ + run `preflight.py` BEFORE renting GPU

## User feedback

Files are `feedback_<name>.md`. Match the name against what you're editing; each is short.

**General:** **[refer_to_jobs_by_part_and_time](feedback_refer_to_jobs_by_part_and_time.md)** (name jobs by part+time)·**[runpod_downloads_to_archive](feedback_runpod_downloads_to_archive.md)** (→ `/media/jojo/Archive`) ·
**[concurrent_sessions](feedback_concurrent_sessions.md)** (shared worktree — never `git stash`/`reset`/`restore`)·**[geometry_change_authorization](feedback_geometry_change_authorization.md)** (show atoms/deltas before authorization) ·
**[no_live_server_mutation_for_verify](feedback_no_live_server_mutation_for_verify.md)**·**[use_completion_triggers](feedback_use_completion_triggers.md)** (never foreground sleep/poll) ·
**[runpod_babysitter_must_act](feedback_runpod_babysitter_must_act.md)** (must KILL pod on failure)·[aksel_abandoned](feedback_aksel_abandoned.md)·[crossover_no_reasoning](feedback_crossover_no_reasoning.md)·[phase_constants_locked](feedback_phase_constants_locked.md)·[native_files_preserve_positions](feedback_native_files_preserve_positions.md) ·
**[staples_are_user_intent](feedback_staples_are_user_intent.md)** (unstapled = intentional loop)·[design_renderer_visibility_rule](feedback_design_renderer_visibility_rule.md)·[overhang_definition](feedback_overhang_definition.md)·[interrupt_before_doubting_user](feedback_interrupt_before_doubting_user.md)·[busy_popup_threshold](feedback_busy_popup_threshold.md) ·
[user_todo_smoke_tests](feedback_user_todo_smoke_tests.md)·**[gpu_value_is_two_axes](feedback_gpu_value_is_two_axes.md)** ($/ns AND ns/day)·[playwright_fixtures_location](feedback_playwright_fixtures_location.md)·[display_toggle_visual_verify](feedback_display_toggle_visual_verify.md)·[no_bulk_reformat](feedback_no_bulk_reformat.md) ·
[loopskip_no_crossover_ends](feedback_loopskip_no_crossover_ends.md)·[browser_console_debugging](feedback_browser_console_debugging.md)

**MD / simulation:** [c1_pair_builder](feedback_c1_pair_builder.md)·[wc_calibration](feedback_wc_calibration.md)·[cg_pipeline_lessons](feedback_cg_pipeline_lessons.md)·[gromacs_debugging](feedback_gromacs_debugging.md)·[sd_em_constraints](feedback_sd_em_constraints.md)·[no_parallel_gromacs](feedback_no_parallel_gromacs.md)·[mrdna_gromacs_atomistic](feedback_mrdna_gromacs_atomistic.md)·[mdanalysis_live_reload](feedback_mdanalysis_live_reload.md)·[pbc_trajectory_alignment](feedback_pbc_trajectory_alignment.md)·[bundle_param_extraction](feedback_bundle_param_extraction.md)·[namd_pdb_serial_limit](feedback_namd_pdb_serial_limit.md)·[namd_cufix_oc_stub](feedback_namd_cufix_oc_stub.md)·[namd_anisotropic_barostat](feedback_namd_anisotropic_barostat.md) ·
**[namd_4fs_production_only](feedback_namd_4fs_production_only.md)** (4.0 fs is the ONLY production dt — fix the clash, never lower)

## Active topic files

Files are `project_<name>.md`. Bold = read before touching that area.

**Cluster/joints:** [cluster_joints](project_cluster_joints.md)·[cluster_reconcile](project_cluster_reconcile.md)·[cluster_autodetect](project_cluster_autodetect.md)·**[deformation_cluster_scope](project_deformation_cluster_scope.md)** (LIVE REF — scope frozen into `affected_helix_ids`, geometry never reads `cluster_ids`)·[cluster_copy_paste](project_cluster_copy_paste.md)

**Feature log / anim:** [feature_log_overhaul](project_feature_log_overhaul.md)·[animation_fade](project_animation_fade.md)·[animation_all_reprs](project_animation_all_reprs.md)·[assembly_configurations](project_assembly_configurations.md)

**Workspace / UX:** **[ux_overhaul](project_ux_overhaul.md)** (P2 — sole owner of file-browser/library/sidebar/modal/toast; `drag_scrub.js`+`overhang_binding_lines.js` gone)

**Selection:** **[mature_selection_model](project_selection_model.md)** (SHIPPED contract — normalized refs, sole-writer controller; read before changing selection)

**Display / representation:** **[native_vr](project_native_vr.md)** (ACTIVE)·[ssdna_ball_joints](project_ssdna_ball_joints.md)·[photo_mode](project_photo_mode.md)·[hull_prism](project_hull_prism.md)·**[mixed_representation](project_mixed_representation.md)** (impostors uncovered)·[strand_animations](project_strand_animations.md)·[reference_geometry](project_reference_geometry.md)·[protein_attachment](project_protein_attachment.md)·[headless_build](project_headless_build.md)·[sphere_impostors](project_sphere_impostors.md)

**Sequences:** **[strand_sequence_edit](project_strand_sequence_edit.md)** (hand-edit a strand's bases; targeted vs design-wide re-derive)

**Crossover geometry:** Catenation retired 2026-08-11 (archived only); ring piercing + heavy-atom clashes are active diagnostics. ·
**[extra_base_spacing](project_extra_base_spacing.md)** (2.25 nm lattice ~2 Å tighter than equilibrium, even with no inserts) ·
**[measured_atomistic](project_measured_atomistic.md)** (all-atom templates re-extracted from free NAMD) ·
**[atomistic_source_of_truth](project_atomistic_source_of_truth.md)** (P0 — RE-VERIFIED CG coupling audit; head + `_archive`) ·
**[helical_site](project_helical_site.md)** (site abstraction all reps project from; CLOSED, head + `_archive`)

**Overhangs / linkers:** **[overhang_duplex_foundation](project_overhang_duplex_foundation.md)**·**[overhang_duplex_cluster](project_overhang_duplex_cluster.md)**·**[overhang_subdomains](project_overhang_subdomains.md)** (bind-locks-joint REVERTED)·[overhang_connections](project_overhang_connections.md)·[overhang_binding_extensions](project_overhang_binding_extensions.md)·[assembly_overhang_bindings](project_assembly_overhang_bindings.md)·[assembly_linker_relax](project_assembly_linker_relax.md)·[bond_relax](project_bond_relax.md)·[ct_tab](project_ct_tab.md)·**[overhang_connections_panel](project_overhang_connections_panel.md)** (diff-length UI-only)·[ssdna_linker_relax](project_ssdna_linker_relax.md)·[oh_binder](project_oh_binder.md)·[overhang_lookup_infra](project_overhang_lookup_infra.md)·[overhang_generation](project_overhang_generation.md)·**[mate_connectors](project_mate_connectors.md)**·[domain_ends_refactor](project_domain_ends_refactor.md)·**[overhang_sequence_display](project_overhang_sequence_display.md)** (3 consumers bypass)

**Primitives / export:** [plates_and_tubes](project_plates_and_tubes.md)·[extrude_preview](project_extrude_preview.md)·[primitive_library](project_primitive_library.md)·[stl_export](project_stl_export.md)

**Cadnano editor:** [periodic_boundary](project_periodic_boundary.md)·[cadnano_resize](project_cadnano_resize.md)·[domain_shift_feature](project_domain_shift_feature.md)·[xover_base_lerp](project_xover_base_lerp.md)

**Scaffold / seam / autostaple:** **[hinge_autoscaffold](project_hinge_autoscaffold.md)** (regression gate)·**[autoscaffold_single_strand](project_autoscaffold_single_strand.md)** (section_router / dumbbell+teeth)·[seamless_router](project_seamless_router.md)

**Cluster submission (Alpine):** **[alpine_cluster_submission](project_alpine_cluster_submission.md)** (read "Resume model" before touching resume)

**MD (NAMD+oxDNA):** **[cpd_umbrella_sampling](project_cpd_umbrella_sampling.md)** (never forms unbiased)·**[reference_local_namd_build](reference_local_namd_build.md)** (Dec-2025 build, `NADOC_NAMD_BIN`; 3.0.2 crashes GPU-resident)·[lammps_oxdna](project_lammps_oxdna.md)·[oxpy_binding_patch](project_oxpy_binding_patch.md)·[proteins_in_simulation](project_proteins_in_simulation.md)·[oxdna_efield](project_oxdna_efield.md)·[oxdna_relaxation](project_oxdna_relaxation.md)·[benchmark_tuning](project_benchmark_tuning.md)·[md_engines_panel](project_md_engines_panel.md)

**MrDNA / ARBD:** [mrdna_arbd_setup](project_mrdna_arbd_setup.md)·**[mrdna_bead_model](project_mrdna_bead_model.md)** (1 bead/bp, not /nt)·[mrdna_panel](project_mrdna_panel.md)·[mrdna_extensions](project_mrdna_extensions.md) (guard `__ext_` not `__`; `__lnk__` is real duplex)

**oxDNA CG:** [oxdna_benchmarks](project_oxdna_benchmarks.md)·[oxdna_extra_bases](project_oxdna_extra_bases.md)·[surface_strands](project_surface_strands.md) (immobilization; P3 residual) ·
**[strand_extensions_sim](project_strand_extensions_sim.md)** (5′/3′ tails in oxDNA+NAMD — read before touching nucleotide walk/native seed) ·
[skip_twist_selfconsistency](project_skip_twist_selfconsistency.md)·**[regional_autorefine](project_regional_autorefine.md)** (LIVE REF — always-on 1–5-edit skip fine-tuner; wholesale placement shelved)·[skip_twist_curvature_sweep](project_skip_twist_curvature_sweep.md)·[md_twist_validation](project_md_twist_validation.md)

**Native FEM shape predictor:** [cando_fem](project_cando_fem.md)·**[snupi_mimic](project_snupi_mimic.md)** (`material="snupi"`)·[snupi_frontend_tab](project_snupi_frontend_tab.md)·**[snupi_gaps](project_snupi_gaps.md)** (A–D DONE)·**[snupi_reference_compare](project_snupi_reference_compare.md)** (real SNUPI at `~/SNUPI`)·**[snupi_dynamics](project_snupi_dynamics.md)** (Langevin)·
**[snupi_ssdna](project_snupi_ssdna.md)** (PLAN SS-0…SS-5)

**BLADE — ARCHIVED 2026-07-20:** **[blade_frontend](project_blade_frontend.md)** (dormant, one-line revive)·**[atomistic_propagator](project_atomistic_propagator.md)** (shelved: ~60× too slow)

**Multi-resolution / CG bridge:** [multiresolution_roadmap](project_multiresolution_roadmap.md)·**[crossover_parameterization](project_crossover_parameterization.md)** (live DB feeds every mrDNA relax)·[bundle_stiffness_params](project_bundle_stiffness_params.md)·[session_handoff](project_session_handoff.md)

**NAMD production / solvation:** **[periodic_md](project_periodic_md.md)** (governed by [architecture_decisions](architecture_decisions.md))·[btube_benchmark](project_btube_benchmark.md)·[periodic_cell](project_periodic_cell.md)·[namd_solvate](project_namd_solvate.md)·[water_shell_carve](project_water_shell_carve.md)·[3x4sq_md_run](project_3x4sq_md_run.md)·[exp30_18hb_production](project_exp30_18hb_production.md) ·
**[extra_base_4fs_geometric_fixb](project_extra_base_4fs_geometric_fixb.md)** (winning seed = GEOMETRIC+FixB, not oxDNA position-seed)·**[voltroncore_fullbox_bench](project_voltroncore_fullbox_bench.md)** (>10M-atom PSF needs EXT format) ·
**[declash_reaudit](project_declash_reaudit.md)** (SHIPPED — declash explicit-only; topology-exact ss-exclusion; Alpine/RunPod early-stop tiers retired, byte-for-byte local parity)

**Atomistic skip-site/GROMACS:** [atomistic_skip_backbone](project_atomistic_skip_backbone.md)·[skip_site_gromacs_fix](project_skip_site_gromacs_fix.md)·[langevin_heating](project_langevin_heating.md)·[gromacs_package_structure](project_gromacs_package_structure.md)·[atomistic_calibration](project_atomistic_calibration.md)·[o3prime_investigation](project_o3prime_investigation.md)·[gromacs_export](project_gromacs_export.md)

**MD job system / runners:** [md_job_system](project_md_job_system.md)·[md_prep_relaxation](project_md_prep_relaxation.md)·[oxdna_metrics_card](project_oxdna_metrics_card.md)

**Simulate-panel overhaul:** [simulate_panel_overhaul](project_simulate_panel_overhaul.md) (P1; C half done — mrDNA+CanDo lack Run/Stop/Resume)

**MD visualization / overlay:** [md_viz_tools](project_md_viz_tools.md)·[md_panel_status](project_md_panel_status.md)·[md_sidebar_audit](project_md_sidebar_audit.md)·[md_live_model_cache](project_md_live_model_cache.md) ·
**[oxdna_occupancy_clouds](project_oxdna_occupancy_clouds.md)** (top-N configs superposed; read before ensemble clustering) ·
**[atomistic_base_orient](project_atomistic_base_orient.md)** (`base_orient="oxdna_a3"`, default-on; pending visual check)

**Automation / jobs infra:** [staleness_diagnostics](project_staleness_diagnostics.md)·[job_activity_spinner](project_job_activity_spinner.md)·[job_disk_usage](project_job_disk_usage.md)·[job_archive](project_job_archive.md)·[runpod_submission](project_runpod_submission.md)·[af25/26 log sync](project_af25_af26_job_log_sync.md)

**Dev infra:** **[scrywrite](project_scrywrite.md)** (VR troubleshooting driver)·[dev_server_shutdown_hang](project_dev_server_shutdown_hang.md)·[nadoc_overview](project_nadoc_overview.md)·**[context_economy_split](project_context_economy_split.md)** (head/archive rule)·[steamvr_drm_lease_fix](project_steamvr_drm_lease_fix.md) (Vive HDMI-0 DRM lease, automatic in routes_vr.py)

**Imports / validation:** [sq_importer_fix](project_sq_importer_fix.md)·[crossover_distance_script](project_crossover_distance_script.md)·[clash_detector](project_clash_detector.md)·[corner_primitive](project_corner_primitive.md)

**Assembly overhaul:** **[path_to_thousands](project_path_to_thousands.md)** (renderer DEFAULT)·[assembly_part_context](project_assembly_part_context.md) (anim PLAYBACK unbuilt)·[assembly_groups](project_assembly_groups.md) (`representation` dead)·[gear_relations](project_gear_relations.md)·[belt_paths](project_belt_paths.md)·[route_for_polymerization](project_route_for_polymerization.md)·[polymerize_origami](project_polymerize_origami.md)·[session_recovery](project_session_recovery.md)

## Supporting and historical topics

[AutoNAMD delta](autonamd_nadoc_protocol_delta.md)·[F028 perf research](f028_performance_optimization_research.md)·[MD integration plan](md_integration_plan.md)·[mrDNA/NAMD inventory](mrdna_namd_inventory.md)·[atomistic O3′ log](log_atomistic_o3prime.md)·[main-init detail](main_init_detail.md)·[surface-vectorize handoff](HANDOFF_surface_vectorize.md)·[2026-05-05 session](project_session_2026_05_05.md)

**Unclassified:** [autostaple bugs](project_autostaple_bugs.md)·[create seam](project_create_seam.md)·[forced ligation](project_forced_ligation.md)·[near/far ends](project_near_far_ends.md) — assign to a category or mark historical.

## Maintenance

Finishing a feature → update its topic file *head*, not this index. Repeated mistakes → add one symptom hook to **LESSONS.md** + detail to `LESSONS_archive.md`.
Head past ~200 lines → move history to matching `*_archive.md`. Run `just lint-memory` after structure changes; see [hygiene rubric](../docs/agent_memory_hygiene.md) for periodic audits.
