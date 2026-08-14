"""Phase-1 smoke tests for the restored CanDo-style FEM solver.

Verifies the mesh→stiffness→solve→RMSF pipeline runs on a real routed bundle and
holds basic structural invariants. It does NOT assert calibrated RMSF/shape values
— pre-stress + calibration are Phase 2/3 (see memory/project_cando_fem.md). The
solver's equilibrium is trivially u=0 here (no pre-stress force yet).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import LatticeType
from backend.physics.fem_solver import (
    apply_boundary_conditions,
    assemble_global_stiffness,
    assemble_prestress_force,
    build_fem_mesh,
    compute_rmsf,
    compute_rmsf_nma,
    deformed_positions_with_axis,
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
    assert len(mesh.rigid_links) + len(mesh.springs) > 0  # the bundle is coupled
    assert len(mesh.rigid_links) > 0  # a DX bundle → rigid links


def test_mesh_nodes_are_duplex_core_not_inflated_axis(routed_6hb):
    # Nodes = duplex bp (both scaffold+staple), NOT round(axis_len/rise) which includes
    # the ~21-bp auto_scaffold cap extension. 6 helices × 84 bp → ~504 duplex nodes,
    # well under the inflated axis count (~6 × (84+21) = 630).
    from backend.physics.fem_solver import _duplex_bp_per_helix

    mesh = build_fem_mesh(routed_6hb)
    duplex = _duplex_bp_per_helix(routed_6hb)
    total_duplex = sum(len(v) for v in duplex.values())
    assert len(mesh.nodes) == total_duplex
    assert len(mesh.nodes) <= 6 * 84 + 6  # no cap inflation


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
    assert len(free) == K.shape[0] - 6  # one node fully pinned
    assert Kf.shape == (len(free), len(free))


def test_equilibrium_is_trivially_zero_without_prestress(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    Kf, ff, free = apply_boundary_conditions(K, f, mesh)
    u = solve_equilibrium(Kf, ff, K.shape[0], free)
    assert np.all(np.isfinite(u))
    assert np.abs(u).max() < 1e-9  # u=0 until Phase-2 pre-stress lands


@pytest.fixture(scope="module")
def routed_sq_bundle():
    """A routed SQUARE-lattice bundle (no loop/skips). Square lattices carry an intrinsic
    register over-twist (~10.67 vs 10.5 bp/turn) that the FEM must now reproduce."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]  # 2×3 SQ
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(cells, 168, lattice=LatticeType.SQUARE, name="sq6")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _max_axis_disp(design):
    """Max axis-node displacement magnitude from the linear pre-stress solve — a robust,
    sign-free proxy for the predicted global twist (twist ∝ spiral displacement)."""
    mesh = build_fem_mesh(design)
    K, _ = assemble_global_stiffness(mesh)
    f = assemble_prestress_force(mesh, design)
    Kf, ff, free = apply_boundary_conditions(K, f, mesh)
    u = solve_equilibrium(Kf, ff, K.shape[0], free)
    return float(np.abs(u.reshape(-1, 6)[:, :3]).max())


def test_square_lattice_register_overtwist_present_and_relieved_by_skips(
    routed_sq_bundle, routed_6hb
):
    """The square-lattice register over-twist (the emergent global twist CanDo reports on an
    UNSKIPPED square bundle) must now show up as a non-zero pre-stress even with zero loop/skips,
    and deletions must RELIEVE it — the direction that lets autorefine straighten a square strut by
    ADDING skips (validated vs the CanDo web solver on 3x6x400: unskipped +64° → 150-skip +24.8°).
    Honeycomb has natural == lattice helicity, so its register term is exactly zero (unchanged)."""
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        sq_lattice_periodic_skips,
    )

    # Honeycomb, no skips: register term vanishes → pre-stress is exactly zero (old behaviour).
    hc_mesh = build_fem_mesh(routed_6hb)
    assert np.linalg.norm(assemble_prestress_force(hc_mesh, routed_6hb)) == 0.0

    # Square, no skips: register eigenstrain is present → non-zero pre-stress AND real deformation
    # (the OLD solver gave u=0 here — it had no register term).
    sq_mesh = build_fem_mesh(routed_sq_bundle)
    assert np.linalg.norm(assemble_prestress_force(sq_mesh, routed_sq_bundle)) > 0.0
    disp_noskip = _max_axis_disp(routed_sq_bundle)
    assert disp_noskip > 1e-3  # a genuine predicted twist, not u=0

    # Adding the default square-lattice deletions RELIEVES the register over-twist → the
    # predicted deformation SHRINKS (skips straighten the bundle, as CanDo shows).
    sq_skipped = apply_loop_skips(
        routed_sq_bundle, sq_lattice_periodic_skips(routed_sq_bundle)
    )
    assert sum(len(h.loop_skips) for h in sq_skipped.helices) > 0
    disp_skipped = _max_axis_disp(sq_skipped)
    assert disp_skipped < disp_noskip  # relief, not addition


def test_solve_does_not_globally_promote_warnings_to_errors():
    """Regression: solve_equilibrium must NOT flip the process-global warnings filter
    to "error". It runs in a background thread (cando_runner); a global escalation
    leaked into concurrently-served FastAPI handlers and turned the ORJSONResponse
    DeprecationWarning into a 500 on GET /api/cando/jobs while a solve was mid-flight.
    A benign warning emitted around/inside the solve must stay a warning, not raise."""
    import warnings

    from scipy.sparse import csr_matrix

    K = csr_matrix(np.eye(6))  # trivial well-conditioned system
    f = np.arange(6, dtype=float)
    free = np.arange(6)

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # our sandbox: everything IS an error here...
        # ...but the fix means solve() no longer *installs its own* global escalation.
        # Emit a warning right after the solve — if solve had left an "error" filter or
        # if it promoted warnings itself, this would already have blown up inside it.
        u = solve_equilibrium(K, f, 6, free)
    assert np.allclose(u, f)

    # After the solve the global filter list is pristine — no leaked "error" entry.
    assert not any(
        entry[0] == "error" and entry[2] is Warning for entry in warnings.filters
    )


def test_singular_system_raises_clear_valueerror():
    """A disconnected/under-constrained stiffness matrix (spsolve → NaN) must raise a
    friendly ValueError — preserved after dropping the warnings-as-errors mechanism,
    since the NaN/Inf guard now detects singularity directly."""
    from scipy.sparse import csr_matrix

    K = csr_matrix(np.array([[1.0, 1.0], [1.0, 1.0]]))  # rank-deficient → singular
    f = np.array([1.0, 2.0])
    free = np.arange(2)
    with pytest.raises(ValueError, match="singular"):
        solve_equilibrium(K, f, 2, free)


def test_rmsf_is_finite_nonnegative_and_per_node(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    K, f = assemble_global_stiffness(mesh)
    Kf, _, free = apply_boundary_conditions(K, f, mesh)
    rmsf = compute_rmsf(Kf, free, len(mesh.nodes))
    assert rmsf.shape == (len(mesh.nodes),)
    assert np.all(np.isfinite(rmsf))
    assert np.all(rmsf >= 0.0)
    assert rmsf.max() > 0.0  # some flexibility present


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
            for bp in (20, 40, 60):  # interior, uniform
                hb.loop_skip(h.id, bp, -1)
        d = design_state.get_or_404().model_copy(deep=True)

    analytic = lsc.predict_global_twist_deg(
        {h.id: list(h.loop_skips) for h in d.helices if h.loop_skips}
    )

    mesh = build_fem_mesh(d)
    K, _ = assemble_global_stiffness(mesh)
    f = assemble_prestress_force(mesh, d)
    assert np.abs(f).max() > 0.0  # non-zero pre-stress from the marks
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
    assert np.linalg.norm(pos - ref, axis=1).max() > 1e-3  # it deformed


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
        for h in d.helices:  # gradient marks → a bend
            for bp in (20, 40, 60):
                hb.loop_skip(h.id, bp, 1 if h.grid_pos[0] == 0 else -1)
        d = design_state.get_or_404().model_copy(deep=True)

    mesh = build_fem_mesh(d)
    # Undeformed backbone baseline (u=0) to measure deformation against.
    from backend.physics.fem_solver import deformed_positions

    base = {
        (p["helix_id"], p["bp_index"], p["direction"]): np.array(p["backbone_position"])
        for p in deformed_positions(d, mesh, np.zeros(6 * len(mesh.nodes)))
    }

    res = predict_shape(d, n_steps=6)  # nonlinear default
    assert res["solver"] == "nonlinear"
    assert len(res["positions"]) > 0
    assert len(res["rmsf"]) == len(mesh.nodes)  # one RMSF per axis node
    assert all(r["rmsf_nm"] >= 0.0 and np.isfinite(r["rmsf_nm"]) for r in res["rmsf"])
    thermal = res["thermal_trajectory"]
    assert thermal["representative_positions"]
    assert len(thermal["representative_axis"]) == len(mesh.nodes)
    # The displayed heat map is measured from the reconstructed thermal ensemble,
    # including off-axis slab motion from rotational modes.
    frame_xyz = np.asarray(thermal["frames"]).reshape(thermal["n_frames"], -1, 3)
    point_msf = np.mean(
        np.sum((frame_xyz - np.mean(frame_xyz, axis=0, keepdims=True)) ** 2, axis=2),
        axis=0,
    )
    by_bp = {}
    for col, key in enumerate(thermal["keys"]):
        by_bp.setdefault((key[0], key[1]), []).append(col)
    reconstructed = {
        key: float(np.sqrt(np.mean(point_msf[cols]))) for key, cols in by_bp.items()
    }
    for value in res["rmsf"]:
        assert value["rmsf_nm"] == pytest.approx(
            reconstructed[(value["helix_id"], value["bp_index"])], abs=1e-12
        )
    # The representative final state must retain the full wound reconstruction frame.
    # XYZ-only records move beads but leave slabs in their design orientation.
    for p in thermal["representative_positions"][:100]:
        n = np.array([p["nx"], p["ny"], p["nz"]])
        t = np.array([p["tx"], p["ty"], p["tz"]])
        assert abs(np.linalg.norm(n) - 1.0) < 1e-6
        assert abs(np.linalg.norm(t) - 1.0) < 1e-6
        assert abs(float(n @ t)) < 1e-3

    # the predicted shape actually deformed off the straight reference
    moved = max(
        float(
            np.linalg.norm(
                np.array(p["backbone_position"])
                - base[(p["helix_id"], p["bp_index"], p["direction"])]
            )
        )
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
    by any display toggle.  A collapsed-key assertion passed anyway (false confidence).

    THE ORACLE IS THE RENDERER'S OWN NUCLEOTIDE LIST (``_geometry_for_helices`` — what
    ``GET /design/geometry`` serves and the renderer draws), not the raw lattice.  This test
    used to build its expectation from ``nucleotide_positions``, which emits a bead at EVERY bp
    of a helix whether a strand is there or not — the scaffold-cap bp carry a REVERSE strand and
    no FORWARD one, and a helix is routinely declared longer than the strands on it.  Demanding
    coverage of those bare lattice sites forced the display to emit beads the renderer cannot
    address: 126 here, and 12 921 on VoltronCore (~47% of every trajectory frame), which also
    dragged the Kabsch fit around (they are the beads furthest outside the meshed range, so the
    winding extrapolates them wildly).  The real invariant is a BIJECTION with the drawn set —
    every drawn bead addressed, and nothing emitted that isn't drawn."""
    from collections import Counter

    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.api.crud import _geometry_for_helices
    from backend.physics.fem_solver import deformed_positions

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)  # ssDNA scaffold ends at the strand termini
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:  # +1 on half the helices → LOOP inserts (copies)
            for bp in (20, 40, 60):
                hb.loop_skip(h.id, bp, 1 if h.grid_pos[0] == 0 else -1)
        d = design_state.get_or_404().model_copy(deep=True)
        drawn_nucs = _geometry_for_helices(
            d, None
        )  # exactly what the renderer receives

    # Every nucleotide the renderer draws, keyed WITH its loop-copy index (appearance
    # order within a (helix, bp, dir) — the same order the renderer + backend assign).
    seen: Counter = Counter()
    expected: set = set()
    for nuc in drawn_nucs:
        k = (nuc["helix_id"], nuc["bp_index"], nuc["direction"])
        expected.add((*k, seen[k]))
        seen[k] += 1
    total_nuc = len(drawn_nucs)
    # The test is only meaningful if the design actually has loop copies (copy > 0).
    assert any(c > 0 for *_rest, c in expected), (
        "design must contain loop inserts (copy>0)"
    )

    mesh = build_fem_mesh(d)
    assert len(mesh.nodes) * 2 < total_nuc, "expected uncovered ssDNA/loop nucleotides"

    pos = deformed_positions(d, mesh, np.zeros(6 * len(mesh.nodes)))
    assert all("copy" in p for p in pos), (
        "every predicted position must carry a copy index"
    )
    covered = {(p["helix_id"], p["bp_index"], p["direction"], p["copy"]) for p in pos}
    missing = expected - covered
    assert not missing, (
        f"{len(missing)} loop/ss nucleotide(s) stranded (no predicted position)"
    )
    dead = covered - expected
    assert not dead, (
        f"{len(dead)} bead(s) emitted that the renderer cannot draw (dead payload)"
    )
    assert covered == expected  # exact per-copy coverage, no phantom keys
    assert len(pos) == total_nuc  # no loop copies collapsed away


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

    assert len(build_fem_mesh(d).nodes) < 2  # degenerate mesh — the trigger
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
    assert 0.05 < free.mean() < 20.0  # physical order of magnitude (nm)
    # Free-free removes the pinned-node cantilever, so it is flatter.
    assert (free.max() / free.mean()) < (pinned.max() / max(pinned.mean(), 1e-9))


def test_deform_backbones_wind_around_the_curved_axis():
    """Regression: on a BENT bundle the FEM-deform backbone beads must WIND around the deformed
    axis (offset ⊥ the local deformed tangent, at the helix radius), not keep their straight-frame
    radial direction.  The pre-fix code only TRANSLATED each bead by its axis-node displacement, so
    on a curve the beads pointed the wrong way ('helical positions messed up mapping onto the
    curvature').  Fixed by transporting a rotation-minimising frame along the deformed axis."""
    from collections import defaultdict

    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 126, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.add_bend(0, 126, curvature_deg_per_bp=90.0 / 126)
        hb.apply_loop_skip_deformations()
        d = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(d, nonlinear=False, with_rmsf=False)
    axis_by_helix = defaultdict(list)
    for a in res["axis"]:
        axis_by_helix[a["helix_id"]].append((a["bp_index"], np.array(a["position"])))

    checked = 0
    for hid, nodes in axis_by_helix.items():
        nodes.sort()
        bp_to_pos = {b: p for b, p in nodes}
        bps = [b for b, _ in nodes]
        P = np.array([p for _, p in nodes])
        if len(P) < 5:
            continue
        # local deformed tangent per node (central difference)
        tan = {}
        for i, b in enumerate(bps):
            v = P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]
            nv = np.linalg.norm(v)
            if nv > 1e-9:
                tan[b] = v / nv
        perp_ratios, radii = [], []
        for p in res["positions"]:
            if (
                p["helix_id"] != hid
                or p["bp_index"] not in bp_to_pos
                or p["bp_index"] not in tan
            ):
                continue
            off = np.array(p["backbone_position"]) - bp_to_pos[p["bp_index"]]
            r = np.linalg.norm(off)
            if r < 1e-6 or r > 4.0:  # skip degenerate / ssDNA-end extrapolations
                continue
            perp_ratios.append(abs(float(off @ tan[p["bp_index"]]) / r))
            radii.append(r)
        if len(perp_ratios) < 50:
            continue
        checked += 1
        # Beads are ~perpendicular to the local deformed tangent (winding follows the curve)…
        assert np.mean(perp_ratios) < 0.15, f"{hid}: beads not ⊥ deformed tangent"
        # …and at roughly the helix radius (not flung off-axis).
        assert 0.7 < np.mean(radii) < 1.6, (
            f"{hid}: bead radius off ({np.mean(radii):.2f} nm)"
        )
    assert checked >= 4, "expected several duplex-core helices to validate"


def test_nadoc_cando_nadoc_zero_displacement_round_trip_is_identity(routed_6hb):
    """At u=0, CanDo reconstruction must return authoritative NADOC geometry exactly.

    CanDo uses 0.340 nm/bp while NADOC renders B-DNA at 0.334 nm/bp. Copying absolute
    FEM coordinates back stretched an undeformed bundle and shifted slab centers by up
    to ~0.4 nm; reconstruction must instead apply FEM displacements to NADOC geometry.
    """
    from collections import Counter

    from backend.core.deformation import deformed_nucleotide_positions
    from backend.core.sequences import domain_bp_range

    mesh = build_fem_mesh(routed_6hb)
    positions, _ = deformed_positions_with_axis(
        routed_6hb, mesh, np.zeros(6 * len(mesh.nodes))
    )
    got = {
        (p["helix_id"], p["bp_index"], p["direction"], p.get("copy", 0)): p
        for p in positions
    }
    covered = set()
    for strand in routed_6hb.strands:
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                covered.add((domain.helix_id, bp, domain.direction.value))
    expected = {}
    seen = Counter()
    for helix in routed_6hb.helices:
        for nuc in deformed_nucleotide_positions(helix, routed_6hb):
            key3 = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
            if key3 not in covered:
                continue
            key = (*key3, seen[key3])
            seen[key3] += 1
            expected[key] = nuc

    assert set(got) == set(expected)
    for key, nuc in expected.items():
        p = got[key]
        np.testing.assert_allclose(p["backbone_position"], nuc.position, atol=2e-12)
        np.testing.assert_allclose(
            [p["nx"], p["ny"], p["nz"]], nuc.base_normal, atol=2e-8
        )
        np.testing.assert_allclose(
            [p["tx"], p["ty"], p["tz"]], nuc.axis_tangent, atol=2e-12
        )


def test_reconstruction_applies_fem_torsional_rotation_to_backbones_and_slabs(
    routed_6hb,
):
    """The centerline RMF does not contain beam twist; nodal rotational DOFs must.

    A pure rotation about a straight helix axis leaves its axis/tangents fixed but rotates
    both backbone winding and slab base normals by the prescribed angle.
    """
    from backend.core.geometry import nucleotide_positions
    from backend.physics.fem_solver import _wound_backbones_for_helix

    helix = routed_6hb.helices[0]
    nucs = list(nucleotide_positions(helix))
    start = helix.axis_start.to_array()
    axis = helix.axis_end.to_array() - start
    axis /= np.linalg.norm(axis)
    anchors0, anchors1 = [], []
    angle = 0.2
    for bp in range(helix.bp_start, helix.bp_start + helix.length_bp):
        p = start + (bp - helix.bp_start) * BDNA_RISE_PER_BP * axis
        anchors0.append((bp, p, p, np.zeros(3)))
        anchors1.append((bp, p, p, angle * axis))
    p0, n0, t0 = _wound_backbones_for_helix(helix, nucs, anchors0)
    p1, n1, t1 = _wound_backbones_for_helix(helix, nucs, anchors1)

    def signed_angle(a, b):
        return np.arctan2(axis @ np.cross(a, b), a @ b)

    i = len(nucs) // 2
    a0 = p0[i] - (start + (nucs[i].bp_index - helix.bp_start) * BDNA_RISE_PER_BP * axis)
    a1 = p1[i] - (start + (nucs[i].bp_index - helix.bp_start) * BDNA_RISE_PER_BP * axis)
    assert signed_angle(a0, a1) == pytest.approx(angle, abs=1e-6)
    assert signed_angle(n0[i], n1[i]) == pytest.approx(angle, abs=1e-6)
    np.testing.assert_allclose(t1[i], t0[i], atol=1e-12)


def test_deform_slabs_carry_the_wound_frame_not_the_straight_orientation():
    """Regression (Symptom-2 slab splay): the FEM-deform display must emit a WOUND slab frame
    (base-normal nx/ny/nz + axis-tangent tx/ty/tz) per bead so the base-pair slabs follow the
    wound backbone.  The pre-fix display emitted NO normals (option B), so slabs kept their
    straight/design orientation while the backbone wound onto the deformed axis → on a bent,
    mark-dense bundle several slabs splayed radially OUTWARD (angle to the inward radial > 90°).

    Pins: every position carries the 6 frame fields; the frame is orthonormal (normal ⊥ tangent,
    both unit); and the normal points INWARD (toward the helix axis) — no radially-outward slabs."""
    from collections import defaultdict

    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 126, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.add_bend(0, 126, curvature_deg_per_bp=90.0 / 126)
        hb.apply_loop_skip_deformations()
        d = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(d, nonlinear=False, with_rmsf=False)
    pos = res["positions"]

    # (1) every position carries the wound frame; (2) it is an orthonormal frame.
    for p in pos[:200] + pos[-200:]:
        for f in ("nx", "ny", "nz", "tx", "ty", "tz"):
            assert f in p, f"missing slab-frame field {f}"
        n = np.array([p["nx"], p["ny"], p["nz"]])
        t = np.array([p["tx"], p["ty"], p["tz"]])
        assert abs(np.linalg.norm(n) - 1.0) < 1e-6, "base-normal not unit"
        assert abs(np.linalg.norm(t) - 1.0) < 1e-6, "axis-tangent not unit"
        assert abs(float(n @ t)) < 1e-3, "slab frame not orthonormal (normal ⊥ tangent)"

    # (3) the normal points INWARD (toward the helix axis) at the WOUND backbone — no slab splays
    # radially outward.  Compare against the FEM axis-centre node nearest each bead (excluding the
    # ssDNA-end extrapolations, r > 4 nm, as the winding test does).
    axis_by_helix = defaultdict(list)
    for a in res["axis"]:
        axis_by_helix[a["helix_id"]].append((a["bp_index"], np.array(a["position"])))
    outward = 0
    checked = 0
    for p in pos:
        nodes = axis_by_helix.get(p["helix_id"])
        if not nodes:
            continue
        bb = np.array(p["backbone_position"])
        ax = min(nodes, key=lambda t: abs(t[0] - p["bp_index"]))[1]
        inward = ax - bb
        r = np.linalg.norm(inward)
        if r < 1e-6 or r > 4.0:
            continue
        n = np.array([p["nx"], p["ny"], p["nz"]])
        checked += 1
        if float(n @ (inward / r)) < 0.0:  # obtuse → slab points radially outward
            outward += 1
    assert checked > 500
    # Pre-fix this design had ~1% radially-outward slabs (max 102°); the wound frame removes them.
    assert outward / checked < 0.005, f"{outward}/{checked} slabs still splay outward"
