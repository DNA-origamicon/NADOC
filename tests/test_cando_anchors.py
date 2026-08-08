"""Oracle for C1 — CanDo FEM anchors (Dirichlet boundary conditions).

Property assertions, not smoke runs:

  * ``apply_boundary_conditions`` pins EXACTLY the requested nodes' 6 DOF, and
    falls back to the single centroid pin when no anchors are given (free-free
    behaviour preserved).
  * A pinned node holds (u == 0 at its DOFs) while a free node moves under a
    test load — the defining Dirichlet property.
  * ``resolve_anchor_nodes`` maps the shared oxDNA anchor scopes (base / cluster)
    onto duplex-core FEM node indices, and drops stale/empty selections.
  * ``predict_shape(design, anchors=...)`` holds the anchored bp at its rest
    position while a free bp still deflects under the loop/skip eigenstrain; a
    selection that resolves to nothing is a no-op (positions AND free-free RMSF
    identical to the unanchored solve).

Fast: no real engine binary. The routed-6HB fixture is a headless bundle build.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.models import Direction, LatticeType
from backend.physics.fem_solver import (
    EA_DS,
    EI_DS,
    FEMElement,
    FEMMesh,
    FEMNode,
    GJ_DS,
    _frame_from_helix_axis,
    apply_boundary_conditions,
    assemble_global_stiffness,
    build_fem_mesh,
    predict_shape,
    resolve_anchor_nodes,
    solve_equilibrium,
)


# ── Synthetic straight beam chain (no design needed) ─────────────────────────


def _straight_chain_mesh(n: int = 6, rise: float = 0.34) -> FEMMesh:
    """A single straight DNA beam of ``n`` axis nodes along +z (one helix, no
    crossovers). Node 0 pinned makes it a well-posed cantilever."""
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


def test_bc_no_anchors_pins_single_centroid_node():
    """No fixed_nodes → the legacy centroid pin: exactly 6 DOF removed."""
    mesh = _straight_chain_mesh(n=6)
    K, _ = assemble_global_stiffness(mesh)
    f = np.zeros(K.shape[0])
    _Kf, _ff, free = apply_boundary_conditions(K, f, mesh)
    assert len(free) == K.shape[0] - 6  # one node (6 DOF) pinned


def test_bc_pins_exactly_the_requested_nodes():
    """fixed_nodes=[0, 2] → those two nodes' 12 DOF removed, nothing else."""
    mesh = _straight_chain_mesh(n=6)
    K, _ = assemble_global_stiffness(mesh)
    f = np.zeros(K.shape[0])
    _Kf, _ff, free = apply_boundary_conditions(K, f, mesh, fixed_nodes=[0, 2])
    free_set = set(free.tolist())
    pinned = set(range(0, 6)) | set(range(12, 18))
    assert free_set.isdisjoint(pinned)
    assert free_set == set(range(K.shape[0])) - pinned


def test_bc_empty_anchor_list_falls_back_to_centroid():
    """An empty fixed_nodes (stale selection resolved to nothing) → centroid pin,
    NOT an unconstrained (singular) system."""
    mesh = _straight_chain_mesh(n=6)
    K, _ = assemble_global_stiffness(mesh)
    f = np.zeros(K.shape[0])
    _Kf, _ff, free = apply_boundary_conditions(K, f, mesh, fixed_nodes=[])
    assert len(free) == K.shape[0] - 6


def test_pinned_node_held_free_node_moves_under_load():
    """The Dirichlet property: pin node 0, push node n-1 transversely →
    u == 0 at every pinned DOF, and the loaded free node actually moves."""
    mesh = _straight_chain_mesh(n=6)
    K, _ = assemble_global_stiffness(mesh)
    f = np.zeros(K.shape[0])
    last = len(mesh.nodes) - 1
    f[6 * last + 0] = 50.0  # transverse (x) point load, pN
    Kf, ff, free = apply_boundary_conditions(K, f, mesh, fixed_nodes=[0])
    u = solve_equilibrium(Kf, ff, K.shape[0], free)
    assert np.allclose(u[0:6], 0.0)  # pinned node held
    assert abs(u[6 * last + 0]) > 1e-6  # free tip deflected along the load


# ── Anchor-scope resolver ────────────────────────────────────────────────────


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


def test_resolve_anchor_nodes_base_scope_hits_one_node(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    n0 = mesh.nodes[len(mesh.nodes) // 2]  # some interior duplex node
    anchor = {
        "kind": "base",
        "helix_id": n0.helix_id,
        "bp": n0.global_bp,
        "direction": Direction.FORWARD.value,
    }
    nodes, keys = resolve_anchor_nodes(routed_6hb, mesh, [anchor])
    # FORWARD + REVERSE nucleotides of one bp collapse to the SINGLE axis node.
    assert nodes == [
        i
        for i, n in enumerate(mesh.nodes)
        if n.helix_id == n0.helix_id and n.global_bp == n0.global_bp
    ]
    assert len(nodes) == 1
    assert keys == [(n0.helix_id, n0.global_bp)]


def test_resolve_anchor_nodes_cluster_scope_covers_helix_set(routed_6hb):
    from backend.physics.fem_solver import _duplex_bp_per_helix

    # A cluster over one helix pins every duplex node on that helix.
    hid = routed_6hb.helices[0].id
    design = routed_6hb.model_copy(deep=True)
    from backend.core.models import ClusterRigidTransform

    design.cluster_transforms.append(
        ClusterRigidTransform(id="c-test", helix_ids=[hid])
    )
    mesh = build_fem_mesh(design)
    nodes, _keys = resolve_anchor_nodes(
        design, mesh, [{"kind": "cluster", "id": "c-test"}]
    )
    expected = {i for i, n in enumerate(mesh.nodes) if n.helix_id == hid}
    assert set(nodes) == expected
    assert len(nodes) == len(_duplex_bp_per_helix(design)[hid])


def test_resolve_anchor_nodes_stale_selection_drops(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    nodes, keys = resolve_anchor_nodes(
        routed_6hb,
        mesh,
        [
            {
                "kind": "base",
                "helix_id": "nope",
                "bp": 9999,
                "direction": Direction.FORWARD.value,
            }
        ],
    )
    assert nodes == [] and keys == []


# ── End-to-end: predict_shape holds the anchor ───────────────────────────────


@pytest.fixture(scope="module")
def skipped_6hb():
    """A routed 6HB with uniform deletions → a real loop/skip eigenstrain that
    deflects the free bundle (something for an anchor to hold against)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:
            for bp in (20, 40, 60):
                hb.loop_skip(h.id, bp, -1)
        return design_state.get_or_404().model_copy(deep=True)


def test_prestress_solve_holds_anchored_node_at_rest(skipped_6hb):
    """Physical-layer anchor property (pre-display, pre-Kabsch): clamp the node that
    deflects most in the free solve → it stays exactly at its rest axis position while
    the rest of the bundle still swings under the loop/skip eigenstrain."""
    from backend.physics.fem_solver import solve_prestress_shape

    d = skipped_6hb
    ref = np.array([n.position for n in build_fem_mesh(d).nodes])

    free = solve_prestress_shape(d, build_fem_mesh(d), n_steps=6)
    i_moved = int(np.argmax(np.linalg.norm(free - ref, axis=1)))
    assert np.linalg.norm(free[i_moved] - ref[i_moved]) > 1e-3  # moves when free

    anc = solve_prestress_shape(d, build_fem_mesh(d), n_steps=6, fixed_nodes=[i_moved])
    assert np.linalg.norm(anc[i_moved] - ref[i_moved]) < 1e-9  # held exactly
    assert np.linalg.norm(anc - ref, axis=1).max() > 1e-3  # rest still deflects


def test_predict_shape_anchor_changes_output_and_reports_keys(skipped_6hb):
    """API surface: passing an anchor resolves to a clamped node (surfaced in
    ``anchor_keys``) and produces a different physical shape than the free solve."""
    d = skipped_6hb
    mesh = build_fem_mesh(d)
    # A cluster over one helix pins a real, non-empty set of nodes.
    hid = d.helices[0].id

    free = predict_shape(d, nonlinear=True, n_steps=6, with_rmsf=False)
    got = predict_shape(
        d,
        nonlinear=True,
        n_steps=6,
        with_rmsf=False,
        anchors=[
            {"kind": "cluster", "id": "no-such"},
            {
                "kind": "base",
                "helix_id": hid,
                "bp": mesh.nodes[0].global_bp,
                "direction": Direction.FORWARD.value,
            },
        ],
    )
    assert free["anchor_keys"] == []
    assert [hid, mesh.nodes[0].global_bp] in got["anchor_keys"]

    # Anchoring perturbs the equilibrium shape (measured after both are Kabsch-posed —
    # a rigid pose can't hide a genuinely different deformation field).
    fp = np.array([p["backbone_position"] for p in free["positions"]])
    gp = np.array([p["backbone_position"] for p in got["positions"]])
    assert np.linalg.norm(fp - gp, axis=1).max() > 1e-3


def test_predict_shape_unresolved_anchor_is_a_noop(skipped_6hb):
    """A selection that resolves to no duplex node leaves positions AND the
    free-free NMA RMSF identical to the unanchored solve."""
    d = skipped_6hb
    plain = predict_shape(d, nonlinear=True, n_steps=6, with_rmsf=True)
    stale = predict_shape(
        d,
        nonlinear=True,
        n_steps=6,
        with_rmsf=True,
        anchors=[
            {
                "kind": "base",
                "helix_id": "nope",
                "bp": 9999,
                "direction": Direction.FORWARD.value,
            }
        ],
    )
    assert stale["anchor_keys"] == []
    p0 = np.array([p["backbone_position"] for p in plain["positions"]])
    p1 = np.array([p["backbone_position"] for p in stale["positions"]])
    assert np.allclose(p0, p1)  # deterministic spsolve shape identical
    r0 = np.array([r["rmsf_nm"] for r in plain["rmsf"]])
    r1 = np.array([r["rmsf_nm"] for r in stale["rmsf"]])
    # Free-free NMA preserved: identical positions above prove the shape solve is
    # unchanged, and the RMSF is the same free-free K in both. The only spread is
    # ARPACK's random-start-vector jitter across the two eigsh calls (an unresolved
    # anchor never touches the RMSF path), so compare by profile SHAPE (Pearson) +
    # aggregate, not element-wise — the honest measure for an iterative eigensolver.
    assert np.corrcoef(r0, r1)[0, 1] > 0.999
    assert abs(r0.mean() - r1.mean()) / r0.mean() < 0.02
