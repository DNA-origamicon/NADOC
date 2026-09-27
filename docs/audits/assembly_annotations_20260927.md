# Assembly annotation parity — 2026-09-27

Scope: annotation targets limited by user request to specific part instances and
specific overhangs. Source-part molecular selections retain their existing behavior.

| Contract | Result |
| --- | --- |
| Annotation tab and existing text/icon/style/size/transparency/manual-placement controls | Shared panel/controller/overlay enabled for assemblies |
| Target identity | Assembly part and overhang refs include instance ID; repeated sources remain distinct |
| Use selection | Selected overhangs take priority, then individually multi-selected parts, then active part; groups and part-editor refs excluded |
| Live rendering | Source-local beads resolve through live instance transforms; overhang matching reuses part domain matching |
| Missing/hidden targets | Highlight/leader disappear; note remains as an unanchored callout, matching part missing-target behavior |
| Automatic placement | Adapted: visible instance bounding spheres provide conservative occupancy without expanding all assembly nucleotides |
| Persistence | `.nass` fields and lightweight metadata PUT; source `.nadoc` data untouched |
| Undo/redo/history seek | Current annotation metadata retained; annotation edits add no topology/history entry |
| Response ordering | Shared revision tracker protects metadata from older assembly snapshots; sequential save queue recovers after failure |
| Prepared sharing | Existing callout capture and highlight UUID mechanism reused |
| Broader molecular/group annotation targets | Excluded at user request |

Only annotated targets allocate transformed backbone entries. Main composition-root
change for this task: +1 line passing the assembly renderer to the existing factory.

Verification results are recorded below. Browser fixtures are
`__e2e__` assemblies with copies of `Examples/hingeV4.nadoc` (import materializes the inline source as `workspace/__e2e__annotation_source.nadoc`); original files
are read-only. Global teardown removes workspace artifacts and the cleanup reporter
removes browser output. The part regression uses its existing `__e2e__` scaffolded
part with the same cleanup mechanisms.

## Backend validation and timing triage

Focused annotation API: **7 passed**. Assembly API regression: **77 passed**.
`just lint`: passed. `just test-smart`: **FAST**, **9,288 passed, 15 skipped, 9 failed**.
Eight failures match the prior visualization audit: seven unavailable external photoproduct-review evidence fixtures and the CPD snapshot coordinate golden mismatch. The ninth, Alpine reconnect timing, passed in isolation. No scientific evidence or geometry goldens were changed.

Deferred notice (verbatim):

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

Applied `.claude/skills/triage-slow-tests/SKILL.md`: inspected all 29 budget outliers and reran each through `just test-focused`. These cover surface construction, placement/auditing, model construction, numeric solves, mocked transport, and subprocess startup. The broad run overlapped the frontend/browser runs; every outlier passed below 5 s when rerun individually. No markers or timing guards changed. Broad FAST wall time: 275.22 s (304 s including selection/guard overhead).

| Test | Concurrent FAST seconds | Isolated measured setup + call seconds |
| --- | ---: | ---: |
| `tests/test_surface_tiled.py::test_tiles_match_dense_field_without_seams[0.24]` | 14.06 | 4.47 |
| `tests/test_streptavidin.py::test_packing_is_deterministic_and_clash_checked[biotin_tether]` | 13.95 | 3.56 |
| `tests/test_streptavidin.py::test_packing_is_deterministic_and_clash_checked[adsorption]` | 13.92 | 4.02 |
| `tests/test_mrdna_extensions.py::test_tails_are_flexible_ssdna_in_the_built_model` | 10.61 | 4.39 |
| `tests/test_surface_bin_transfer.py::test_figure_probe_is_adjustable_and_default_is_preserved` | 9.93 | 2.31 |
| `tests/test_junction_balance.py::test_the_atomistic_dx_junction_linkers_are_balanced[fixture0]` | 8.53 | 3.51 |
| `tests/test_aptamer_history.py::test_move_rotate_edit_delete_and_revert_preserve_native_sites` | 8.46 | 0.62 |
| `tests/test_molecular_placement_audit.py::test_runs_longer_than_two_remain_at_the_geometric_baseline` | 7.78 | 1.04 |
| `tests/test_surface_visual_regression.py::test_invariants_detect_envelope_perturbation` | 7.72 | 2.51 |
| `tests/test_gold_strep_dna.py::test_job_api_builds_full_fixed_core_model[CPU]` | 7.72 | 0.59 |
| `tests/test_atomistic_validation.py::test_display_atomistic_audit_route` | 7.52 | 2.91 |
| `tests/test_mrdna_extra_bases.py::test_bead_cloud_grows_with_bulk_inserts` | 7.45 | 2.82 |
| `tests/test_cg_seed_cluster_transform.py::test_cluster_translation_no_double_transform` | 7.37 | 2.51 |
| `tests/test_surface_visual_regression.py::test_vectorized_fine_surface_matches_exact_on_deformed` | 7.33 | 2.56 |
| `tests/test_fem_correlation_batch.py::test_generalized_correlation_crosses_batch_boundary` | 7.33 | 3.48 |
| `tests/test_strep_dna_occupancy.py::test_api_coating_first_exact_counts_undo_redo_and_atomic_failure` | 7.12 | 1.19 |
| `tests/test_nanoparticle_kinematics.py::test_closed_loop_solver_projects_nanoparticle_clearance` | 7.08 | 2.67 |
| `tests/test_md_prep_wiring.py::test_solvated_package_exports_fast_relaxation_assets` | 7.06 | 2.59 |
| `tests/test_molecular_placement_audit.py::test_audit_candidate_is_isolated_and_moves_only_insert_residues` | 6.49 | 0.77 |
| `tests/test_vr_motion_clusters.py::test_cluster_deterministic_and_exclusions_have_no_label` | 6.49 | 3.53 |
| `tests/test_peg_live.py::test_worker_transport_is_persistent_and_tears_down[CPU]` | 5.92 | 2.74 |
| `tests/test_alpine_worker.py::test_transfer_keeps_running_after_api_process_is_killed` | 5.88 | 4.42 |
| `tests/test_headless_corner_build.py::test_length_optimizer_beats_uniform_baseline_and_reference` | 5.88 | 2.67 |
| `tests/test_runpod_s3.py::test_s3_connection_maps_pod_workspace_to_volume_root` | 5.81 | 3.84 |
| `tests/test_streptavidin.py::test_coating_create_resize_move_remove_and_undo_are_atomic` | 5.76 | 0.96 |
| `tests/test_mrdna_extra_bases.py::test_inserts_are_flexible_ssdna_in_the_model[False]` | 5.43 | 4.06 |
| `tests/test_exp28_hierarchical_tube_cg.py::test_scale_smoke_symbolic_memory_scales_with_instance_count` | 5.30 | 4.14 |
| `tests/test_molecular_placement_audit.py::test_two_base_runs_show_promoted_production_v7_in_both_panels` | 5.21 | 0.97 |
| `tests/test_molecular_placement_audit.py::test_route_returns_full_and_ballstick_feeds_without_mutating_state` | 5.13 | 0.81 |

## Browser validation

- Part annotation regression: passed (real strand selection, content gating, highlight/color/icon, manual drag, viewport movement, hide/delete).
- Assembly workflow: passed (two copies of `hingeV4`, actual part and unnamed-overhang clicks, instance-scoped highlights, 25 nm transform tracking, style/manual controls, global toggle, `.nass` serialization/reimport, unchanged source annotations, prepared-sharing callout/target capture, delete).
- BigO: passed with all 30 instances and a single annotation on copy 18. Original `BigO-poly.nass` and `BigO.nadoc` compared byte-for-byte unchanged.
- Browser console error collections were empty on these passing runs. A failure screenshot was inspected while diagnosing the fixture; it showed both correctly colored leaders anchored to the intended part and overhang.
- Browser troubleshooting exposed and fixed two actual gaps: simplified renderers allocate no bead meshes (annotations now resolve source geometry), and unnamed overhangs had no pick anchors (now selectable without changing names).
- The browser tests use temporary `__e2e__` documents; all workspace copies and project-history artifacts are covered by global teardown, with Playwright output removed by the cleanup reporter. Interrupted runs were explicitly torn down and cleaned before rerunning.

## Frontend validation

Final `just test-frontend`: **549 files passed; 7,101 tests passed, 1 skipped** (95.00 s, including the final recovery-cache fix). The earlier oxDNA UI timing failure passed both its isolated 34-test file and this final full run. Production build and lint passed.

`just smoke`: **23 passed** (2.3 min), including assembly exit and loaded-design
teardown. After teardown, the workspace root had no new entries relative to the
pre-smoke inventory, no `__e2e__` paths remained anywhere under workspace, and
Playwright report/output directories were absent.

Recovery metadata is written to the browser cache before the server request, so a
failed save retains local edits; the existing retry test verifies that behavior
and that a later successful save recovers the queue.

Final production build: passed (10.86 s). Temporary validation logs were removed after recording these results. `git diff --check` passed.
