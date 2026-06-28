# NADOC — Memory Index

Index only. Open the topic file when relevant. Hard rules and commands live in `/home/joshua/NADOC/CLAUDE.md`.

## Read first when relevant

- **[LESSONS](LESSONS.md)** — past struggles + anti-patterns, categorized by failure mode. Open before debugging or proposing non-trivial changes.
- **[REFERENCE_DNA_TOPOLOGY](REFERENCE_DNA_TOPOLOGY.md)** — strand/scaffold/polarity rules. Always.
- **[tech_debt](project_tech_debt.md)** — ledger of code flagged for review/removal (e.g. legacy overhang Bind/Unbind button). Check when touching a flagged area.
- **`FEATURE_DEVELOPMENT.md` (repo root)** — module-first guardrails; READ BEFORE ADDING ANY FEATURE. Anti-backslip law: new cohesive logic → a new tested module (`initX({deps})→{api}`, Sprout Method); `main.js` only gains imports + factory inits + thin wiring; a feature commit leaves `main.js` LOC flat-or-lower (the ratchet).
- **[reference_assembly_test_fixture](reference_assembly_test_fixture.md)** — `workspace/Belt_test1.nass` is the reference-standard assembly fixture (parts+groups+mates+polymers+belts+parts-on-belts). Use for any assembly test/exercise.
- **`issues_ledger.md` + `issues_fix_log.md` (repo root)** — the "fix next issue" loop (UX bugs/tech debt): repro-with-a-test FIRST → ask desired behavior → one phase → don't grow main.js. Push-intake: carve-up/fix sessions add `ISSUE-N` dossiers. Read its "Next-session handoff".
- **`backend_router_carveup.md` + `backend_router_extraction_log.md` (repo root)** — backend god-file carve-up loop for `crud.py`/`assembly.py` → small FastAPI sub-routers (`routes_<area>.py`) + `backend/core` helpers. Invoke `/carve-router crud|assembly`. Pass metric = back-import surface `B` (gate B≤3), NOT LOC. Read the carveup map's `## Next-session handoff`.
- **`manual_validation_debt.md` (repo root)** — shift-register of features shipped with the "live gesture/visual NOT hand-checked" caveat. One item/loop: read `▶ HEAD` → USER TODO block → shift → commit. Push-intake: carve-up/fix loops append PENDING `MV-N` rows. `## Next loop` pointer in-file.
- **`design_automation_{backlog,log,harness,metrics}.md` (repo root)** — the design-automation loop, invoked by **`/automate-feature`**. Each session gives one UI-only/API-less op a headless entry point + a reusable validation oracle (toward automated validation + text-to-DNA-origami). Anti-shovel metric = "validation gained, not a passthrough". New code → `headless_*`/`backend/core`, never a god-file. **Four-file layout (split 2026-06-25 to cut per-loop context):** read `backlog` (protocol + ranked items + ≤8-line `## Next-session handoff`) + `log` (oracle catalog + lessons + difficulties) per loop; open `harness` (do-not-rebuild wrapper signatures + gotchas) and `metrics` (per-item rows + data fits) **on demand only**, never wholesale.

- [test_parallelization](project_test_parallelization.md) — backend suite runs parallel (`just test` = `pytest -n auto --dist loadfile`, ~2.5min); `just test-fast` skips slow real-sim tests (~45s); slow registry in `tests/conftest.py`; global active-design isolation gotcha under xdist.

## Path-scoped architecture maps

These live in `/home/joshua/NADOC/.claude/rules/` and load automatically when matching files are read. Don't open them manually unless you need cross-area context.

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
- [REFERENCE_FEM](REFERENCE_FEM.md) — DERELICT: FEM + xpbd archived 2026-05-10; revival-planning reference only
- [REFERENCE_DEFORMATION_THEORY](REFERENCE_DEFORMATION_THEORY.md) — DTP-6 / loop-skip theory
- [REFERENCE_SQUARE_LATTICE](REFERENCE_SQUARE_LATTICE.md) — DTP-SQ decisions, scaffold routing
- [REFERENCE_CROSSOVER_AUTOBREAK](REFERENCE_CROSSOVER_AUTOBREAK.md) — crossover/autobreak pipeline, ligation, circular strands
- [REFERENCE_PLAYWRIGHT](REFERENCE_PLAYWRIGHT.md) — E2E test patterns + helpers. **Troubleshooting-only tool, NOT routine verification** (too slow for iteration); use only to repro a bug or clarify unclear behavior

## User feedback (apply when in scope)

- [aksel_abandoned](feedback_aksel_abandoned.md) — Aksel thermodynamic staple routing removed (didn't work, user dislikes it); routing is now all-crossovers-minus-seams → break-at-ticks → merge-to-56
- [crossover_no_reasoning](feedback_crossover_no_reasoning.md) — never reason geometrically about crossover placement; mechanical rules only
- [phase_constants_locked](feedback_phase_constants_locked.md) — `_PHASE_*` constants require explicit approval
- [native_files_preserve_positions](feedback_native_files_preserve_positions.md) — `/design/load` and `/design/import` (native) must NOT recenter
- [design_renderer_visibility_rule](feedback_design_renderer_visibility_rule.md) — hiding design touches 4 modules; arcs/extra-bases need explicit handling
- [overhang_definition](feedback_overhang_definition.md) — overhangs are strands embedded in scaffold, free tip on overhang helix
- [interrupt_before_doubting_user](feedback_interrupt_before_doubting_user.md) — ask first; do not preemptively "fix" user observations
- [busy_popup_threshold](feedback_busy_popup_threshold.md) — `_BUSY_POPUP_DELAY_MS = 5000`
- [user_todo_smoke_tests](feedback_user_todo_smoke_tests.md) — manual smoke tests get a `USER TODO` block with numbered steps
- [playwright_fixtures_location](feedback_playwright_fixtures_location.md) — test-generated `.nadoc` files live in `workspace/playwright_tests/`, deleted when no longer needed

## Active topic files

One line per entry, grouped by area (bold lead). Open the topic file for detail.

**Cluster/joints:** [cluster_joints](project_cluster_joints.md) (local-frame storage, Plan B) · [cluster_reconcile](project_cluster_reconcile.md) (incremental membership) · [cluster_autodetect](project_cluster_autodetect.md) (scaffold+geometry dual, hull render) · [deformation_cluster_scope](project_deformation_cluster_scope.md) (bend/twist `cluster_ids` + picker, helix-level only)
**Feature log/anim:** [feature_log_overhaul](project_feature_log_overhaul.md) (snapshot log, edit endpoint, tabbed sidebar) · [animation_fade](project_animation_fade.md) (per-bp scale fade) · [animation_all_reprs](project_animation_all_reprs.md) (pre-baked CG/atomistic/surface) · [assembly_configurations](project_assembly_configurations.md) (poses+configs; `kf.configuration_id` not wired)
- [ssdna_flexible_segments](project_ssdna_ball_joints.md) — mark UNPAIRED runs flexible → fixed-length geometric arc between EXISTING clusters → real-time "ssDNA constrained" cluster drag (free-until-taut PBD in cluster_gizmo). Replaced the auto-cut ball-joint+Powell. Shipped 2026-05-30. (Distinct from [ball_joint](project_ball_joint.md), unbuilt.)
- [photo_mode](project_photo_mode.md) — PBR + HDRI + SSS + fluorophore PointLights + tiled high-res export; cross-context PMREM rebake; PT BVH-rebuild caveat.
- [hull_prism](project_hull_prism.md) — Hull Prism distance-LOD: per-extrusion grey boxes / per-cluster prisms, dsDNA-only, culls + margin slider, raycast overhang face markers. Design view `joint_renderer.js`; ported to assembly shared renderer as LOD bucket 3.
- [mixed_representation](project_mixed_representation.md) — PLAN ONLY (2026-06-02): different reps in different regions of ONE structure (cylinder bulk + full focal duplex). Keystone: resolve rep PER NUCLEOTIDE → contiguous run-segments. Photo-mode export must honor overrides.
- [protein_attachment](project_protein_attachment.md) — import PDB proteins + attach to overhangs (display layer). Phase 1 SHIPPED 2026-05-22 (import/library/all-atom, CHARMM, handle is auxiliary-anchor not a strand). Phases 2–4 NOT built.
- [strand_animations](project_strand_animations.md) — standalone display-only Help page (`/strand-anim.html`) animating un/hybridization in ball-and-slab. Unzip 2-strand / TMSD 3-strand × straight/helical, per-base melt. No backend. `frontend/src/strand-anim/`. Shipped 2026-05-29.
- [reference_geometry](project_reference_geometry.md) — per-strand `is_reference`: auto-features ignore, exports/validation exclude, bend/twist freeze, rendered translucent (true-alpha shader + cadnano globalAlpha). Two-pattern exclusion; mixed-helix freeze caveat. Shipped 2026-05-23.
- [headless_build](project_headless_build.md) — mouse-free bundle/extrude API (`backend/api/headless_build.py`, AI-design seed) + conftest test-design builders (teeth/6hb/18hb/mini_hinge) replaying feature logs. Pins in `test_section_router.py`+`test_headless_build.py`.
- [sphere_impostors](project_sphere_impostors.md) — beads/atoms as 2-tri camera-facing quads ray-painting a lit sphere + gl_FragDepth (~70× fewer tris). onBeforeCompile MeshPhong patch, `impostor_material.js`. Phase A+B DONE 2026-05-22 (`?impostors=1`); C atomistic + photo-mode revert TODO.
**Overhangs/linkers:** [overhang_subdomains](project_overhang_subdomains.md) (SubDomain model+CRUD+thermo, 2026-05-10) · [overhang_connections](project_overhang_connections.md) (ss+ds linkers, bridge nucs, relax) · [overhang_binding_extensions](project_overhang_binding_extensions.md) (OverhangBinding cluster-pose 0/1/N-DOF + bind-relax log + CT Bound column) · [assembly_overhang_bindings](project_assembly_overhang_bindings.md) (v1 cross-part bindings + Overhangs Manager popup, 2026-05-14) · [assembly_linker_relax](project_assembly_linker_relax.md) (cross-part ds linker relax into coaxial duplex; transform-only guard gotcha) · [bond_relax](project_bond_relax.md) (generic Relax Bond `POST /design/relax-bond`, crossover/ligation/linker/strand_arc 0/1/N-DOF) · [ball_joint](project_ball_joint.md) (scoped only, no code) · [ct_tab](project_ct_tab.md) (Connection Types tab, bridge_sequence, live Sequence col) · [ssdna_linker_relax](project_ssdna_linker_relax.md) (FJC slab+SAW, R_ee×Rg picker) · [oh_binder](project_oh_binder.md) (OH-binder type + `Domain.binds_overhang_id`; RC sync; KEYSTONE scaffold-coverage fix) · [overhang_lookup_infra](project_overhang_lookup_infra.md) (4-stage pipeline) · [overhang_generation](project_overhang_generation.md) (Johnson 5-mer Gen) · [mate_connectors](project_mate_connectors.md) (cache-invalidation + dup-connector issues) · [domain_ends_refactor](project_domain_ends_refactor.md) (coverage-map blunt-ends)
- [plates_and_tubes](project_plates_and_tubes.md) — "Plates and tubes" tab BOTH editors: 96-well plate + auto-fill (group→color→length) + tube segregation (mod or >60 nt → 250 nmol+HPLC) + drag moves. `Design.plate_layout`, shared `ui/plate_view.js`. Shipped 2026-05-25.
- [extrude_preview](project_extrude_preview.md) — right-sidebar "Extrude" toggle → translucent ghost cylinders (slice-plane in `slice_plane.js` + overhang dialog ghost in `main.js`). Display-only. Shipped 2026-05-25.
- [primitive_library](project_primitive_library.md) — Tools→Add Primitive → Primitives panel (6hb/18hb cards + hover-GIF previews). Placement (snap→lattice `bundle-segment`), parametric circle disc (`POST /design/circle-segment`), primitive-on-FACE (flat+bent continuation) shipped 2026-06-11. Gestures → MV-CIRCLE / MV-PRIM-FACE. Only circle-disc-on-face deferred (ASK first).
- [stl_export](project_stl_export.md) — File→"Export Surface STL": binary STL of the molecular surface (`stl_export.py`+`GET /design/export/stl`), auto-scaled 200 mm, design-only. ~6 non-manifold edges slicers auto-repair. Shipped 2026-05-27.
**Cadnano editor:** [periodic_boundary](project_periodic_boundary.md) (seam mirror view: 2 red sliders, ±P ghosts, wrapped-bp ruler, live-proxy edit, gap readout) · [cadnano_overhaul](project_cadnano_overhaul.md) (Phase 1 + remaining) · [cadnano_resize](project_cadnano_resize.md) (drag-to-resize issues) · [domain_shift_feature](project_domain_shift_feature.md) (drag-to-move, `length_bp` gotcha) · [xover_base_lerp](project_xover_base_lerp.md) (`updateExtraBaseArc` invariant)
**Scaffold/seam/autostaple:** [hinge_autoscaffold](project_hinge_autoscaffold.md) (scaffold-routing REGRESSION GATE `scaffold_invariants.py` = seams-present + ≥3bp ssDNA margin, parametrized over every entry point; + hinge routers `hinge_ladder.py`/`hinge_weave_router.py` routing 1 strand through FL gap-bridges for ARBITRARY even k×N — **SEAMED** (`auto_scaffold_seamed`, double-pass weave + seam max-matching) AND **SEAMLESS** (`auto_scaffold_seamless`, single-pass Hamiltonian-cycle + buried nick), both self-gated; `build_hinge(k,n)` generates kxN primitives. **Add new autoscaffold paths to ROUTING_ENTRY_POINTS.**) · [autoscaffold_single_strand](project_autoscaffold_single_strand.md) (ISSUE-8: crossovers CANNOT merge fragments; path = uniform sub-bundles + 2-opt splice; build in progress) · [scaffold_router](project_scaffold_router.md) (CSP, bulge stub) · [seamless_router](project_seamless_router.md) (closing zig) · [dumbbell_autoscaffold](project_dumbbell_autoscaffold.md) (visual bug; resume guide inside) · [autostaple_bugs](project_autostaple_bugs.md) (resolved Apr 11) · [forced_ligation](project_forced_ligation.md) (merged Apr 12) · [advanced_staple_disabled](project_advanced_staple_disabled.md) (fallback to basic; optimizer too slow)
**MD (NAMD+oxDNA):**
- [oxpy_binding_patch](project_oxpy_binding_patch.md) — user's `~/oxDNA` oxpy is locally patched to expose `BaseForce.F0`/`.dir` (live-field steering, AF-21); git-untracked → reapply 2 lines + `make` after any clean rebuild.
- [proteins_in_simulation](project_proteins_in_simulation.md) — PLAN + Phase 1 (2026-06-19): PDB proteins in oxDNA (ANM fork `DNANM`, Cα ANM, mutual_trap) + MD (CHARMM36 + Cα ENM). CPU fork at `~/anm-oxdna/oxDNA/build/bin/oxDNA`; CUDA deferred. Protein particles FIRST in hybrid topology.
- [oxdna_efield](project_oxdna_efield.md) — E-field via per-nt `string` forces + anchor traps. SHIPPED 2026-06-18 (gizmo + anchor UI + "⚡ Run field" → `POST /oxdna/jobs/{id}/field`; `measure_field_response` oracle; field-deflecting mock, no GPU). TODO: deflection-map viz + real GPU validation.
- [oxdna_relaxation](project_oxdna_relaxation.md) — SHIPPED: oxDNA CUDA 3-stage relax sub-panel + NAMD-seed handoff. §25 (2026-06-18): hard surface + Anchors + consolidated `POST /oxdna/jobs/{id}/run` + relax-on-surface + KEYSTONE `fix_diffusion=false` for absolute-coord forces. NOT GPU-verified.
- [benchmark_tuning](project_benchmark_tuning.md) (proxy trials → fastest backend in `metadata.hardware_defaults[host]`, MV-BENCH) · [md_engines_panel](project_md_engines_panel.md) (Help▸MD Engines install/status + auto-build, `core/engines.py`+`engine_install.py`, MV-ENGINES)
**Atomistic/GROMACS/seq:** [atomistic_calibration](project_atomistic_calibration.md) (C1'-C1' OK, 4 issues) · [o3prime_investigation](project_o3prime_investigation.md) (C3'-O3'-P=93.6°, fix=template re-extract) · [gromacs_export](project_gromacs_export.md) (v1, amber99sb-ildn) · [sequence_clear_fix](project_sequence_clear_fix.md) (incomplete; clarify intent) · [log_atomistic_o3prime](log_atomistic_o3prime.md) (long debug log, reference)
**Imports/validation:** [sq_importer_fix](project_sq_importer_fix.md) (fixed Apr 20; scaffold open) · [crossover_distance_script](project_crossover_distance_script.md) (`scripts/measure_crossover_distances.py`)
**Assembly overhaul (12 phases shipped):** [assembly_overhaul](project_assembly_overhaul.md) (planning) · [assembly_part_context](project_assembly_part_context.md) (part-context UI; feature-log/anim deferred)
- [assembly_groups](project_assembly_groups.md) — PowerPoint-style PartGroups (Group/Ungroup/Dup/Cascade-delete/Move + nested + .nass v2). Shipped 2026-05-28. Gizmo-on-group + click-through state-machine + shared-renderer visibility overlay fast path. Deferred: Escape-to-pop.
- [gear_relations](project_gear_relations.md) — couple two revolute joints by ratio/invert, live RPM spin (`kinematics_ticker.js`). Display-only. "Create Mate" type=gear. Shipped 2026-05-29.
- [belt_paths](project_belt_paths.md) — "Define Belt Path" wraps two revolute-mated pulleys, preview tube + `Assembly.belt_paths`. Display-only Phase 1, 2026-06-01; mating/anim deferred.
- [route_for_polymerization](project_route_for_polymerization.md) — Routing menu (both editors): fill bare scaffold ends, EVERY bridge `is_periodic_seam` → end-to-end polymerizable. `derive_periodic_delta` oracle. Cadnano editor has its OWN api.js. Shipped 2026-06-10.
- [polymerize_origami](project_polymerize_origami.md) — Polymerize Origami (chain mated parts from seed joint, 2026-05-15) + Polymerize (Periodic) (chain ONE periodic part, no mate, `periodic_polymer.py` + POST /assembly/polymerize-periodic, 2026-05-26).
- [path_to_thousands](project_path_to_thousands.md) — assembly scale refactor, Phases 0–7 DONE (shared GPU instancing, O(N) backend, .nass v2). Shared renderer is DEFAULT (`?shared=0` opts out). Stubbed: pickPartJoint, rebuildLinkers. **Read before touching assembly code.**
- [session_recovery](project_session_recovery.md) — Phases 1+2 SHIPPED 2026-05-23: P1 server-restart silent recovery (`.session/` autosave + `/health` beacon + connection badge); P2 multi-document backend (`doc_id` via `doc_context` ContextVar + ASGI middleware, `POST/GET/DELETE /documents`, per-tab doc id, New/Open spawn a tab). Default doc unchanged.

## Maintenance

When finishing a feature: update or close out the relevant topic file. When repeated mistakes happen, add an entry to **LESSONS.md** under the matching category. Stale memory misleads future sessions — prune ruthlessly.
