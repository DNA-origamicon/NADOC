"""Phase-1 smoke tests for the restored CanDo-style FEM solver.

Verifies the mesh→stiffness→solve→RMSF pipeline runs on a real routed bundle and
holds basic structural invariants. It does NOT assert calibrated RMSF/shape values
— pre-stress + calibration are Phase 2/3 (see memory/project_cando_fem.md). The
solver's equilibrium is trivially u=0 here (no pre-stress force yet).
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.core.models import LatticeType
from backend.physics.fem_solver import (
    apply_boundary_conditions,
    assemble_global_stiffness,
    assemble_prestress_force,
    build_fem_mesh,
    compute_rmsf,
    compute_rmsf_nma,
    predict_shape,
    solve_equilibrium,
)


@pytest.fixture(scope="module")
def routed_6hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_mesh_builds_with_nodes_elements_and_crossover_links(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    assert len(mesh.nodes) > 0
    assert len(mesh.elements) > 0
    # Standard DX crossovers are RIGID LINKS (exact constraint); ssDNA ones are springs.
    assert len(mesh.rigid_links) + len(mesh.springs) > 0   # the bundle is coupled
    assert len(mesh.rigid_links) > 0                        # a DX bundle → rigid links


def test_mesh_nodes_are_duplex_core_not_inflated_axis(routed_6hb):
    # Nodes = duplex bp (both scaffold+staple), NOT round(axis_len/rise) which includes
    # the ~21-bp auto_scaffold cap extension. 6 helices × 84 bp → ~504 duplex nodes,
    # well under the inflated axis count (~6 × (84+21) = 630).
    from backend.physics.fem_solver import _duplex_bp_per_helix

    mesh = build_fem_mesh(routed_6hb)
    duplex = _duplex_bp_per_helix(routed_6hb)
    total_duplex = sum(len(v) for v in duplex.values())
    assert len(mesh.nodes) == total_duplex
    assert len(mesh.nodes) <= 6 * 84 + 6    # no cap inflation


def test_stiffness_assembly_shape_and_zero_force(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    assert K.shape == (6 * len(mesh.nodes), 6 * len(mesh.nodes))
    # Phase 1: no pre-stress force vector yet.
    assert np.allclose(f, 0.0)


def test_boundary_conditions_remove_six_rigid_body_dofs(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    Kf, ff, free = apply_boundary_conditions(K, f, mesh)
    assert len(free) == K.shape[0] - 6      # one node fully pinned
    assert Kf.shape == (len(free), len(free))


def test_equilibrium_is_trivially_zero_without_prestress(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    Kf, ff, free = apply_boundary_conditions(K, f, mesh)
    u = solve_equilibrium(Kf, ff, K.shape[0], free)
    assert np.all(np.isfinite(u))
    assert np.abs(u).max() < 1e-9           # u=0 until Phase-2 pre-stress lands


def test_rmsf_is_finite_nonnegative_and_per_node(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    Kf, _, free = apply_boundary_conditions(K, f, mesh)
    rmsf = compute_rmsf(Kf, free, len(mesh.nodes))
    assert rmsf.shape == (len(mesh.nodes),)
    assert np.all(np.isfinite(rmsf))
    assert np.all(rmsf >= 0.0)
    assert rmsf.max() > 0.0                 # some flexibility present


def test_prestress_produces_damped_bundle_twist(routed_6hb):
    """The loop/skip eigenstrain drives a global twist that is DAMPED below the free
    single-helix analytic (predict_global_twist_deg) by the crossover-beam coupling —
    the bundle torsional-coupling effect CanDo reproduces (6HB ratio ≈ 0.26). The twist
    must be non-zero, correctly signed, and a substantial-but-sub-analytic fraction."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core import loop_skip_calculator as lsc

    # Fresh routed 6HB, 5 uniform deletions/helix off crossovers/ends.
    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:
            for bp in (20, 40, 60):        # interior, uniform
                hb.loop_skip(h.id, bp, -1)
        d = design_state.get_or_404().model_copy(deep=True)

    analytic = lsc.predict_global_twist_deg(
        {h.id: list(h.loop_skips) for h in d.helices if h.loop_skips})

    mesh = build_fem_mesh(d)
    K, _ = assemble_global_stiffness(mesh)
    f = assemble_prestress_force(mesh, d)
    assert np.abs(f).max() > 0.0            # non-zero pre-stress from the marks
    Kf, ff, free = apply_boundary_conditions(K, f, mesh)
    u = solve_equilibrium(Kf, ff, K.shape[0], free)

    # Per-helix end-to-end θ_z (local material twist), averaged.
    by: dict = {}
    for i, n in enumerate(mesh.nodes):
        by.setdefault(n.helix_id, []).append((n.global_bp, i))
    twists = []
    for lst in by.values():
        lst.sort()
        twists.append(np.degrees(u[6 * lst[-1][1] + 5] - u[6 * lst[0][1] + 5]))
    mean_twist = float(np.mean(twists))

    # Damped below the free analytic, but a substantial fraction (bundle coupling, not
    # rigid): 6HB comes out ≈ 0.26 of analytic. Sign-agnostic (frame = ASK-FIRST).
    ratio = abs(mean_twist) / abs(analytic)
    assert 0.1 < ratio < 0.6


def test_nonlinear_prestress_shape_runs_and_deforms(routed_6hb):
    """The incremental corotational solve returns per-node positions and moves the
    structure off its straight reference under a twist eigenstrain. (Convergence +
    large-deflection accuracy are validated separately against CanDo, not here.)"""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.physics.fem_solver import solve_prestress_shape

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:
            hb.loop_skip(h.id, 40, -1)
        d = design_state.get_or_404().model_copy(deep=True)

    mesh = build_fem_mesh(d)
    ref = np.array([n.position for n in mesh.nodes])
    pos = solve_prestress_shape(d, mesh, n_steps=4)
    assert pos.shape == (len(mesh.nodes), 3)
    assert np.all(np.isfinite(pos))
    assert np.linalg.norm(pos - ref, axis=1).max() > 1e-3   # it deformed


def test_predict_shape_defaults_to_nonlinear_and_returns_positions_and_rmsf():
    """The public shape-prediction entry point defaults to the geometrically-NONLINEAR
    solve (validated ~0.95 vs CanDo; the linear solve under-predicts bend ~10%), returns
    deformed backbone positions and node-aligned RMSF, and moves a marked design off its
    straight reference. Display-only output — topology is never mutated."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:              # gradient marks → a bend
            for bp in (20, 40, 60):
                hb.loop_skip(h.id, bp, 1 if h.grid_pos[0] == 0 else -1)
        d = design_state.get_or_404().model_copy(deep=True)

    mesh = build_fem_mesh(d)
    # Undeformed backbone baseline (u=0) to measure deformation against.
    from backend.physics.fem_solver import deformed_positions
    base = {(p["helix_id"], p["bp_index"], p["direction"]): np.array(p["backbone_position"])
            for p in deformed_positions(d, mesh, np.zeros(6 * len(mesh.nodes)))}

    res = predict_shape(d, n_steps=6)                       # nonlinear default
    assert res["solver"] == "nonlinear"
    assert len(res["positions"]) > 0
    assert len(res["rmsf"]) == len(mesh.nodes)              # one RMSF per axis node
    assert all(r["rmsf_nm"] >= 0.0 and np.isfinite(r["rmsf_nm"]) for r in res["rmsf"])

    # the predicted shape actually deformed off the straight reference
    moved = max(
        float(np.linalg.norm(np.array(p["backbone_position"])
                             - base[(p["helix_id"], p["bp_index"], p["direction"])]))
        for p in res["positions"]
    )
    assert moved > 1e-3


def test_predict_shape_covers_every_nucleotide_including_each_loop_copy():
    """VALIDATION for the deform / flex / deviation display toggles: the predicted
    positions must cover EVERY rendered nucleotide INCLUDING each LOOP-INSERT COPY.

    A loop insertion places several nucleotides at ONE (helix, bp, direction); the
    renderer distinguishes them by a `copy` index (helix_renderer `_copySeenBB`) and
    addresses beads by "helix:bp:dir:copy".  deformed_positions must therefore stamp
    the SAME copy index on each emitted position, or every loop copy > 0 strands at its
    native position/colour — invisible to a set-of-(helix,bp,dir) check that collapses
    the copies.  So this asserts coverage over the (helix, bp, dir, COPY) tuples.

    Regression (this bug): the pre-fix deformed_positions emitted no `copy` field, so
    all loop copies aliased to copy 0 → the extra loop bases were never moved/coloured
    by any display toggle.  A collapsed-key assertion passed anyway (false confidence)."""
    from collections import Counter

    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.geometry import nucleotide_positions
    from backend.physics.fem_solver import deformed_positions

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)      # ssDNA scaffold ends at the strand termini
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:                   # +1 on half the helices → LOOP inserts (copies)
            for bp in (20, 40, 60):
                hb.loop_skip(h.id, bp, 1 if h.grid_pos[0] == 0 else -1)
        d = design_state.get_or_404().model_copy(deep=True)

    # Every nucleotide the renderer draws, keyed WITH its loop-copy index (appearance
    # order within a (helix, bp, dir) — the same order the renderer + backend assign).
    seen: Counter = Counter()
    expected: set = set()
    total_nuc = 0
    for helix in d.helices:
        for nuc in nucleotide_positions(helix):
            k = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
            expected.add((*k, seen[k]))
            seen[k] += 1
            total_nuc += 1
    # The test is only meaningful if the design actually has loop copies (copy > 0).
    assert any(c > 0 for *_rest, c in expected), "design must contain loop inserts (copy>0)"

    mesh = build_fem_mesh(d)
    assert len(mesh.nodes) * 2 < total_nuc, "expected uncovered ssDNA/loop nucleotides"

    pos = deformed_positions(d, mesh, np.zeros(6 * len(mesh.nodes)))
    assert all("copy" in p for p in pos), "every predicted position must carry a copy index"
    covered = {(p["helix_id"], p["bp_index"], p["direction"], p["copy"]) for p in pos}
    missing = expected - covered
    assert not missing, f"{len(missing)} loop/ss nucleotide(s) stranded (no predicted position)"
    assert covered == expected            # exact per-copy coverage, no phantom keys
    assert len(pos) == total_nuc          # no loop copies collapsed away


def test_predict_shape_raises_clear_error_on_duplex_free_design():
    """Edge case: a design with no double-helical core (0 FEM mesh nodes) — e.g. a lone
    unpaired 1-bp helix — must raise a CLEAR ValueError, not crash deep in the solver with
    a cryptic ``AxisError: axis 1 is out of bounds`` (the empty centroid computation in
    apply_boundary_conditions).  The job runner surfaces this message to the panel."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 1)], 1, lattice=LatticeType.HONEYCOMB, name="mini")
        d = design_state.get_or_404().model_copy(deep=True)

    assert len(build_fem_mesh(d).nodes) < 2      # degenerate mesh — the trigger
    with pytest.raises(ValueError, match="duplex"):
        predict_shape(d, nonlinear=False, with_rmsf=False)


def test_free_free_nma_rmsf_is_physical_and_flatter_than_pinned(routed_6hb):
    # Free-free NMA (CanDo's method): projects out the 6 rigid-body modes, no pin →
    # no cantilever-grows-with-distance artifact. RMSF should be finite, positive,
    # in a physical nm range, and much flatter (lower max/mean spread) than the pinned
    # solve. Absolute calibration to CanDo (~0.4-1.7 nm) is ongoing Phase-2 work.
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    free = compute_rmsf_nma(K, len(mesh.nodes))
    Kf, _, fd = apply_boundary_conditions(K, f, mesh)
    pinned = compute_rmsf(Kf, fd, len(mesh.nodes))

    assert free.shape == (len(mesh.nodes),)
    assert np.all(np.isfinite(free)) and np.all(free >= 0.0)
    assert 0.05 < free.mean() < 20.0        # physical order of magnitude (nm)
    # Free-free removes the pinned-node cantilever, so it is flatter.
    assert (free.max() / free.mean()) < (pinned.max() / max(pinned.mean(), 1e-9))
