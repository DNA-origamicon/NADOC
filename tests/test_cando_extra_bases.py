"""Oracle for C3 — CanDo FEM extra crossover bases as compliant connector elements.

`Crossover.extra_bases` (single-stranded thymines that relieve junction strain) are a
JOB-REQUEST/topology-metadata READ, never a Design mutation (Three-Layer Law).  In the
CanDo FEM they turn a crossover from a rigid zero-length link into a compliant ssDNA
connector — CanDo's CONN3D2 analogue: a 2-node WLC spring between the two existing duplex
axis nodes (no added mesh nodes; CanDo models ssDNA connections as connectors between
existing bp nodes, not extra beam nodes).  The mechanism has lived in ``build_fem_mesh``
since the Phase-5 ship but was never property-tested — this file is that oracle.

The pass criterion (bright line): a design WITH inserts vs WITHOUT yields a **measurable,
correct-sign softening** that is comparable across engines, not just "it ran".

  FAST (deterministic, no NMA):
    * an extra-base crossover meshes as a compliant WLC spring (k_rot == 0), removed from
      the rigid-link set — the mesh reflects inserts (spring count == #inserted crossovers);
    * the spring softens monotonically with insert length and is orders of magnitude more
      compliant than a rigid link (matches the WLC low-force stiffness 3·kT/(2·L_c·L_p));
    * under the SAME transverse load a compliant crossover lets its node deflect far more
      than a rigid link (compliance, unambiguous sign for a single connector).

  SLOW (real in-process ``predict_shape`` + free-free NMA — conftest-registered):
    * inserts on a band of crossovers raise the LOCAL flexibility (per-bp RMSF) at the
      inserted-crossover nodes measurably (CanDo's reference observable), every affected
      node getting more flexible — surfaced through the shared S3 ``compare_descriptors``
      RMSF channel so it is a genuine cross-engine-comparable prediction.

We deliberately do NOT assert a twist/bend *direction*: softening inter-helix coupling
redistributes a distributed field/eigenstrain load non-monotonically (verified: the free
along-field projection is not a clean function of insert count), and reasoning about the
sign geometrically is exactly what the crossover rules forbid.  RMSF (flexibility) is the
physically-unambiguous softening signal, and it is CanDo's designated observable.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse.linalg import spsolve

from backend.core.models import LatticeType
from backend.core.shape_metrics import compute_shape_descriptors, compare_descriptors
from backend.physics.fem_solver import (
    KBT,
    K_PENALTY,
    L_P_SS,
    RISE_SS,
    FEMMesh,
    FEMNode,
    FEMRigidLink,
    FEMSpring,
    assemble_global_stiffness,
    build_fem_mesh,
    predict_shape,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def routed_6hb():
    """A routed 6HB honeycomb bundle (no inserts) — the base design each test perturbs."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _with_inserts(design, seq="TT", predicate=lambda i, xo: True):
    """Copy the design and stamp ``extra_bases=seq`` on crossovers matching ``predicate``.

    Building a design variant with inserts is fixture construction (the FEM only READS
    ``Crossover.extra_bases``); no topology is mutated in the solver.  Returns
    (variant, n_inserted, {(helix_id, bp) endpoint keys of inserted crossovers})."""
    d = design.model_copy(deep=True)
    n = 0
    keys: set = set()
    for i, xo in enumerate(d.crossovers):
        if predicate(i, xo):
            xo.extra_bases = seq
            n += 1
            keys.add((xo.half_a.helix_id, xo.half_a.index))
            keys.add((xo.half_b.helix_id, xo.half_b.index))
    return d, n, keys


def _wlc_k_trans(n_extra: int) -> float:
    """The WLC low-force stiffness ``build_fem_mesh`` assigns an n-base ssDNA connector."""
    L_c = n_extra * RISE_SS
    return 3.0 * KBT / (2.0 * L_c * L_P_SS)


# ── FAST: the mesh reflects inserts (rigid link → compliant WLC spring) ───────

def test_extra_base_crossovers_mesh_as_compliant_springs(routed_6hb):
    """Every crossover carrying extra bases becomes a WLC spring (k_rot == 0) and leaves
    the rigid-link set; a plain crossover stays a rigid link.  The mesh's connector census
    reflects the inserts (spring count == #inserted crossovers)."""
    base_mesh = build_fem_mesh(routed_6hb)
    assert len(base_mesh.springs) == 0
    n_rigid0 = len(base_mesh.rigid_links)
    assert n_rigid0 > 0

    # Insert on every OTHER crossover so both connector types coexist in one mesh.
    variant, n_ins, _ = _with_inserts(routed_6hb, "TT", predicate=lambda i, xo: i % 2 == 0)
    assert 0 < n_ins < len(routed_6hb.crossovers)
    mesh = build_fem_mesh(variant)

    # Inserted crossovers → compliant springs; the rest stay rigid links. Total coupling
    # count is conserved (each crossover is still exactly one connector).
    assert len(mesh.springs) == n_ins
    assert len(mesh.rigid_links) == n_rigid0 - n_ins
    assert len(mesh.springs) + len(mesh.rigid_links) == n_rigid0
    for sp in mesh.springs:
        assert sp.k_rot == 0.0                        # ssDNA tether carries no torque
        assert sp.k_trans == pytest.approx(_wlc_k_trans(2))
        assert sp.k_trans < K_PENALTY / 1e3           # orders of magnitude softer than rigid


def test_spring_softens_monotonically_with_insert_length(routed_6hb):
    """More single-stranded bases → a longer, floppier tether → a softer spring; every
    length is far more compliant than the rigid-link penalty."""
    def single_spring_k(seq):
        first_id = routed_6hb.crossovers[0].id
        variant, n, _ = _with_inserts(
            routed_6hb, seq, predicate=lambda i, xo: xo.id == first_id)
        assert n == 1
        springs = build_fem_mesh(variant).springs
        assert len(springs) == 1
        return springs[0].k_trans

    k1, k2, k4 = single_spring_k("T"), single_spring_k("TT"), single_spring_k("TTTT")
    assert k1 > k2 > k4                                # longer insert → softer
    assert k2 == pytest.approx(_wlc_k_trans(2))
    assert k1 == pytest.approx(2.0 * k2)              # k ∝ 1/L_c
    assert k4 < K_PENALTY / 1e4                        # even the stiffest insert is compliant


# ── FAST: a compliant connector deflects more under the same load ────────────

def _two_node_connector_mesh(link):
    """Minimal mesh: two axis nodes one interhelix-offset apart, joined ONLY by ``link``
    (a rigid link or a spring).  No beams — isolates the connector's compliance."""
    a = FEMNode(helix_id="a", global_bp=0, position=np.array([0.0, 0.0, 0.0]))
    b = FEMNode(helix_id="b", global_bp=0, position=np.array([2.25, 0.0, 0.0]))
    mesh = FEMMesh(nodes=[a, b])
    if isinstance(link, FEMRigidLink):
        mesh.rigid_links.append(link)
    else:
        mesh.springs.append(link)
    return mesh


def _node_b_transverse_deflection(mesh, force=1.0):
    """Clamp node A fully + node B's 3 rotational DOF, push node B along +x, and return
    B's along-x translation.  (Pinning B's rotations keeps the soft translational-only
    spring case non-singular; the translational compliance is what we compare.)"""
    K, f = assemble_global_stiffness(mesh)
    f[6] = force                                       # +x force on node B translation
    free = np.array([6, 7, 8], dtype=int)              # node B translational DOF only
    K_free = K.tocsr()[free, :][:, free]
    u = spsolve(K_free, f[free])
    return float(u[0])


def test_compliant_crossover_deflects_far_more_under_load():
    """Under the SAME transverse load, an extra-base (WLC spring) crossover lets its node
    move orders of magnitude more than a rigid crossover — the connector really is soft."""
    offset = np.array([2.25, 0.0, 0.0])
    rigid = _two_node_connector_mesh(FEMRigidLink(node_i=0, node_j=1, offset=offset))
    spring = _two_node_connector_mesh(
        FEMSpring(node_i=0, node_j=1, k_trans=_wlc_k_trans(2), k_rot=0.0))

    u_rigid = _node_b_transverse_deflection(rigid)
    u_spring = _node_b_transverse_deflection(spring)

    assert u_spring > u_rigid * 1e3                    # spring vastly more compliant
    assert u_spring == pytest.approx(1.0 / _wlc_k_trans(2), rel=1e-6)  # F/k_trans
    assert u_rigid == pytest.approx(1.0 / K_PENALTY, rel=1e-6)         # F/K_PENALTY


# ── SLOW: inserts raise local flexibility (RMSF) in the real predict_shape ────

def test_extra_bases_raise_local_flexibility_rmsf(routed_6hb):
    """The comparable prediction: a band of extra-base crossovers softens the structure so
    the CanDo FEM predicts measurably higher LOCAL flexibility (per-bp NMA RMSF) at exactly
    those crossover nodes than the insert-free design — surfaced through the shared S3
    ``compare_descriptors`` RMSF channel (CanDo's reference observable).  Every affected
    node gets more flexible; the sign is unambiguous (softer connector → more fluctuation).
    """
    # Inserts on a contiguous MIDDLE-third band of crossovers: enough to soften locally,
    # far short of the every-crossover regime that unphysically disintegrates the bundle.
    xbps = sorted({xo.half_a.index for xo in routed_6hb.crossovers})
    lo, hi = xbps[len(xbps) // 3], xbps[2 * len(xbps) // 3]
    variant, n_ins, affected = _with_inserts(
        routed_6hb, "TT", predicate=lambda i, xo: lo <= xo.half_a.index <= hi)
    assert n_ins >= 4                                  # a real band, not a single junction

    base = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True)
    ins = predict_shape(variant, nonlinear=False, with_rmsf=True)

    def rmsf_by_bp(pred):
        return {(x["helix_id"], x["bp_index"]): x["rmsf_nm"] for x in pred["rmsf"]}

    r0, r1 = rmsf_by_bp(base), rmsf_by_bp(ins)
    shared = [k for k in affected if k in r0 and k in r1]
    assert len(shared) >= 4

    # Every inserted-crossover node became more flexible, and the local mean rose clearly.
    assert all(r1[k] > r0[k] for k in shared)
    local0 = float(np.mean([r0[k] for k in shared]))
    local1 = float(np.mean([r1[k] for k in shared]))
    assert local1 > local0 * 1.3                       # ≳1.87× observed; margin for jitter

    # RED-guard: a NO-insert control run against itself shows no such softening.
    base2 = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True)
    r0b = rmsf_by_bp(base2)
    ctrl0 = float(np.mean([r0[k] for k in shared]))
    ctrl1 = float(np.mean([r0b[k] for k in shared]))
    assert ctrl1 < ctrl0 * 1.05                        # self-vs-self is flat (NMA jitter only)

    # Same softening seen through the shared cross-engine S3 machinery (RMSF is comparable
    # per-bp across engines): the insert bundle's mean RMSF exceeds the insert-free one's.
    def bundle(pred):
        core = pred["positions"]
        return {"engine": "cando",
                "descriptors": compute_shape_descriptors(core),
                "rmsf": pred["rmsf"],
                "shape_frame": core}

    cmp = compare_descriptors(bundle(ins), bundle(base))
    assert cmp["rmsf"] is not None
    assert (cmp["rmsf"]["candidate_mean_rmsf_nm"]
            > cmp["rmsf"]["reference_mean_rmsf_nm"] * 1.1)
