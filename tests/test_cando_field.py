"""Oracle for C2 — CanDo FEM uniform E-field deflection.

Property assertions, not smoke runs. The pass criterion is the SHARED S4 field-response
descriptor (``shape_metrics.field_response_profile``) measured on the FEM deflected frame
vs the same design's field-OFF frame — the exact cross-engine-comparable check oxDNA is
scored against:

  * ``assemble_field_force`` builds a uniform per-node body load = 2·force_per_nt·dir_hat
    (a duplex node carries both strands' backbones), translational DOF only, and is an
    exact no-op for None / zero magnitude / zero direction.  Magnitude scales linearly.
  * With one end cross-section anchored, a transverse field deflects the FREE region
    ALONG the field (S4 ``passed``) while the anchored nodes hold (drift ≤ tol).
  * The deflection is MONOTONE in field magnitude (2× field → larger along-field motion).
  * ZERO field → no deflection (free along-field motion ≈ 0); ``field=None`` is identical
    to omitting the field entirely.

Fast: no real engine binary — the 6HB fixture is a headless bundle build + in-process solve.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.models import Direction, LatticeType
from backend.core.shape_metrics import field_response_profile
from backend.physics.fem_solver import (
    EA_DS,
    EI_DS,
    FEM_FIELD_CHARGES_PER_NODE,
    FEMElement,
    FEMMesh,
    FEMNode,
    GJ_DS,
    _frame_from_helix_axis,
    assemble_field_force,
    build_fem_mesh,
    predict_shape,
    resolve_anchor_nodes,
    solve_prestress_shape,
)


# ── assemble_field_force: pure body-load property tests (no design) ──────────


def _straight_chain_mesh(n: int = 6, rise: float = 0.34) -> FEMMesh:
    axis = _frame_from_helix_axis(np.array([0.0, 0.0, 1.0]))
    nodes = [
        FEMNode(helix_id="h0", global_bp=i, position=np.array([0.0, 0.0, i * rise]))
        for i in range(n)
    ]
    elems = [
        FEMElement(
            node_i=i, node_j=i + 1, length=rise, R=axis, ea=EA_DS, ei=EI_DS, gj=GJ_DS
        )
        for i in range(n - 1)
    ]
    return FEMMesh(nodes=nodes, elements=elems)


def test_field_force_none_and_zero_are_noops():
    mesh = _straight_chain_mesh(6)
    zero = np.zeros(6 * len(mesh.nodes))
    assert np.array_equal(assemble_field_force(mesh, None), zero)
    assert np.array_equal(assemble_field_force(mesh, {}), zero)
    assert np.array_equal(
        assemble_field_force(mesh, {"field_pN": 0.0, "dir": [1, 0, 0]}), zero
    )
    assert np.array_equal(
        assemble_field_force(mesh, {"field_pN": 5.0, "dir": [0, 0, 0]}), zero
    )


def test_field_force_direction_and_charges_per_node():
    """Every node gets 2·force_per_nt along dir_hat on its 3 translational DOF, zero
    on the 3 rotational DOF (a body force carries no couple)."""
    mesh = _straight_chain_mesh(4)
    f = assemble_field_force(mesh, {"field_pN": 3.0, "dir": [0.0, 4.0, 3.0]})  # |dir|=5
    expected = FEM_FIELD_CHARGES_PER_NODE * 3.0 * np.array([0.0, 0.8, 0.6])
    for node in range(len(mesh.nodes)):
        assert np.allclose(f[6 * node : 6 * node + 3], expected)  # translational
        assert np.allclose(f[6 * node + 3 : 6 * node + 6], 0.0)  # rotational


def test_field_force_scales_linearly_with_magnitude():
    mesh = _straight_chain_mesh(5)
    f1 = assemble_field_force(mesh, {"field_pN": 2.0, "dir": [1, 0, 0]})
    f2 = assemble_field_force(mesh, {"field_pN": 4.0, "dir": [1, 0, 0]})
    assert np.allclose(f2, 2.0 * f1)


# ── End-to-end: predict_shape(field=...) scored by the shared S4 descriptor ──


@pytest.fixture(scope="module")
def straight_6hb():
    """A routed 6HB with NO skips → field-off shape is essentially at rest, so the
    field-response measures ONLY the field-induced deflection."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


# The S4 field-response is measured on the RAW solved axis-node frame (the field-off
# and field-on solves share the SAME clamped anchors, so the anchored region is a genuine
# common frame — anchored nodes sit at identical rest positions in both). We deliberately
# do NOT use predict_shape's `positions`: those are Kabsch-RE-POSED onto the displayed
# design geometry (deformed_positions_with_axis) with a per-frame rigid transform, so the
# straight and bent frames land in DIFFERENT poses and the anchor would spuriously "drift"
# ~5 nm. The C5 field-source builder must likewise emit field-response from the raw frame.
_N_STEPS = 8  # corotational increments — converged for these gentle fields (see C2 log)


def _end_anchor_nodes_and_transverse_dir(design):
    """Anchor the low-bp end cross-section (one base anchor per helix at its start bp),
    resolve it to FEM node indices, and return a unit field direction PERPENDICULAR to
    the bundle's long axis, so the field bends the free end like a tethered cantilever."""
    mesh = build_fem_mesh(design)
    min_bp = {}
    for n in mesh.nodes:
        min_bp[n.helix_id] = min(min_bp.get(n.helix_id, n.global_bp), n.global_bp)
    anchors = [
        {
            "kind": "base",
            "helix_id": hid,
            "bp": bp,
            "direction": Direction.FORWARD.value,
        }
        for hid, bp in min_bp.items()
    ]
    fixed_nodes, keys = resolve_anchor_nodes(design, mesh, anchors)
    pos = np.array([n.position for n in mesh.nodes])
    axis_hat = np.linalg.svd(pos - pos.mean(0), full_matrices=False)[2][0]
    trial = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(trial, axis_hat)) > 0.9:
        trial = np.array([0.0, 1.0, 0.0])
    perp = trial - np.dot(trial, axis_hat) * axis_hat
    return mesh, fixed_nodes, keys, perp / np.linalg.norm(perp)


def _node_position_map(mesh, node_positions):
    """The raw solved axis-node positions as an S4 display-position map (one 'forward'
    entry per bp node — the axis deflection IS the FEM field response)."""
    return [
        {
            "helix_id": n.helix_id,
            "bp_index": n.global_bp,
            "direction": "forward",
            "backbone_position": [float(x) for x in node_positions[i]],
        }
        for i, n in enumerate(mesh.nodes)
    ]


def _fem_field_response(design, mesh, fixed_nodes, keys, field_dir, field_pN):
    field = (
        None
        if field_pN is None
        else {"field_pN": field_pN, "dir": [float(x) for x in field_dir]}
    )
    ref = solve_prestress_shape(
        design,
        build_fem_mesh(design),
        n_steps=_N_STEPS,
        fixed_nodes=fixed_nodes,
        field=None,
    )
    cand = solve_prestress_shape(
        design,
        build_fem_mesh(design),
        n_steps=_N_STEPS,
        fixed_nodes=fixed_nodes,
        field=field,
    )
    return field_response_profile(
        _node_position_map(mesh, cand),
        _node_position_map(mesh, ref),
        field_dir,
        [(h, bp, "forward") for (h, bp) in keys],
    )


def test_anchored_field_deflects_free_region_along_field(straight_6hb):
    """The headline C2 property: anchors held, free region deflects along the field —
    exactly the S4 verdict oxDNA is scored on."""
    mesh, fixed, keys, fdir = _end_anchor_nodes_and_transverse_dir(straight_6hb)
    assert len(fixed) == 6  # one node per helix resolved
    fr = _fem_field_response(straight_6hb, mesh, fixed, keys, fdir, field_pN=0.1)

    assert fr["n_anchored"] > 0 and fr["n_free"] > 0
    assert fr["passed"], fr["reason"]
    assert fr["anchored_max_drift_nm"] <= 1.0  # tethered end holds (clamped: ~0)
    assert fr["free_proj_along_field_nm"] >= 0.5  # free end swings along the field


def test_deflection_is_monotone_in_field_magnitude(straight_6hb):
    mesh, fixed, keys, fdir = _end_anchor_nodes_and_transverse_dir(straight_6hb)
    small = _fem_field_response(straight_6hb, mesh, fixed, keys, fdir, field_pN=0.05)
    large = _fem_field_response(straight_6hb, mesh, fixed, keys, fdir, field_pN=0.1)
    assert large["free_proj_along_field_nm"] > small["free_proj_along_field_nm"] + 1e-3


def test_zero_field_produces_no_deflection(straight_6hb):
    """field_pN=0 → the free region does not move along the field (RED guard: a
    non-zero along-field motion here would mean the eigenstrain, not the field, is
    driving the response)."""
    mesh, fixed, keys, fdir = _end_anchor_nodes_and_transverse_dir(straight_6hb)
    fr = _fem_field_response(straight_6hb, mesh, fixed, keys, fdir, field_pN=0.0)
    assert abs(fr["free_proj_along_field_nm"]) < 1e-6
    assert not fr["passed"]


def test_predict_shape_field_threads_through_and_changes_shape(straight_6hb):
    """The public entry point: predict_shape(field=...) reaches the solve and produces a
    different displayed shape than the field-off solve (a field=None no-op is identical)."""
    mesh, fixed, keys, fdir = _end_anchor_nodes_and_transverse_dir(straight_6hb)
    anchors = [
        {"kind": "base", "helix_id": h, "bp": b, "direction": Direction.FORWARD.value}
        for (h, b) in keys
    ]
    off = predict_shape(
        straight_6hb, nonlinear=True, n_steps=_N_STEPS, with_rmsf=False, anchors=anchors
    )
    none = predict_shape(
        straight_6hb,
        nonlinear=True,
        n_steps=_N_STEPS,
        with_rmsf=False,
        anchors=anchors,
        field=None,
    )
    on = predict_shape(
        straight_6hb,
        nonlinear=True,
        n_steps=_N_STEPS,
        with_rmsf=False,
        anchors=anchors,
        field={"field_pN": 0.1, "dir": list(fdir)},
    )
    p_off = np.array([p["backbone_position"] for p in off["positions"]])
    p_none = np.array([p["backbone_position"] for p in none["positions"]])
    p_on = np.array([p["backbone_position"] for p in on["positions"]])
    assert np.array_equal(p_off, p_none)  # field=None is a no-op
    assert np.linalg.norm(p_on - p_off, axis=1).max() > 0.5  # field bent the shape
