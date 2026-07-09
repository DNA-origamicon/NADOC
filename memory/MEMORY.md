# NADOC — Memory Index

Index only. Open the topic file when relevant. Hard rules + commands live in `CLAUDE.md` (repo root).

## Read first when relevant

- **[LESSONS](LESSONS.md)** — past struggles + anti-patterns by failure mode. Open before debugging / non-trivial changes.
- **[REFERENCE_DNA_TOPOLOGY](REFERENCE_DNA_TOPOLOGY.md)** — strand/scaffold/polarity rules. Always.
- **[tech_debt](project_tech_debt.md)** — ledger of code flagged for review/removal.
- **`FEATURE_DEVELOPMENT.md` (repo root)** — module-first guardrails; READ BEFORE ADDING ANY FEATURE. New cohesive logic → new tested module (`initX({deps})→{api}`); `main.js` gains only imports+factory init+thin wiring (LOC flat-or-lower).
- **[reference_assembly_test_fixture](reference_assembly_test_fixture.md)** — `workspace/Belt_test1.nass` = reference assembly fixture. Use for any assembly test.
- **[reference_efield_crossval_fixture](reference_efield_crossval_fixture.md)** — `workspace/6hb_e_test.nadoc` = anchored-E-field cross-validation standard (both end overhangs pinned → transverse field bows the 6HB); bow = existing `field_response_profile`/`compute_shape_descriptors`, agreement via `compare_field_response`.
- **`issues_ledger.md` + `issues_fix_log.md` (repo root)** — "fix next issue" loop: repro-test FIRST → ask behavior → one phase → don't grow main.js. Read its "Next-session handoff".
- **`backend_router_carveup.md` + `backend_router_extraction_log.md` (repo root)** — backend god-file carve-up (`crud.py`/`assembly.py` → `routes_<area>.py`). `/carve-router`. Metric = back-import surface B≤3, not LOC.
- **`manual_validation_debt.md` (repo root)** — shift-register of "live gesture NOT hand-checked" features. One item/loop; `MV-N` rows.
- **`design_automation_{backlog,log,harness,metrics}.md` (repo root)** — design-automation loop (`/automate-feature`): one op → headless entry point + oracle. Read backlog+log per loop; harness+metrics on demand.
- **`SIM_COVERAGE_PLAN.md` + `sim_coverage_plan.json` + `sim_coverage_{log,metrics}.md` (repo root)** — sim/feature-coverage loop (`/continue-coverage`): drive CanDo/mrDNA/oxDNA/NAMD over extra-bases/linkers/E-fields/anchors + shared cross-engine metric. Task list = the JSON (status-only edits). Rubric: shared-metric first, anchors-before-field, one task/session, main loop + read-only subagents. Auto-commit to master. Read the `▶` handoff first.
- [test_parallelization](project_test_parallelization.md) — `just test` = parallel `pytest -n auto` (~2.5min); `just test-fast` skips slow real-sim (~45s); slow registry in `tests/conftest.py`; xdist active-design isolation gotcha.

## Path-scoped architecture maps

Live in `.claude/rules/`, auto-load when matching files are read. Don't open manually unless you need cross-area context.

| Rule file | Triggers on |
|---|---|
| `api-and-state.md` | `backend/api/**`, `frontend/src/api/**` |
| `rendering.md` | `frontend/src/scene/{design,helix,glow,domain_ends,crossover_connections}*` |
| `selection.md` | `frontend/src/scene/selection_manager.js` |
| `cadnano-2d.md` | `frontend/src/cadnano/**`, `frontend/src/scene/cadnano_view.js` |
| `unfold.md` | `frontend/src/scene/unfold_view.js` |
| `deformation.md` | `backend/core/deformation.py`, deform editor + view |
| `physics-fem.md` | physics + FEM modules |
| `animation.md` | animation player, panel, backend |
| `scaffold-and-loops.md` | scaffold/seamless/loop_skip backend, `lattice.py` |
| `main-init.md` | `frontend/src/main.js` |
| `strand-anim.md` | `frontend/src/strand-anim/**`, `frontend/strand-anim.html` |

## Domain references (load on demand)

- [REFERENCE_CONSTANTS](REFERENCE_CONSTANTS.md) — HC/SQ lattice constants, B-DNA params
- [REFERENCE_MODELS](REFERENCE_MODELS.md) — domain model conventions, overhang system, `Design`
- [REFERENCE_PHASE_STATUS](REFERENCE_PHASE_STATUS.md) — historical: shipped phases + test counts
- [REFERENCE_CADNANO](REFERENCE_CADNANO.md) — caDNAno v2 import/export
- [REFERENCE_ATOMISTIC](REFERENCE_ATOMISTIC.md) — Phase AA template, PDB/PSF export
- [REFERENCE_FEM](REFERENCE_FEM.md) — DERELICT (FEM+xpbd archived 2026-05-10); revival reference only
- [REFERENCE_DEFORMATION_THEORY](REFERENCE_DEFORMATION_THEORY.md) — DTP-6 / loop-skip theory
- [REFERENCE_SQUARE_LATTICE](REFERENCE_SQUARE_LATTICE.md) — DTP-SQ decisions, scaffold routing
- [REFERENCE_CROSSOVER_AUTOBREAK](REFERENCE_CROSSOVER_AUTOBREAK.md) — crossover/autobreak, ligation, circular strands
- [REFERENCE_PLAYWRIGHT](REFERENCE_PLAYWRIGHT.md) — E2E patterns. Troubleshooting-only, NOT routine verification (too slow).

## User feedback (apply when in scope)

- [aksel_abandoned](feedback_aksel_abandoned.md) — Aksel routing removed; = all-crossovers-minus-seams → break-at-ticks → merge-to-56
- [crossover_no_reasoning](feedback_crossover_no_reasoning.md) — never reason geometrically about crossovers; mechanical rules only
- [phase_constants_locked](feedback_phase_constants_locked.md) — `_PHASE_*` constants require explicit approval
- [native_files_preserve_positions](feedback_native_files_preserve_positions.md) — `/design/load`+`/design/import` (native) must NOT recenter
- [design_renderer_visibility_rule](feedback_design_renderer_visibility_rule.md) — hiding design touches 4 modules; arcs/extra-bases explicit
- [overhang_definition](feedback_overhang_definition.md) — overhangs = strands embedded in scaffold, free tip on overhang helix
- [interrupt_before_doubting_user](feedback_interrupt_before_doubting_user.md) — ask first; don't preemptively "fix" user observations
- [busy_popup_threshold](feedback_busy_popup_threshold.md) — `_BUSY_POPUP_DELAY_MS = 5000`
- [user_todo_smoke_tests](feedback_user_todo_smoke_tests.md) — manual smoke tests get a `USER TODO` numbered block
- [playwright_fixtures_location](feedback_playwright_fixtures_location.md) — test `.nadoc` → `workspace/playwright_tests/`, deleted when done
- [display_toggle_visual_verify](feedback_display_toggle_visual_verify.md) — verify viz toggles by SCREENSHOT not status text; multi-doc e2e needs doc-pinned load (`?doc=`+`X-NADOC-Doc`) or renders nothing

**MD / simulation feedback:**
- [c1_pair_builder](feedback_c1_pair_builder.md) — sort all C1' pair candidates by distance first (else scaffold-before-staples mispair)
- [wc_calibration](feedback_wc_calibration.md) — template structures ~25% WC inflated ref dist; use C1' as primary metric
- [cg_pipeline_lessons](feedback_cg_pipeline_lessons.md) — oxDNA segfaults, PCA vs override, mrdna 1 bead/bp, per-helix spline
- [gromacs_debugging](feedback_gromacs_debugging.md) — inspect em.gro bond lengths FIRST; dt/gen-vel secondary
- [sd_em_constraints](feedback_sd_em_constraints.md) — SD/steep support constraints=h-bonds; L-BFGS cannot
- [no_parallel_gromacs](feedback_no_parallel_gromacs.md) — parallel `gmx mdrun` slower here; run serially
- [mrdna_gromacs_atomistic](feedback_mrdna_gromacs_atomistic.md) — mrdna atomistic PDB unusable w/ CHARMM27; use NADOC templates
- [mdanalysis_live_reload](feedback_mdanalysis_live_reload.md) — `_reopen()` broken; rebuild Universe from disk
- [browser_console_debugging](feedback_browser_console_debugging.md) — `console.log` not `.debug`; add timestamps
- [pbc_trajectory_alignment](feedback_pbc_trajectory_alignment.md) — PBC diagnostics; median vs mean centroid
- [bundle_param_extraction](feedback_bundle_param_extraction.md) — topology vs geometry; PCA sign; Euler gimbal; centroid bias
- [namd_pdb_serial_limit](feedback_namd_pdb_serial_limit.md) — NAMD drops HETATM serials ≥10000; cap `(serial-1)%9999+1`
- [namd_cufix_oc_stub](feedback_namd_cufix_oc_stub.md) — fix OTMG NBFIX partners in `par_stub_ions_nbfix.str`
- [namd_anisotropic_barostat](feedback_namd_anisotropic_barostat.md) — `useFlexibleCell yes` → Z runaway; use isotropic NPT
- [no_bulk_reformat](feedback_no_bulk_reformat.md) — no repo-wide `ruff format` commits; rely on pre-commit hook
- [loopskip_no_crossover_ends](feedback_loopskip_no_crossover_ends.md) — auto loops/skips never on crossovers/strand-ends (breaks CanDo); manual placement stays free

## Active topic files

One line per entry, grouped by area. Open the topic file for detail.

**Cluster/joints:** [cluster_joints](project_cluster_joints.md) · [cluster_reconcile](project_cluster_reconcile.md) · [cluster_autodetect](project_cluster_autodetect.md) · [deformation_cluster_scope](project_deformation_cluster_scope.md) (bend/twist cluster_ids + picker, helix-level)

**Feature log / anim:** [feature_log_overhaul](project_feature_log_overhaul.md) · [animation_fade](project_animation_fade.md) · [animation_all_reprs](project_animation_all_reprs.md) · [assembly_configurations](project_assembly_configurations.md) (`kf.configuration_id` not wired)

**Display / representation:** [ssdna_flexible_segments](project_ssdna_ball_joints.md) (UNPAIRED runs → arc, free-until-taut) · [photo_mode](project_photo_mode.md) (PBR+HDRI+SSS; PMREM rebake; PT BVH caveat) · [hull_prism](project_hull_prism.md) (distance-LOD boxes/prisms, dsDNA) · [mixed_representation](project_mixed_representation.md) (PLAN: per-nt rep) · [strand_animations](project_strand_animations.md) (`/strand-anim.html`) · [reference_geometry](project_reference_geometry.md) (`is_reference`; translucent, excluded) · [protein_attachment](project_protein_attachment.md) (import PDB proteins → overhangs; P1 shipped, 2–4 unbuilt) · [headless_build](project_headless_build.md) (mouse-free bundle/extrude API) · [sphere_impostors](project_sphere_impostors.md) (bead/atom quads +gl_FragDepth, `?impostors=1`)

**Overhangs / linkers:** [overhang_subdomains](project_overhang_subdomains.md) · [overhang_connections](project_overhang_connections.md) · [overhang_binding_extensions](project_overhang_binding_extensions.md) · [assembly_overhang_bindings](project_assembly_overhang_bindings.md) · [assembly_linker_relax](project_assembly_linker_relax.md) (transform-only guard) · [bond_relax](project_bond_relax.md) · [ball_joint](project_ball_joint.md) (scoped) · [ct_tab](project_ct_tab.md) · [overhang_connections_panel](project_overhang_connections_panel.md) (CT picker) · [ssdna_linker_relax](project_ssdna_linker_relax.md) (FJC) · [oh_binder](project_oh_binder.md) (`binds_overhang_id`) · [overhang_lookup_infra](project_overhang_lookup_infra.md) · [overhang_generation](project_overhang_generation.md) · [mate_connectors](project_mate_connectors.md) · [domain_ends_refactor](project_domain_ends_refactor.md) · [overhang_sequence_display](project_overhang_sequence_display.md) (`assembleOverhangSequence`; auto-RC) · [overhang_duplex_foundation](project_overhang_duplex_foundation.md) (**Duplex graph; read before overhang pairing**) · [overhang_duplex_cluster](project_overhang_duplex_cluster.md) (movable child cluster)

**Primitives / export:** [plates_and_tubes](project_plates_and_tubes.md) (96-well plate + tube segregation; shipped 2026-05-25) · [extrude_preview](project_extrude_preview.md) (Extrude ghost cylinders; 2026-05-25) · [primitive_library](project_primitive_library.md) (Add Primitive panel, circle disc, primitive-on-face; 2026-06-11; circle-on-face deferred) · [stl_export](project_stl_export.md) (Export Surface STL; 2026-05-27)

**Cadnano editor:** [periodic_boundary](project_periodic_boundary.md) (seam mirror view, ±P ghosts, gap readout) · [cadnano_overhaul](project_cadnano_overhaul.md) · [cadnano_resize](project_cadnano_resize.md) · [domain_shift_feature](project_domain_shift_feature.md) (`length_bp` gotcha) · [xover_base_lerp](project_xover_base_lerp.md) (`updateExtraBaseArc` invariant)

**Scaffold / seam / autostaple:** [hinge_autoscaffold](project_hinge_autoscaffold.md) (**REGRESSION GATE `scaffold_invariants.py`**; `build_hinge(k,n)`; **add new autoscaffold paths to ROUTING_ENTRY_POINTS**) · [autoscaffold_single_strand](project_autoscaffold_single_strand.md) (ISSUE-8; in progress) · [scaffold_router](project_scaffold_router.md) (CSP) · [seamless_router](project_seamless_router.md) · [dumbbell_autoscaffold](project_dumbbell_autoscaffold.md) (visual bug) · [autostaple_bugs](project_autostaple_bugs.md) (resolved) · [forced_ligation](project_forced_ligation.md) (merged) · [advanced_staple_disabled](project_advanced_staple_disabled.md)

**Cluster submission (CURC Alpine):** [alpine_cluster_submission](project_alpine_cluster_submission.md) (**5 PHASES SHIPPED + live-validated 2026-07-03**; MD→Alpine SSH+SLURM; review-card submit w/ auto-resources; seam=`MdJob.execution_target`; whole-ladder single sbatch; timeout→resumable, user-driven Resume from mid-segment checkpoint (Duo needs user); learned ns/day; queued ⧗ icon. **Read the "Resume model" block before touching resume.** **Ensemble production (2026-07-07): N multi-seed replicas on amilan — `md_ensemble.py`, parent+child MdJobs w/ `ensemble_seed`, one collapsible item; offline-verified, live submit needs Duo.** **In-sbatch relaxation early-stop (2026-07-07): ladder self-truncates on the node, no Python runner — `remote_cutoff_eval.py` (stdlib Tier B) + `remote_health_eval.py`/staged `md_health` (Tier A WC), gated emission in `slurm_script.generate_sbatch`, `MdJob.early_stop_{relax,tier}`; declash rejected; live-validation owed (Duo).** Open: phantom `atesting_a100` in `alpine_profile()`; GPU NAMD module + `sinfo` discovery unconfirmed)

**MD (NAMD+oxDNA):** [lammps_oxdna](project_lammps_oxdna.md) (**LAMMPS+CG-DNA = CPU-parallel MPI oxDNA for huge assemblies; P1–P6 SHIPPED & live-verified (14.5k-nt, serial); MPI-parallel unverified (needs `libopenmpi-dev`); remaining: force mapping, torque.** `lammps_interface.py`+`lammps_runner.py`+`lammps_job.py`+`routes_lammps.py`+`ui/lammps_jobs_*`) · [oxpy_binding_patch](project_oxpy_binding_patch.md) (oxpy `BaseForce.F0/.dir`; reapply after rebuild) · [proteins_in_simulation](project_proteins_in_simulation.md) (PDB proteins in oxDNA ANM fork; `~/anm-oxdna`) · [oxdna_efield](project_oxdna_efield.md) (E-field per-nt forces+traps; no GPU) · [oxdna_relaxation](project_oxdna_relaxation.md) (CUDA 3-stage relax + surface/anchors; KEYSTONE `fix_diffusion=false`) · [benchmark_tuning](project_benchmark_tuning.md) (MV-BENCH) · [md_engines_panel](project_md_engines_panel.md) (MV-ENGINES)

**MrDNA / ARBD:** [mrdna_arbd_setup](project_mrdna_arbd_setup.md) (install; 5 py3.13 patches) · [mrdna_bead_model](project_mrdna_bead_model.md) (**CRITICAL: 1 DNA bead per bp not per nt**) · [mrdna_panel](project_mrdna_panel.md) (Dynamics-tab CG panel; Fine=`multiresolution_simulation`; curvature ~18% under Dietz — LESSONS A9)

**oxDNA CG:** [oxdna_benchmarks](project_oxdna_benchmarks.md) · [oxdna_extra_bases](project_oxdna_extra_bases.md) (`extra_bases`→ssDNA; **phantom-FENE-bond gotcha**) · [skip_twist_selfconsistency](project_skip_twist_selfconsistency.md) (SQ skip period) · [regional_autorefine](project_regional_autorefine.md) (non-uniform skip) · [skip_twist_curvature_sweep](project_skip_twist_curvature_sweep.md) (exp31 DONE; **CUDA-proxy fails→real CUDA**; exp32=`profile_guided_refine.py`) · [md_twist_validation](project_md_twist_validation.md) (exp33 atomistic)

**Native FEM shape predictor:** [cando_fem](project_cando_fem.md) (CanDo-replica twist/curvature/RMSF FEM, zero export; Phase 0 DONE; revives archived `fem_solver.py`)

**Multi-resolution / CG bridge:** [multiresolution_roadmap](project_multiresolution_roadmap.md) · [crossover_parameterization](project_crossover_parameterization.md) (6-DOF Boltzmann inversion) · [bundle_stiffness_params](project_bundle_stiffness_params.md) (inter-helix stiffness DB; 0T done) · [pipeline_validation_log](pipeline_validation_log.md) · [session_handoff](project_session_handoff.md) (next: mrdna→GROMACS bridge)

**NAMD production / solvation:** [btube_benchmark](project_btube_benchmark.md) (GPU PME disabled; dt trick) · [periodic_cell](project_periodic_cell.md) (5 failure modes) · [namd_solvate](project_namd_solvate.md) (GMX solvate→PSF merge) · [water_shell_carve](project_water_shell_carve.md) (drop bulk water, 12GB GPU) · [3x4sq_md_run](project_3x4sq_md_run.md) · [exp30_18hb_production](project_exp30_18hb_production.md) (topology scale bugs)

**Atomistic skip-site / GROMACS:** [atomistic_skip_backbone](project_atomistic_skip_backbone.md) (`_minimize_backbone_bridge`) · [skip_site_gromacs_fix](project_skip_site_gromacs_fix.md) (constrained EM, gen-vel=no) · [langevin_heating](project_langevin_heating.md) (T(t); 50ps min for skips) · [gromacs_package_structure](project_gromacs_package_structure.md) (`_has_skips`, file layout)

**MD job system / runners:** [md_job_system](project_md_job_system.md) (`md_job.py`, `namd_runner`, `routes_md`) · [md_prep_relaxation](project_md_prep_relaxation.md) (exp29; ENM k-release; read HANDOFF first) · [oxdna_metrics_card](project_oxdna_metrics_card.md) (Graphs+Metrics card; MV-20)

**Simulate-panel UX overhaul (IN PROGRESS):** [simulate_panel_overhaul](project_simulate_panel_overhaul.md) (**one collapsible Simulate section, static engine headers, Periodic MD removed, context Run/Stop/Resume via shared `job_run_control.js`; oxDNA+NAMD wired, LAMMPS/mrDNA/CanDo + master Job-status-card consolidation REMAIN**; `collapsible:false` on `jobs_panel_base`; MV-30/MV-31 owed)

**MD visualization / overlay:** [md_viz_tools](project_md_viz_tools.md) (trajectory + RMSF; **per-frame de-unwrapped 2026-07-02, ~15000× faster**) · [md_panel_status](project_md_panel_status.md) (stale-Universe + PBC) · [md_sidebar_audit](project_md_sidebar_audit.md) (R1–R12; R1/R2 fixed) · [md_live_model_cache](project_md_live_model_cache.md) (single-flight `atomistic_cache.py`)

**Automation / jobs infra:** [staleness_diagnostics](project_staleness_diagnostics.md) (**staleness compares vs LIVE design → check `GET /api/design` first**; `describe_staleness`) · [af25_af26_job_log_sync](project_af25_af26_job_log_sync.md) (COMPLETE) · [job_activity_spinner](project_job_activity_spinner.md) (`/api/jobs/active`) · [job_disk_usage](project_job_disk_usage.md) · [job_archive](project_job_archive.md) (`job_dir()` archive-aware invariant)

**Dev infra:** [dev_server_shutdown_hang](project_dev_server_shutdown_hang.md) (uvicorn `--reload` wedges on status websockets; `--timeout-graceful-shutdown 5`) · [nadoc_overview](project_nadoc_overview.md) (what NADOC is; deformed vs non-deformed export)

**Atomistic / GROMACS / seq:** [atomistic_calibration](project_atomistic_calibration.md) (C1'-C1' OK, 4 issues) · [o3prime_investigation](project_o3prime_investigation.md) (C3'-O3'-P=93.6°, fix=template re-extract) · [gromacs_export](project_gromacs_export.md) (amber99sb-ildn) · [sequence_clear_fix](project_sequence_clear_fix.md) (incomplete; clarify intent) · [log_atomistic_o3prime](log_atomistic_o3prime.md) (debug log)

**Imports / validation:** [sq_importer_fix](project_sq_importer_fix.md) (fixed Apr 20; scaffold open) · [crossover_distance_script](project_crossover_distance_script.md) (`scripts/measure_crossover_distances.py`) · [clash_detector](project_clash_detector.md) (design-layer steric clash: pure `clash_report` + `GET /design/clashes` + "clash" view-tool overlay; **straight-vs-posed exclusion**, thr 0.65 / margin 2.0 nm) · [corner_primitive](project_corner_primitive.md) (headless `build_corner` mitred 90° corner + TWO optimizers: phase-aware length [axial+phase two-constraint] + fold-pose [clash]; co-opt beats hand-tuned reference on BOTH bonds & clashes; validated via clash detector, `steric_clash_count` excludes seam FL bonds; path-B analytic)

**Assembly overhaul (12 phases shipped):** [assembly_overhaul](project_assembly_overhaul.md) · [assembly_part_context](project_assembly_part_context.md) · [assembly_groups](project_assembly_groups.md) (.nass v2) · [gear_relations](project_gear_relations.md) (live RPM) · [belt_paths](project_belt_paths.md) · [route_for_polymerization](project_route_for_polymerization.md) (cadnano editor own api.js) · [polymerize_origami](project_polymerize_origami.md) · [path_to_thousands](project_path_to_thousands.md) (**shared renderer DEFAULT; read before touching assembly**) · [session_recovery](project_session_recovery.md) (multi-doc `doc_context`)

## Maintenance

Finishing a feature → update/close the topic file. Repeated mistakes → add to **LESSONS.md**. Prune stale memory.
