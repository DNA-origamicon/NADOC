"""
Shared pytest fixtures and hooks.
"""


from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


def make_minimal_design(
    *,
    n_helices: int = 1,
    helix_length_bp: int = 42,
    lattice: LatticeType = LatticeType.HONEYCOMB,
    with_scaffold: bool = True,
    with_staple: bool = True,
) -> Design:
    """Minimal fixture: 1–2 honeycomb/square helices, optional scaffold + staple
    spanning a single domain each. Used by tests that need a valid Design but
    don't care about the topology specifics. Larger or bespoke designs should
    be built inline.
    """
    if n_helices not in (1, 2):
        raise ValueError("n_helices must be 1 or 2")

    helices = [
        Helix(
            id=f"h{i}",
            axis_start=Vec3(x=i * 2.5, y=0.0, z=0.0),
            axis_end=Vec3(x=i * 2.5, y=0.0, z=helix_length_bp * BDNA_RISE_PER_BP),
            length_bp=helix_length_bp,
            bp_start=0,
        )
        for i in range(n_helices)
    ]

    strands = []
    if with_scaffold:
        strands.append(Strand(
            id="scaf",
            strand_type=StrandType.SCAFFOLD,
            domains=[Domain(
                helix_id="h0",
                start_bp=0,
                end_bp=helix_length_bp - 1,
                direction=Direction.FORWARD,
            )],
        ))
    if with_staple:
        # Per backend/core/sequences.py:84-95 convention: REVERSE direction
        # requires start_bp > end_bp so domain_bp_range traverses high→low.
        # (Pass 8-C fix; previously start_bp=0 silently yielded empty range.)
        strands.append(Strand(
            id="stap",
            strand_type=StrandType.STAPLE,
            domains=[Domain(
                helix_id="h0",
                start_bp=helix_length_bp - 1,
                end_bp=0,
                direction=Direction.REVERSE,
            )],
        ))

    return Design(helices=helices, strands=strands, lattice_type=lattice)


# ── Test-design builders ───────────────────────────────────────────────────────────
# These rebuild common bundle designs by replaying their `bundle-create` +
# `extrude-continuation` feature-log ops through the same core builders the app's
# /design/bundle and /design/bundle-continuation endpoints call.  The produced
# topology tracks how the app actually constructs designs, so tests can consume a
# built design instead of a committed `.nadoc` blob that can be silently corrupted.
#
# Cell layouts are taken VERBATIM from real designs' feature logs (cited per
# constant) — never hand-derived, per the "ask first about topology" rule.

# 4×4 SQUARE teeth bundle — tests/fixtures/teeth.nadoc.  First 8 cells are the
# columns extruded on every pass (long teeth); all 16 appear on the wide passes.
TEETH_CELLS = [
    (0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (1, 2), (1, 1), (1, 0),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 3), (3, 2), (3, 1), (3, 0),
]
# Pass widths after the initial 16-cell create — alternating narrow/wide is the
# tooth profile (see teeth.nadoc feature_log).
TEETH_PASSES = [8, 16, 8, 16, 8]

# 6-helix honeycomb ring — common across many real designs (workspace/6hb_3dprint,
# u6hb, OH6hb_test, Belt_segment_v1 all share these cells).
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]

# 18-helix honeycomb bundle — tests/fixtures/18hb_fixture.nadoc.
EIGHTEEN_HB_CELLS = [
    (1, 3), (0, 3), (0, 2), (0, 1), (1, 1), (1, 2), (2, 2), (2, 1), (3, 1),
    (3, 2), (3, 3), (2, 3), (2, 4), (2, 5), (2, 6), (1, 6), (1, 5), (1, 4),
]

# mini_hinge base — workspace/mini_hinge.nadoc bundle-create: two 4×2 SQUARE
# blocks at rows 0–1 and 4–5 (the gap between them is the hinge).  This is only
# the initial extrusion; the file's later routing/flexible/overhang ops are NOT
# reproduced here.
MINI_HINGE_CELLS = [
    (0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (1, 2), (1, 1), (1, 0),
    (4, 0), (4, 1), (4, 2), (4, 3), (5, 3), (5, 2), (5, 1), (5, 0),
]


def build_extruded_bundle(
    cells,
    length_bp: int,
    *,
    lattice: LatticeType,
    name: str = "Bundle",
    plane: str = "XY",
    strand_filter: str = "both",
    passes=(),
) -> Design:
    """Build a bundle (+ N extrude passes) through the headless construction API.

    Thin wrapper over ``backend.api.headless_build.build_bundle`` — i.e. the same
    route handlers the UI's bundle/extrude tools call, run mouse-free in an
    isolated throwaway document.  Designs therefore carry a real, replayable
    ``feature_log`` (one bundle-create + one extrude-continuation per pass), just
    like a design built by clicking.

    Parameters
    ----------
    cells, length_bp, lattice, name, plane, strand_filter:
        The initial bundle-create (see ``make_bundle_design``).
    passes:
        Extrude-continuation passes off the blunt ends.  Each entry is an ``int``
        n (extrude ``cells[:n]``) or an explicit cell list; pass *i* (1-based)
        extrudes at ``offset_nm = i × length_bp × rise`` (the teeth pattern).
        Empty for a single-create design (6hb / 18hb / mini_hinge base).
    """
    from backend.api.headless_build import build_bundle

    return build_bundle(
        cells, length_bp, lattice=lattice, name=name,
        plane=plane, strand_filter=strand_filter, passes=passes,
    )


def make_teeth_design() -> Design:
    """Rebuild tests/fixtures/teeth.nadoc (4×4 SQUARE, 42 bp, 5 alternating passes).

    Pinned against the committed file by ``test_teeth_builder_matches_fixture``:
    canonical topology equality + identical seamed/seamless routed output.
    """
    return build_extruded_bundle(
        TEETH_CELLS, 42, lattice=LatticeType.SQUARE, name="teeth", passes=TEETH_PASSES,
    )


def make_6hb_design(length_bp: int = 42) -> Design:
    """6-helix honeycomb bundle (single create).  Default 42 bp."""
    return build_extruded_bundle(
        SIX_HB_CELLS, length_bp, lattice=LatticeType.HONEYCOMB, name="6hb",
    )


def make_6hb_curved_design(length_bp: int = 192) -> Design:
    """6-helix honeycomb bundle bent into a Dietz curve via loop/skip marks.

    Deterministic replacement for the old gitignored ``workspace/6hb_curved.nadoc``
    (workspace/ isn't synced across the two computers, so any test bound to it
    drifted).  Builds a plain 192-bp 6hb, then applies ``bend_loop_skips`` at
    R=40 nm over the interior span — which lands exactly 18 loops + 18 skips and a
    predicted radius of ~35 nm (the ~36 nm Dietz regime the curvature check pins).
    """
    from backend.core.loop_skip_calculator import apply_loop_skips, bend_loop_skips

    d = make_6hb_design(length_bp=length_bp)
    hel = d.helices
    bp0 = min(h.bp_start for h in hel)
    bpN = min(h.bp_start + h.length_bp for h in hel)
    mods = bend_loop_skips(hel, bp0 + 5, bpN - 5, 40.0, direction_deg=0.0, design=d)
    return apply_loop_skips(d, mods)


def make_18hb_design(length_bp: int = 388) -> Design:
    """18-helix honeycomb bundle — matches tests/fixtures/18hb_fixture.nadoc at 388 bp."""
    return build_extruded_bundle(
        EIGHTEEN_HB_CELLS, length_bp, lattice=LatticeType.HONEYCOMB, name="18hb",
    )


def make_18hb_routed_design(length_bp: int = 388) -> Design:
    """Fully-routed 18hb: bundle-create → auto-scaffold-seamed → auto-crossover → auto-break.

    The mouse-free equivalent of the old gitignored ``workspace/18hb.nadoc`` —
    a scaffold-routed, crossover'd, staple-broken precursor — built in an isolated
    scratch session via the headless auto-op wrappers.  Deterministic, so tests
    that assert routed specifics can pin against it.
    """
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(
            EIGHTEEN_HB_CELLS, length_bp, lattice=LatticeType.HONEYCOMB, name="18hb",
        )
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def make_mini_hinge_base_design(length_bp: int = 84) -> Design:
    """mini_hinge initial bundle: two 4×2 SQUARE blocks (rows 0–1, 4–5).

    Only the base geometry — the file's routing/flexible/overhang ops are not replayed.
    """
    return build_extruded_bundle(
        MINI_HINGE_CELLS, length_bp, lattice=LatticeType.SQUARE, name="mini_hinge",
    )


# ── Overhang placement (single validated source of truth) ────────────────────────
# Tests historically re-implemented "find a staple end + free neighbour" several
# times, none of them applying the backbone-facing rule the UI enforces.  These two
# helpers delegate to the validated oracle (overhang_candidate_error) so test
# overhangs land exactly where the app's overhang tool would offer them.


def valid_overhang_sites(design: Design) -> list[dict]:
    """Every placement the UI overhang tool would offer on *design*.

    Returns dicts ``{helix_id, bp_index, direction, is_five_prime, neighbor_row,
    neighbor_col}`` for each staple 5′/3′ end × surrounding cell that passes the
    validated gate (adjacency + vacant-at-Z + backbone bead faces the cell).  The
    oracle does the geometry, so we just enumerate candidate cells and let it filter.
    """
    from backend.core.lattice import overhang_candidate_error
    from backend.core.models import StrandType

    helix_by_id = {h.id: h for h in design.helices}
    sites: list[dict] = []
    seen: set[tuple] = set()
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        for hid, bp, direc, is5 in (
            (first.helix_id, first.start_bp, first.direction, True),
            (last.helix_id, last.end_bp, last.direction, False),
        ):
            helix = helix_by_id.get(hid)
            if helix is None or helix.grid_pos is None:
                continue
            r, c = helix.grid_pos
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    key = (hid, bp, direc, is5, nr, nc)
                    if key in seen:
                        continue
                    seen.add(key)
                    if overhang_candidate_error(design, helix, bp, direc, nr, nc) is None:
                        sites.append(dict(
                            helix_id=hid, bp_index=bp, direction=direc,
                            is_five_prime=is5, neighbor_row=nr, neighbor_col=nc,
                        ))
    return sites


def extrude_valid_overhang(design: Design, length_bp: int = 12) -> tuple[Design, str]:
    """Extrude an overhang at the first valid candidate; return (design, overhang_id).

    Raises AssertionError if *design* has no valid overhang site.
    """
    from backend.core.lattice import make_overhang_extrude

    for site in valid_overhang_sites(design):
        out = make_overhang_extrude(
            design, site["helix_id"], site["bp_index"], site["direction"],
            site["is_five_prime"], site["neighbor_row"], site["neighbor_col"], length_bp,
        )
        new_helix_ids = {h.id for h in out.helices} - {h.id for h in design.helices}
        new_helix_id = next(iter(new_helix_ids))
        new_ovhg = next(o for o in out.overhangs if o.helix_id == new_helix_id)
        return out, new_ovhg.id
    raise AssertionError("design has no valid overhang site")


# ---------------------------------------------------------------------------
# Slow-test registry (auto-applies the ``slow`` marker)
#
# A handful of tests drive REAL simulation binaries (oxDNA/oxpy, GROMACS, the
# protein fork) or parse on-disk MD trajectories with MDAnalysis. They cost
# seconds each and dominate suite wall time; everything else is sub-100ms.
#
# Rather than scatter ``@pytest.mark.slow`` across ~45 call sites (and silently
# rot as new heavy tests appear), the heavy tests are listed here in ONE place
# and marked at collection time. ``just test-fast`` runs ``-m "not slow"`` to
# skip them for the tight dev loop; ``just test`` runs everything.
#
# To refresh after adding/renaming heavy tests, run the suite with
# ``--durations=0`` and fold any new >=~2s "call" entries into the sets below.
# (Pre-existing inline ``@pytest.mark.slow`` decorators are still honored too.)
# ---------------------------------------------------------------------------

# Whole modules where every test is a heavy real-sim / trajectory test.
_SLOW_MODULES = {
    "test_md_trajectory",
    "test_md_display_ready_live",   # real-job load: parses 143 MB PSF + builds model
    # Setup-dominated: a ~16 s module/class-scoped fixture that EVERY test pays,
    # so per-test marking wouldn't help — the whole file is slow.
    "test_md_pipeline",
}

# Individual heavy tests (>=~2s call time) living in otherwise-fast modules.
_SLOW_TESTS = {
    # N2 NAMD anchors: real psfgen topology build (stubbed solvate) + conf writing.
    "test_prepare_writes_anchor_restraints_end_to_end",
    # N2 NAMD anchors: 176-strand routed design build + real export_pdb (~30 s).
    "test_export_pdb_residue_order_is_natural_not_sorted_on_many_strands",
    # N1 NAMD E-field: real psfgen prepare (stubbed solvate) + conf writing.
    "test_prepare_writes_efield_end_to_end_and_psf_charge_is_minus_one",
    # N1 NAMD E-field: real psfgen prepare, asserts the unresolved-anchor guard raises.
    "test_field_with_unresolvable_anchors_raises_at_prep",
    # N1 NAMD E-field: real psfgen build, reads the force field's own residue charges.
    "test_real_psf_charges_pin_the_conversion_and_the_terminal_deficit",
    # N1 NAMD E-field: real psfgen + three real NAMD runs (differential field probe).
    "test_real_namd_run_holds_anchor_and_accelerates_free_strand_along_field",
    "test_oxdna_http_lifecycle",
    "test_runner_real_binary_status_lifecycle",
    "test_lammps_real_run_end_to_end",   # real lmp CG-DNA run
    "test_lammps_field_holds_anchor_and_deflects_free",   # real lmp field+anchor run
    "test_create_runs_to_completion_and_lists",   # real lmp CG-DNA run via REST
    "test_create_with_field_and_anchor_records_forces",   # real lmp steered run via REST

    # headless build+optimize (real router/oxdna passes)
    "test_build_and_optimize_oracle_fires_on_unreachable",
    "test_build_and_optimize_converges",
    "test_build_and_optimize_oracle_fires_on_vacuous",
    "test_build_and_check_reports_radius_of_gyration",
    "test_build_and_check_resolves_end_to_end_landmarks",
    "test_apply_loop_skips_spec_honors_marks_per_helix",
    # extra-base heavy reps
    "test_heavy_rep_extra_bases_follow_sim_positions",
    "test_md_chain_map_keys_extra_bases_uniquely",
    "test_md_rigid_reference_tolerates_extra_base_keys",
    # headless oxdna field campaigns / sweeps / relaxed measurements (real oxpy)
    "test_run_live_field_real_oxpy_steers",
    "test_field_campaign_distinguishes_designs",
    "test_field_campaign_is_reproducible",
    "test_field_campaign_oracle_fires_on_indistinguishable",
    "test_field_campaign_records_a_failed_design",
    "test_field_sweep_maps_response_surface",
    "test_field_sweep_oracle_fires_on_unbounded_window",
    "test_field_validation_deflection_scales_with_field",
    "test_iterate_oracle_fires_on_exhaustion",
    "test_iterate_converges_to_constraint",
    "test_read_flexibility_map_returns_mean_and_confidence",
    "test_relaxed_measurement_segment_angle_fires_on_wrong_target",
    "test_relaxed_measurement_fires_on_wrong_target",
    "test_relaxed_measurement_radius_of_gyration_fires_on_wrong_target",
    "test_assert_relaxed_measurement_radius_of_gyration",
    "test_assert_relaxed_measurement_end_to_end",
    "test_assert_relaxed_measurement_segment_angle",
    "test_check_relaxed_constraint_met_on_real_run",
    "test_multiple_field_children_from_one_parent",
    # protein fork run
    "test_prepared_hybrid_job_runs_on_fork",
    # atomistic trajectory audits (MDAnalysis loads)
    "test_trajectory_audit_route",
    "test_audit_trajectory_frames_clean",
    "test_audit_trajectory_frames_catches_bad_frame",
    "test_audit_trajectory_frames_explicit_indices",
    # headless build (full routing / saturation passes)
    "test_make_18hb_routed_design_is_deterministic",
    "test_apply_deformations_geometry_honors_marks_per_helix",
    "test_fill_all_overhang_candidates_saturates_and_stays_valid",
    "test_auto_op_chain_routes_a_full_18hb",
    # CanDo-FEM autorefine density sweep (~20 FEM solves on a multi-helix square strut)
    "test_fem_autorefine_relieves_square_strut_twist_headless",
    "test_sweep_skip_period_finds_a_twist_relieving_minimum",
    "test_refine_plain_square_strut_tunes_density_where_greedy_kept_zero",
    "test_autorefine_job_applies_marks_logs_and_caches_all_displays",
    # --- CanDo-FEM / autorefine numeric solves added by the G1/G3/G4 shape-objective
    #     work (refreshed 2026-07-05; each is a real FEM eigensolve or refine loop). ---
    # test_cando_autorefine.py (honeycomb/square shape refine)
    "test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden",
    "test_refine_plain_square_strut_nulls_twist_where_greedy_kept_zero",
    "test_refine_emits_per_iteration_twist_bend_deviation_and_target",
    "test_refine_straight_control_makes_no_edits",
    "test_refine_square_lattice_is_skips_only",
    # test_cando_job.py (full autorefine/linear jobs)
    "test_linear_job_completes_and_caches",
    "test_progress_and_reconcile",
    "test_autorefine_job_no_improvement_leaves_design_but_still_caches",
    # test_cando_cylinders.py (axis nodes + RMSF heatmap)
    "test_axis_nodes_are_helix_centre_not_backbone_midpoint",
    "test_rmsf_heatmap_attached_per_node_with_p95_ramp",
    # test_fem_solver.py (NMA / nonlinear equilibrium eigensolves)
    "test_free_free_nma_rmsf_is_physical_and_flatter_than_pinned",
    "test_predict_shape_defaults_to_nonlinear_and_returns_positions_and_rmsf",
    "test_rmsf_is_finite_nonnegative_and_per_node",
    "test_nonlinear_prestress_shape_runs_and_deforms",
    # test_fem_curvature_validation.py (CanDo bend reproduction)
    "test_fem_reproduces_cando_bend_90_nonlinear",
    "test_realized_vs_unrealized_bend_is_the_only_difference",
    "test_fem_reproduces_cando_bend_180_hairpin_linear",
    "test_bend_deformation_without_loopskips_predicts_straight",
    # test_cando_deviation.py (deviation-field FEM)
    "test_unrealized_bend_deviates_far_more_than_realized",
    "test_deviation_payload_shape_and_stats",
    "test_straight_control_has_near_zero_deviation",
    "test_loop_copies_each_get_their_own_deviation_entry",
    # test_namd_topology.py (extra-base inline threading / junction backbone builds)
    "test_extra_bases_thread_inline_in_seq_num",
    "test_extra_base_junction_backbone_bonds_are_sane",
    # test_oxdna_relaxation.py (seed geometry + crossover-stretch on bent bundle)
    "test_seed_geometry_falls_back_for_bent_bundle",
    "test_max_crossover_stretch_detects_compaction_desync",
    # test_cando_field.py (C2 E-field: each is multiple nonlinear corotational solves on
    # a 6HB; the assemble_field_force UNIT tests stay fast — pure force-vector math)
    "test_anchored_field_deflects_free_region_along_field",
    "test_deflection_is_monotone_in_field_magnitude",
    "test_zero_field_produces_no_deflection",
    "test_predict_shape_field_threads_through_and_changes_shape",
    # test_cando_shape_source.py (C5 comparison source: the pure assembler tests stay
    # fast — this one runs a real in-process FEM predict_shape + NMA RMSF on a 6HB)
    "test_real_predict_shape_assembles_and_compares",
    # test_cando_extra_bases.py (C3 extra-base compliant connectors: the mesh/compliance
    # tests are fast pure-math; this one runs several real predict_shape + NMA RMSF solves)
    "test_extra_bases_raise_local_flexibility_rmsf",
}


# ---------------------------------------------------------------------------
# Slow-test AREA tagging (for change-based selection — ``just test-smart``)
#
# Each slow test also gets an ``area`` marker derived from its filename, so the
# selector can run just the heavy group affected by a change:
#   -m "not slow or oxdna"   → all fast tests + the oxDNA slow group
# The fast suite (``not slow``) ALWAYS runs regardless, so a mis-tag can only
# skip a heavy sim test whose fast-suite cousins still ran — never a silent hole
# in basic coverage. scripts/select_tests.py owns the source->area routing.
#
# Keep AREA_MARKERS in sync with the markers registered in pyproject.toml.
# ---------------------------------------------------------------------------
AREA_MARKERS = ("oxdna", "cando", "namd", "mrdna", "atomistic", "md", "headless")


def _slow_area_for(module: str) -> str:
    """Map a slow test's module (bare filename, no .py) to one area marker.
    First match wins; order matters (oxdna before headless so the oxDNA
    headless-build file lands in oxdna, not headless)."""
    if "oxdna" in module or "skip_twist" in module:
        return "oxdna"
    if "cando" in module or "fem" in module:
        return "cando"
    if "namd" in module:
        return "namd"
    if "mrdna" in module:
        return "mrdna"
    if "atomistic" in module:
        return "atomistic"
    if module.startswith("test_md") or "openmm" in module or "benchmark" in module:
        return "md"
    if "headless" in module or "spec_build" in module:
        return "headless"
    # Unclassified slow test: park in "md" (a broad sim area). It still always
    # runs under a FULL selection; this only affects narrow leaf selections.
    return "md"


def pytest_collection_modifyitems(config, items):
    """Auto-apply the ``slow`` marker to the heavy real-sim/trajectory tests
    registered above, plus an ``area`` marker so ``just test-smart`` can run
    only the heavy group a change affects. ``-m 'not slow'`` skips them all."""
    import pytest

    for item in items:
        module = item.module.__name__.rsplit(".", 1)[-1] if item.module else ""
        # item.originalname is the bare function name without any param id.
        name = getattr(item, "originalname", None) or item.name.split("[")[0]
        if module in _SLOW_MODULES or name in _SLOW_TESTS:
            item.add_marker(pytest.mark.slow)
            item.add_marker(getattr(pytest.mark, _slow_area_for(module)))


# ---------------------------------------------------------------------------
# Resource guard: skip heavy (``slow``) tests while a production NAMD / oxDNA /
# mrDNA job is already running on this machine.  Piling GPU/CPU-bound tests on
# top of a live sim just starves both and makes the tests time out (flaky).
#
# The check runs ONCE per worker at startup (pytest_configure) — before any test
# body has spawned its own oxDNA/oxpy subprocess — and is cached, so a slow test
# launching a sim can't make sibling slow tests skip themselves.  Detection is
# fail-open (a probe glitch never skips).  Override with NADOC_IGNORE_SIM_GUARD=1.
# ---------------------------------------------------------------------------
_SIM_GUARD: tuple[bool, str] | None = None


def _sim_guard() -> tuple[bool, str]:
    """(running, reason), computed once per process and cached."""
    global _SIM_GUARD
    if _SIM_GUARD is None:
        import os

        if os.environ.get("NADOC_IGNORE_SIM_GUARD"):
            _SIM_GUARD = (False, "")
        else:
            try:
                from backend.core.hardware import heavy_sim_running

                _SIM_GUARD = heavy_sim_running()
            except Exception:  # fail-open: never mask tests on a probe error
                _SIM_GUARD = (False, "")
    return _SIM_GUARD


def pytest_configure(config):
    # Prime the cache during the clean startup window (no test has run yet, so no
    # test-spawned sim can be mistaken for a production job).
    _sim_guard()


def pytest_runtest_setup(item):
    if item.get_closest_marker("slow") is None:
        return
    running, reason = _sim_guard()
    if running:
        import pytest

        pytest.skip(
            f"heavy sim job running ({reason}); skipping slow test to avoid resource "
            f"contention — set NADOC_IGNORE_SIM_GUARD=1 to override"
        )
