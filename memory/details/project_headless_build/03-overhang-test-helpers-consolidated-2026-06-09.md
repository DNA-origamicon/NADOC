# Overhang test helpers consolidated (2026-06-09) — supporting detail

[Topic head](../../project_headless_build.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Overhang test helpers consolidated (2026-06-09)

`conftest.valid_overhang_sites(design)` + `conftest.extrude_valid_overhang(design,
length_bp)` are the **single validated source of truth** for test overhang
placement — they enumerate staple-end × cell candidates and filter through
`overhang_candidate_error` (so test overhangs land exactly where the UI tool
offers). Replaced 3 bespoke enumerators that omitted the backbone-facing rule:
`test_sub_domains._extrude_overhang` (used by 11 tests across sub_domains /
subdomain_rotation / subdomain_boundary_hairpin) and
`test_overhang_sequence_resize._all_overhang_sites` now delegate. **Left
`test_overhang_geometry._all_overhang_sites` alone on purpose** — it tests the
ungated geometric PRIMITIVE at arbitrary positions (the facing filter would cut
coverage). New `test_headless_build.test_fill_all_overhang_candidates_saturates_and_stays_valid`
pins the fill-until-saturated behaviour (stacks >1 per cell, valid, 0 candidates left).

## Test-migration audit (2026-06-09) — what can/can't use the builders

`test_seamless_router.py::test_teeth_closing_zig` migrated teeth.nadoc →
`make_teeth_design()` (builder helix AND strand ids match the fixture exactly —
deterministic `h_XY_r_c` naming — so even id-referencing asserts are safe).

**Do NOT blindly swap the `workspace/18hb.nadoc` tests in `test_staple_scoring.py`
to `make_18hb_design()`** — that was a wrong recommendation from an automated
audit. `workspace/18hb.nadoc` is a FULLY ROUTED design (1 scaffold strand, 757
crossovers, sequences; feature_log = bundle-create→auto-scaffold-seamed→
auto-crossover→autobreak), NOT a bare bundle. The 4 skipping tests
(`test_score_workspace_18hb...`, `test_auto_break_aksel...`, `test_auto_route_aksel...`,
`test_full_autostaple_completes_on_18hb...`) need that routed input and assert
routing-specific outcomes (hardcoded 7188 nt scaffold / 6984 bound; or HTTP 422
"No complete legal breakpoint path"). A bare bundle invalidates all of them.
`test_precursor_graph_workspace_18hb...` was ALREADY migrated to the committed
bare `18hb_fixture.nadoc` (total_nt==388). `test_old_nadoc_loads_without_snapshot_entries`
deliberately wants an OLD no-feature-log file (`Examples/6hb_test.nadoc`, exists) —
the builder produces the opposite.

**Outcome of unblocking the 4 routed-18hb tests (done 2026-06-09):** with the
auto-op wrappers + `make_18hb_routed_design()`, 2 of the 4 migrated to run on CI
(no longer skip): `test_score_workspace_18hb...` (regen reproduces total_nt 7188 /
bound 6984 EXACTLY) and `test_full_autostaple_completes_on_18hb...` (structural
asserts hold). The 2 Aksel tests (`test_auto_break_aksel...`, `test_auto_route_aksel...`)
**stayed file-gated** — they assert the **422 "No complete legal breakpoint path"**
failure mode, which is a property of the bespoke workspace design; a clean regen
HAS a legal path and returns 200, so substituting it would destroy the regression.
Added `test_auto_route_aksel_succeeds_on_clean_18hb` as the positive (200)
complement. Lesson: structural/length-derived assertions survive regeneration;
design-specific *failure-mode* assertions do not — verify each individually, never
bulk-swap. Hinge3 / hingeV4 / mini_rect / 10hb-MD fixtures stay file-based (bespoke
or hand-routed).

Related: [[project_autoscaffold_single_strand]], [[project_seamless_router]],
[[project_extrude_preview]].
