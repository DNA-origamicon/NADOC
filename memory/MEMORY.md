# NADOC — Memory Index

Index only. Open the topic file when relevant. Hard rules + commands live in `CLAUDE.md` (repo root).

## Read first when relevant

- **[LESSONS](LESSONS.md)** — past struggles + anti-patterns by failure mode. Open before debugging or non-trivial changes.
- **[REFERENCE_DNA_TOPOLOGY](REFERENCE_DNA_TOPOLOGY.md)** — strand/scaffold/polarity rules. Always.
- **[tech_debt](project_tech_debt.md)** — ledger of code flagged for review/removal. Check when touching a flagged area.
- **`FEATURE_DEVELOPMENT.md` (repo root)** — module-first guardrails; READ BEFORE ADDING ANY FEATURE. New cohesive logic → new tested module (`initX({deps})→{api}`); main.js only imports+inits+thin wiring (LOC ratchet).
- **[reference_assembly_test_fixture](reference_assembly_test_fixture.md)** — `workspace/Belt_test1.nass` reference assembly fixture. Use for any assembly test.
- **`issues_ledger.md` + `issues_fix_log.md` (repo root)** — "fix next issue" loop: repro-with-test → ask behavior → one phase → don't grow main.js. Read "Next-session handoff".
- **`backend_router_carveup.md` + `backend_router_extraction_log.md` (repo root)** — crud.py/assembly.py → sub-routers loop (`/carve-router`). Metric = back-import surface B≤3.
- **`manual_validation_debt.md` (repo root)** — shift-register of "live gesture NOT hand-checked" caveats. One item/loop: `▶ HEAD` → USER TODO → shift. Push-intake appends `MV-N`.
- **`design_automation_{backlog,log,harness,metrics}.md` (repo root)** — design-automation loop (`/automate-feature`): one op → headless entry point + validation oracle. Read backlog+log per loop; harness+metrics on demand.
- [test_parallelization](project_test_parallelization.md) — `just test`=pytest -n auto (~2.5min); `just test-fast` skips real-sim (~45s); xdist active-design isolation gotcha.

## Path-scoped architecture maps

Live in `.claude/rules/`, load automatically when matching files are read. Don't open manually unless you need cross-area context.

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
- [REFERENCE_CADNANO](REFERENCE_CADNANO.md) — caDNAno v2 import/export specifics
- [REFERENCE_ATOMISTIC](REFERENCE_ATOMISTIC.md) — Phase AA template, PDB/PSF export
- [REFERENCE_FEM](REFERENCE_FEM.md) — DERELICT (FEM+xpbd archived 2026-05-10); revival reference only
- [REFERENCE_DEFORMATION_THEORY](REFERENCE_DEFORMATION_THEORY.md) — DTP-6 / loop-skip theory
- [REFERENCE_SQUARE_LATTICE](REFERENCE_SQUARE_LATTICE.md) — DTP-SQ decisions, scaffold routing
- [REFERENCE_CROSSOVER_AUTOBREAK](REFERENCE_CROSSOVER_AUTOBREAK.md) — crossover/autobreak, ligation, circular strands
- [REFERENCE_PLAYWRIGHT](REFERENCE_PLAYWRIGHT.md) — E2E patterns. Troubleshooting-only, NOT routine verification (too slow)

## User feedback (apply when in scope)

- [aksel_abandoned](feedback_aksel_abandoned.md) — Aksel thermo routing removed; now all-crossovers-minus-seams → break-at-ticks → merge-56
- [crossover_no_reasoning](feedback_crossover_no_reasoning.md) — never reason geometrically about crossovers; mechanical rules only
- [phase_constants_locked](feedback_phase_constants_locked.md) — `_PHASE_*` constants need explicit approval
- [native_files_preserve_positions](feedback_native_files_preserve_positions.md) — native load/import must NOT recenter
- [design_renderer_visibility_rule](feedback_design_renderer_visibility_rule.md) — hiding design touches 4 modules; arcs/extra-bases explicit
- [overhang_definition](feedback_overhang_definition.md) — overhangs = strands embedded in scaffold, free tip on overhang helix
- [interrupt_before_doubting_user](feedback_interrupt_before_doubting_user.md) — ask first; don't preemptively "fix" user observations
- [busy_popup_threshold](feedback_busy_popup_threshold.md) — `_BUSY_POPUP_DELAY_MS = 5000`
- [user_todo_smoke_tests](feedback_user_todo_smoke_tests.md) — manual smoke tests get a `USER TODO` numbered block
- [playwright_fixtures_location](feedback_playwright_fixtures_location.md) — test `.nadoc` → `workspace/playwright_tests/`, deleted when done

**MD / simulation feedback:**
- [c1_pair_builder](feedback_c1_pair_builder.md) — PSF scaffold-before-staples → C1' mispair; sort candidates by distance first
- [wc_calibration](feedback_wc_calibration.md) — template WC pairs have inflated ref distances (>8 Å); use C1' as primary metric
- [cg_pipeline_lessons](feedback_cg_pipeline_lessons.md) — oxDNA segfaults, PCA vs direct override, mrdna 1 bead/bp, per-helix spline
- [gromacs_debugging](feedback_gromacs_debugging.md) — inspect em.gro bond lengths FIRST; dt/gen-vel secondary
- [sd_em_constraints](feedback_sd_em_constraints.md) — SD/steep support constraints=h-bonds; L-BFGS cannot
- [no_parallel_gromacs](feedback_no_parallel_gromacs.md) — parallel `gmx mdrun` slower here; run serially
- [mrdna_gromacs_atomistic](feedback_mrdna_gromacs_atomistic.md) — mrdna atomistic PDB unusable w/ CHARMM27; use NADOC templates
- [mdanalysis_live_reload](feedback_mdanalysis_live_reload.md) — `_reopen()` broken; rebuild Universe from disk for new frames
- [browser_console_debugging](feedback_browser_console_debugging.md) — `console.log` not `.debug`; timestamps stop DevTools collapsing
- [pbc_trajectory_alignment](feedback_pbc_trajectory_alignment.md) — PBC diagnostics; median vs mean centroid; boundary vs wrap
- [bundle_param_extraction](feedback_bundle_param_extraction.md) — topology vs geometry; PCA sign; Euler gimbal; crossover centroid bias
- [namd_pdb_serial_limit](feedback_namd_pdb_serial_limit.md) — NAMD drops HETATM serials ≥10000; cap `(serial-1)%9999+1`
- [namd_cufix_oc_stub](feedback_namd_cufix_oc_stub.md) — MGH validates OTMG NBFIX partners; fix `par_stub_ions_nbfix.str`
- [namd_anisotropic_barostat](feedback_namd_anisotropic_barostat.md) — `useFlexibleCell yes` → Z runaway; use isotropic NPT
- [no_bulk_reformat](feedback_no_bulk_reformat.md) — no repo-wide `ruff format` commits; rely on pre-commit hook

## Active topic files

One line per entry, grouped by area. Open the topic file for detail.

**Cluster/joints:** [cluster_joints](project_cluster_joints.md) · [cluster_reconcile](project_cluster_reconcile.md) · [cluster_autodetect](project_cluster_autodetect.md) (scaffold+geometry, hull render) · [deformation_cluster_scope](project_deformation_cluster_scope.md) (bend/twist cluster_ids picker, helix-level)
**Feature log/anim:** [feature_log_overhaul](project_feature_log_overhaul.md) (snapshot log, tabbed sidebar) · [animation_fade](project_animation_fade.md) · [animation_all_reprs](project_animation_all_reprs.md) (pre-baked CG/atomistic/surface) · [assembly_configurations](project_assembly_configurations.md) (`kf.configuration_id` not wired)
- [ssdna_flexible_segments](project_ssdna_ball_joints.md) — mark UNPAIRED runs flexible → fixed-length arc → free-until-taut PBD cluster drag. Shipped 2026-05-30. (vs [ball_joint](project_ball_joint.md), unbuilt.)
- [photo_mode](project_photo_mode.md) — PBR+HDRI+SSS+fluorophore lights + tiled export; PMREM rebake; PT BVH caveat.
- [hull_prism](project_hull_prism.md) — distance-LOD grey boxes/prisms, dsDNA-only, culls+margin, overhang face markers. `joint_renderer.js`; assembly LOD bucket 3.
- [mixed_representation](project_mixed_representation.md) — PLAN ONLY: different reps per region of ONE structure; resolve rep PER NUCLEOTIDE → run-segments.
- [protein_attachment](project_protein_attachment.md) — import PDB proteins, attach to overhangs (display). Phase 1 SHIPPED 2026-05-22; Phases 2–4 not built.
- [strand_animations](project_strand_animations.md) — display-only Help page `/strand-anim.html`, un/hybridization ball-and-slab. `frontend/src/strand-anim/`. 2026-05-29.
- [reference_geometry](project_reference_geometry.md) — per-strand `is_reference`: features ignore, exports exclude, freeze, translucent. Shipped 2026-05-23.
- [headless_build](project_headless_build.md) — mouse-free bundle/extrude API + conftest test-design builders. `test_headless_build.py`.
- [sphere_impostors](project_sphere_impostors.md) — beads/atoms as camera-facing quads + gl_FragDepth (~70× fewer tris). `?impostors=1`. Phase A+B 2026-05-22; C+photo TODO.
**Overhangs/linkers:** [overhang_subdomains](project_overhang_subdomains.md) (SubDomain+thermo) · [overhang_connections](project_overhang_connections.md) (ss+ds linkers, relax) · [overhang_binding_extensions](project_overhang_binding_extensions.md) (OverhangBinding 0/1/N-DOF, CT Bound col) · [assembly_overhang_bindings](project_assembly_overhang_bindings.md) (cross-part + Manager popup) · [assembly_linker_relax](project_assembly_linker_relax.md) (cross-part ds linker → coaxial; transform-only guard) · [bond_relax](project_bond_relax.md) (`POST /design/relax-bond` 0/1/N-DOF) · [ball_joint](project_ball_joint.md) (scoped, no code) · [ct_tab](project_ct_tab.md) (Connection Types tab, bridge_sequence) · [overhang_connections_panel](project_overhang_connections_panel.md) (sidebar CT picker, v1 2026-06-28; old modal kept) · [ssdna_linker_relax](project_ssdna_linker_relax.md) (FJC slab+SAW, R_ee×Rg) · [oh_binder](project_oh_binder.md) (`Domain.binds_overhang_id`; scaffold-coverage fix) · [overhang_lookup_infra](project_overhang_lookup_infra.md) (4-stage) · [overhang_generation](project_overhang_generation.md) (Johnson 5-mer) · [mate_connectors](project_mate_connectors.md) (cache-invalidation/dup issues) · [domain_ends_refactor](project_domain_ends_refactor.md) (coverage-map blunt-ends) · [overhang_sequence_display](project_overhang_sequence_display.md) (assembled seq; `reassign_if_sequenced` auto-RC, 2026-06-29)
- [overhang_duplex_foundation](project_overhang_duplex_foundation.md) — Proposal-B `Duplex` graph (register edges) replacing OverhangBinding. **Read before touching overhang pairing.** (locked 2026-06-30)
- [overhang_duplex_cluster](project_overhang_duplex_cluster.md) — duplex pose → sidebar child cluster + rotation-point + taut/MOVABLE-LINK drag; selection-driven Move/Rotate (auto-open, ±45°, snap); connection-tether move (2026-07-01)
- [plates_and_tubes](project_plates_and_tubes.md) — "Plates and tubes" tab both editors: 96-well + auto-fill + tube segregation. `Design.plate_layout`. 2026-05-25.
- [extrude_preview](project_extrude_preview.md) — "Extrude" toggle → translucent ghost cylinders. Display-only. 2026-05-25.
- [primitive_library](project_primitive_library.md) — Add Primitive panel (6hb/18hb), placement snap, circle disc, primitive-on-FACE. 2026-06-11. Only circle-on-face deferred (ASK).
- [stl_export](project_stl_export.md) — File→Export Surface STL, binary, auto-scaled 200mm, design-only. 2026-05-27.
**Cadnano editor:** [periodic_boundary](project_periodic_boundary.md) (seam mirror: 2 sliders, ±P ghosts, gap readout) · [cadnano_overhaul](project_cadnano_overhaul.md) · [cadnano_resize](project_cadnano_resize.md) · [domain_shift_feature](project_domain_shift_feature.md) (`length_bp` gotcha) · [xover_base_lerp](project_xover_base_lerp.md) (`updateExtraBaseArc` invariant)
**Scaffold/seam/autostaple:** [hinge_autoscaffold](project_hinge_autoscaffold.md) (REGRESSION GATE `scaffold_invariants.py`=seams+≥3bp margin; hinge routers seamed+seamless for even k×N; **add new paths to ROUTING_ENTRY_POINTS**) · [autoscaffold_single_strand](project_autoscaffold_single_strand.md) (ISSUE-8: uniform sub-bundles + 2-opt splice; in progress) · [scaffold_router](project_scaffold_router.md) (CSP) · [seamless_router](project_seamless_router.md) · [dumbbell_autoscaffold](project_dumbbell_autoscaffold.md) (visual bug) · [autostaple_bugs](project_autostaple_bugs.md) (resolved) · [forced_ligation](project_forced_ligation.md) (merged) · [advanced_staple_disabled](project_advanced_staple_disabled.md) (optimizer too slow)
**MD (NAMD+oxDNA):**
- [oxpy_binding_patch](project_oxpy_binding_patch.md) — `~/oxDNA` oxpy patched to expose `BaseForce.F0`/`.dir`; git-untracked, reapply 2 lines + make after rebuild.
- [proteins_in_simulation](project_proteins_in_simulation.md) — PDB proteins in oxDNA (ANM fork DNANM) + MD (CHARMM36+Cα ENM). CPU fork `~/anm-oxdna/...`; CUDA deferred.
- [oxdna_efield](project_oxdna_efield.md) — E-field via per-nt string forces + anchor traps. SHIPPED 2026-06-18. TODO: deflection viz + real GPU.
- [oxdna_relaxation](project_oxdna_relaxation.md) — oxDNA CUDA 3-stage relax panel + NAMD-seed; §25 hard surface+anchors+`/run`+`fix_diffusion=false`. NOT GPU-verified.
- [benchmark_tuning](project_benchmark_tuning.md) (proxy trials → `hardware_defaults[host]`, MV-BENCH) · [md_engines_panel](project_md_engines_panel.md) (Help▸MD Engines install/status, `core/engines.py`, MV-ENGINES)
**MrDNA / ARBD (CG reference engine):** [mrdna_arbd_setup](project_mrdna_arbd_setup.md) (install paths, py3.13 patches, re-patch script) · [mrdna_bead_model](project_mrdna_bead_model.md) (CRITICAL: 1 DNA bead per bp not per nt; per-helix) · [mrdna_panel](project_mrdna_panel.md) (Dynamics-tab job panel mirroring oxDNA: Coarse/Fine buttons, deform+CG-beads-with-bonds displays, ds-OH/linker duplexes; Fine=real multiresolution_simulation; curvature readout analytic-vs-sim — mrDNA under-reproduces Dietz curvature ~18%, see LESSONS A9; MV-MRDNA-JOBS)
**oxDNA CG:** [oxdna_benchmarks](project_oxdna_benchmarks.md) (CPU timing, step counts, input keys, box) · [oxdna_extra_bases](project_oxdna_extra_bases.md) (`Crossover.extra_bases` ssDNA inserts; phantom-FENE gotcha) · [skip_twist_selfconsistency](project_skip_twist_selfconsistency.md) (tune SQ skip period to analytic; `geometry_rmsd` gate) · [regional_autorefine](project_regional_autorefine.md) (Phase 5 non-uniform skip placement; 5.0/5.1 green, 5.2–5.4 pending) · [skip_twist_curvature_sweep](project_skip_twist_curvature_sweep.md) (exp31 DONE: incremental-gap wins; exp32=`profile_guided_refine.py`; benchmark CUDA-proxy fails→use real CUDA) · [md_twist_validation](project_md_twist_validation.md) (exp33 atomistic NAMD validation of oxDNA twist, auto after exp32)
**Multi-resolution / CG bridge:** [multiresolution_roadmap](project_multiresolution_roadmap.md) (ARBD/mrdna reference CG; phase checklist) · [crossover_parameterization](project_crossover_parameterization.md) (2hb_xover_val, 6-DOF Boltzmann inversion) · [bundle_stiffness_params](project_bundle_stiffness_params.md) (inter-helix stiffness DB; 0T done, 1T pending) · [pipeline_validation_log](pipeline_validation_log.md) · [session_handoff](project_session_handoff.md) (next: mrdna→GROMACS; NADOC→mrdna design bridge)
**NAMD production / solvation:** [btube_benchmark](project_btube_benchmark.md) (GROMACS vs NAMD; dt trick) · [periodic_cell](project_periodic_cell.md) (21bp cell; 5 failure modes) · [namd_solvate](project_namd_solvate.md) (GMX solvate → PSF merge; 4 bugs) · [water_shell_carve](project_water_shell_carve.md) (drop bulk water >N Å for 12GB GPU) · [3x4sq_md_run](project_3x4sq_md_run.md) (SQ health-fail root cause) · [exp30_18hb_production](project_exp30_18hb_production.md) (224-strand to k=0; topology scale bugs)
**Atomistic skip-site / GROMACS:** [atomistic_skip_backbone](project_atomistic_skip_backbone.md) (`_minimize_backbone_bridge`) · [skip_site_gromacs_fix](project_skip_site_gromacs_fix.md) (constrained EM, gen-vel=no, 50ps NVT) · [langevin_heating](project_langevin_heating.md) (T(t); 50ps min for skips) · [gromacs_package_structure](project_gromacs_package_structure.md) (vars, MDP regex, `_has_skips`)
**MD job system / runners:** [md_job_system](project_md_job_system.md) (`md_job.py`, `namd_runner`, `routes_md`; REST `/api/md/`) · [md_prep_relaxation](project_md_prep_relaxation.md) (exp29 prep harness; ENM k-release; read HANDOFF) · [oxdna_metrics_card](project_oxdna_metrics_card.md) (oxDNA "Graphs and Metrics" card: twist/curvature/base-pairing graphs over a job/lineage + PNG/CSV + ETA; `production_metric_series`, `routes_oxdna_metrics.py`, `metric_graph.js`; 2026-07-02, MV-20)
**MD visualization / overlay:** [md_viz_tools](project_md_viz_tools.md) (trajectory + RMSF; reuse oxDNA controller) · [md_panel_status](project_md_panel_status.md) (stale-Universe + PBC artifacts) · [md_sidebar_audit](project_md_sidebar_audit.md) (findings R1–R12; R1/R2 fixed) · [md_live_model_cache](project_md_live_model_cache.md) (per-load rebuild→20GB; fixed w/ `atomistic_cache.py`)
**Automation / jobs infra:** [af25_af26_job_log_sync](project_af25_af26_job_log_sync.md) (roll/return lifecycle oracle; COMPLETE) · [job_activity_spinner](project_job_activity_spinner.md) (`/api/jobs/active` + concurrency guard) · [job_disk_usage](project_job_disk_usage.md) (welcome disk column) · [job_archive](project_job_archive.md) (move off-workspace; `job_dir()` archive-aware)
**Dev infra:** [dev_server_shutdown_hang](project_dev_server_shutdown_hang.md) (uvicorn --reload wedges on status ws; `--timeout-graceful-shutdown 5`) · [nadoc_overview](project_nadoc_overview.md) (what NADOC is, its layers)
**Atomistic/GROMACS/seq:** [atomistic_calibration](project_atomistic_calibration.md) (C1'-C1' OK, 4 issues) · [o3prime_investigation](project_o3prime_investigation.md) (C3'-O3'-P=93.6°, fix=template re-extract) · [gromacs_export](project_gromacs_export.md) (amber99sb-ildn) · [sequence_clear_fix](project_sequence_clear_fix.md) (incomplete; clarify) · [log_atomistic_o3prime](log_atomistic_o3prime.md) (debug log)
**Imports/validation:** [sq_importer_fix](project_sq_importer_fix.md) (fixed; scaffold open) · [crossover_distance_script](project_crossover_distance_script.md) (`scripts/measure_crossover_distances.py`)
**Assembly overhaul (12 phases shipped):** [assembly_overhaul](project_assembly_overhaul.md) (planning) · [assembly_part_context](project_assembly_part_context.md) (part-context UI)
- [assembly_groups](project_assembly_groups.md) — PartGroups (Group/Ungroup/Dup/Cascade + nested + .nass v2). 2026-05-28. Deferred: Escape-to-pop.
- [gear_relations](project_gear_relations.md) — couple two revolute joints by ratio, live RPM spin. Display-only. 2026-05-29.
- [belt_paths](project_belt_paths.md) — "Define Belt Path" wraps two mated pulleys, preview tube. Display-only Phase 1, 2026-06-01.
- [route_for_polymerization](project_route_for_polymerization.md) — Routing menu: fill scaffold ends, every bridge `is_periodic_seam`. Cadnano editor has OWN api.js. 2026-06-10.
- [polymerize_origami](project_polymerize_origami.md) — Polymerize Origami (chain mated parts) + Polymerize Periodic (`periodic_polymer.py`). 2026-05-15/26.
- [path_to_thousands](project_path_to_thousands.md) — assembly scale refactor Phases 0–7 DONE (shared instancing, O(N) backend, .nass v2). Shared renderer DEFAULT. **Read before touching assembly.**
- [session_recovery](project_session_recovery.md) — P1 server-restart recovery (`.session/` autosave + `/health`); P2 multi-doc backend (`doc_id` ContextVar, `/documents`, per-tab). SHIPPED 2026-05-23.

## Maintenance

Finishing a feature: update/close the topic file. Repeated mistakes → **LESSONS.md** under the matching category. Stale memory misleads — prune ruthlessly.
