"""Oracle for C4 — CanDo FEM linkers / overhang connections as connector elements.

An :class:`~backend.core.models.OverhangConnection` (a linker) is a real
topological edit: ``connect_overhangs`` materializes the linker complement
strand(s) so each overhang HYBRIDIZES to the linker's reverse-complementary
binding domain — the linked overhang becomes **duplex** — plus a virtual
``__lnk__`` bridge helix (duplex for a ds linker, single-stranded for a ss
linker).  The FEM only READS this generated topology (Three-Layer Law); no
``Design`` mutation happens in the solver.

Before C4 the FEM's duplex detector counted only *scaffold ∧ staple* bp, so a
linked overhang (*staple ∧ linker*) and the ``__lnk__`` bridge (*linker ∧
linker*) were invisible — a linker contributed **nothing** to the mesh.  C4
makes two additive changes to ``build_fem_mesh``:

  1. **Duplex detection** unions in linker-formed duplex — a bp covered by both a
     FORWARD and a REVERSE strand *when a linker strand covers it*.  On a design
     with NO linker strands this term is empty, so the duplex set is byte-for-byte
     identical (zero exp36-calibration regression — asserted below).
  2. **Load-path closure at linker helix-hops.**  A linker strand crosses helices
     at its inter-domain junctions (these are NOT ``Design.crossovers``).  Two
     meshed duplex domains that are directly adjacent across a hop couple with a
     **rigid link** (a ds bridge — stiff duplex); two meshed duplex domains
     flanking an UNMESHED ssDNA run couple with a **WLC spring** (a ss linker —
     compliant tether, contour = the ss run length).

The bright line (C4 oracle): **two parts joined by a linker show a COUPLED
response under a load on one part (the other moves); with no linker they are
DECOUPLED.**  Proven both synthetically (a minimal two-part mesh) and on the real
generated topology (mesh census: a ds linker adds a bridge + two rigid hops; a ss
linker adds one compliant WLC hop).
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse.linalg import spsolve

from backend.core.models import LatticeType, StrandType
from backend.physics.fem_solver import (
    KBT,
    K_PENALTY,
    L_P_SS,
    RISE_SS,
    EA_DS,
    FEMElement,
    FEMMesh,
    FEMNode,
    FEMRigidLink,
    FEMSpring,
    _duplex_bp_per_helix,
    assemble_global_stiffness,
    build_fem_mesh,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _oh_helices(design, oh_ids) -> set:
    """The helix ids carrying the overhang domains of ``oh_ids``."""
    return {dm.helix_id for s in design.strands for dm in s.domains
            if dm.overhang_id in oh_ids}


def _connector_helix_pairs(mesh) -> set:
    """The unordered helix-pairs joined by a rigid link or a spring — the mesh's
    inter-helix connector census (used to prove the linker wires the right parts)."""
    pairs = set()
    for c in [*mesh.rigid_links, *mesh.springs]:
        hi, hj = mesh.nodes[c.node_i].helix_id, mesh.nodes[c.node_j].helix_id
        if hi != hj:
            pairs.add(frozenset({hi, hj}))
    return pairs


def _linked_bundle(linker_type: str, length_value: float, a_attach: str, b_attach: str):
    """A REAL routed 6HB with two extruded overhangs (well-formed 5'→3' domains,
    unlike the hand-built leaf seed) tied by a linker, plus the same bundle with NO
    connection (the decoupled control).  Returns
    (linked, bare, {overhang ids}, {overhang-helix ids})."""
    from backend.api import headless_build as hb
    from tests.test_headless_build import _place_two_overhangs_on_6hb

    with hb.scratch_session(LatticeType.HONEYCOMB):
        bare, (a_id, b_id) = _place_two_overhangs_on_6hb()
        bare = bare.model_copy(deep=True)
        d = hb.connect_overhangs(
            a_id, b_id, overhang_a_attach=a_attach, overhang_b_attach=b_attach,
            linker_type=linker_type, length_value=length_value, length_unit="bp",
        )
        d = d.model_copy(deep=True)
        return d, bare, {a_id, b_id}, _oh_helices(d, {a_id, b_id})


def _wlc_k_trans(n_bases: int) -> float:
    L_c = n_bases * RISE_SS
    return 3.0 * KBT / (2.0 * L_c * L_P_SS)


# ── FAST: duplex detection is additive (zero regression on linker-free designs) ─

def test_duplex_detection_unchanged_without_linkers():
    """The new linker-duplex term is a UNION that is empty when no linker strand
    exists — a routed bundle with no connections meshes byte-for-byte as before
    (the exp36 calibration cannot shift)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    assert not any(s.strand_type == StrandType.LINKER for s in design.strands)
    dbp = _duplex_bp_per_helix(design)
    # Recompute the LEGACY scaffold∧staple set directly and require identity.
    from backend.core.sequences import domain_bp_range
    scaf = {h.id: set() for h in design.helices}
    stap = {h.id: set() for h in design.helices}
    for s in design.strands:
        if s.is_reference:
            continue
        tgt = scaf if s.strand_type == StrandType.SCAFFOLD else stap
        for dm in s.domains:
            if dm.helix_id in tgt:
                tgt[dm.helix_id].update(domain_bp_range(dm))
    legacy = {hid: scaf[hid] & stap[hid] for hid in scaf}
    assert dbp == legacy


# ── SLOW: a ds linker meshes a duplex bridge + rigid hops (real routed bundle) ─

def test_ds_linker_meshes_duplex_bridge_and_rigid_hops():
    """On a real routed 6HB, a ds linker hybridizes both overhangs (staple∧linker)
    AND builds a duplex ``__lnk__`` bridge (linker∧linker) — all three gain duplex bp
    they lacked before linking — and the mesh gains the bridge's beam nodes plus
    inter-part RIGID hops (a stiff duplex bridge), never a compliant spring."""
    linked, bare, _oh_ids, oh_h = _linked_bundle("ds", 6, "free_end", "free_end")
    bridge = next(h.id for h in linked.helices if h.id.startswith("__lnk__"))

    dbp_bare, dbp = _duplex_bp_per_helix(bare), _duplex_bp_per_helix(linked)
    for h in oh_h:
        assert (dbp_bare.get(h) or set()) == set()   # ss overhang before linking
        assert len(dbp[h]) > 0                        # duplex after linking
    assert len(dbp[bridge]) > 0                        # ds bridge is duplex

    m_bare, m = build_fem_mesh(bare), build_fem_mesh(linked)
    meshed = {n.helix_id for n in m.nodes}
    assert oh_h <= meshed and bridge in meshed         # overhangs + bridge now meshed
    assert bridge not in {n.helix_id for n in m_bare.nodes}
    # A ds linker couples rigidly (bridge + hops), never compliantly.
    assert len(m.rigid_links) > len(m_bare.rigid_links)
    assert len(m.springs) == len(m_bare.springs) == 0
    # The load path genuinely closes: the bridge is rigidly linked to BOTH overhang
    # helices (A↔bridge and bridge↔B), so the two parts are one stiff component —
    # not merely "more rigid links appeared somewhere".
    pairs = _connector_helix_pairs(m)
    for h in oh_h:
        assert frozenset({h, bridge}) in pairs


def test_ss_linker_meshes_one_compliant_wlc_hop():
    """On a real routed 6HB, a ss linker hybridizes both overhangs (duplex) but its
    ``__lnk__`` bridge stays single-stranded (NOT meshed); the two overhang duplexes
    are coupled by exactly ONE new compliant WLC spring (k_rot == 0, WLC low-force
    stiffness, orders of magnitude softer than a rigid link) spanning the ssDNA run."""
    linked, bare, _oh_ids, oh_h = _linked_bundle("ss", 6, "root", "free_end")
    bridge = next(h.id for h in linked.helices if h.id.startswith("__lnk__"))

    dbp = _duplex_bp_per_helix(linked)
    for h in oh_h:
        assert len(dbp[h]) > 0                          # overhangs duplex
    assert (dbp.get(bridge) or set()) == set()          # ss bridge unmeshed

    m_bare, m = build_fem_mesh(bare), build_fem_mesh(linked)
    assert bridge not in {n.helix_id for n in m.nodes}  # ss bridge not meshed
    assert len(m.springs) == len(m_bare.springs) + 1    # exactly one new compliant hop
    sp = m.springs[-1]
    assert sp.k_rot == 0.0
    assert sp.k_trans < K_PENALTY / 1e3
    # The spring bridges the two DISTINCT overhang helices (a real inter-part tether).
    hi, hj = m.nodes[sp.node_i].helix_id, m.nodes[sp.node_j].helix_id
    assert hi != hj and {hi, hj} <= oh_h
    assert sp.k_trans == pytest.approx(_wlc_k_trans(6), rel=0.2)  # ~6-base ss run


# ── FAST: the bright line — coupling with a linker, decoupled without ─────────

def _two_parts(link):
    """Two disjoint 2-node 'parts' (a beam each). Part A = nodes 0-1 along +z at
    x=0; part B = nodes 2-3 along +z at x=3.  ``link`` (a spring or rigid link
    between node 1 and node 2) is the ONLY thing that can join them; None = no
    linker (decoupled)."""
    z = np.array([0.0, 0.0, 1.0])
    nodes = [
        FEMNode(helix_id="A", global_bp=0, position=np.array([0.0, 0.0, 0.0])),
        FEMNode(helix_id="A", global_bp=1, position=z.copy()),
        FEMNode(helix_id="B", global_bp=0, position=np.array([3.0, 0.0, 0.0])),
        FEMNode(helix_id="B", global_bp=1, position=np.array([3.0, 0.0, 1.0])),
    ]
    R = np.eye(3)
    mesh = FEMMesh(nodes=nodes)
    mesh.elements.append(FEMElement(node_i=0, node_j=1, length=1.0, R=R.copy(), ea=EA_DS))
    mesh.elements.append(FEMElement(node_i=2, node_j=3, length=1.0, R=R.copy(), ea=EA_DS))
    if isinstance(link, FEMSpring):
        mesh.springs.append(link)
    elif isinstance(link, FEMRigidLink):
        mesh.rigid_links.append(link)
    return mesh


def _part_b_moves(mesh, force=1.0):
    """Clamp part A fully (nodes 0,1), push node 1 toward part B (+x), and return
    the magnitude of part B's node-2 translation.  With NO connector part B is a
    free rigid body (singular) → we instead pin part B's rotations only and read
    whether node 2 translates: a linker transmits the load, no linker leaves it 0."""
    K, f = assemble_global_stiffness(mesh)
    f[6] = force                                       # +x on node 1 (part A's free tip)
    # Free DOF: node 1 translation (0..2 already clamped? no) — clamp node 0 fully,
    # node 1 free (translate), node 2 translation free, node 3 fully clamped.
    free = np.array([6, 7, 8, 12, 13, 14], dtype=int)
    K_free = K.tocsr()[free, :][:, free]
    u = spsolve(K_free, f[free])
    return float(np.linalg.norm(u[3:6]))               # node 2 (part B) translation


def test_linker_couples_two_parts_and_absence_decouples():
    """THE bright line: a WLC-spring linker between the two parts transmits a load
    from part A into part B (node 2 moves); removing the linker decouples them
    (node 2 stays exactly put)."""
    spring = FEMSpring(node_i=1, node_j=2, k_trans=_wlc_k_trans(6), k_rot=0.0)
    coupled = _part_b_moves(_two_parts(spring))
    decoupled = _part_b_moves(_two_parts(None))

    assert decoupled == pytest.approx(0.0, abs=1e-12)   # no linker → part B untouched
    assert coupled > 1e-9                                # linker → part B moves
    assert coupled > decoupled + 1e-9


def test_rigid_linker_couples_more_stiffly_than_a_soft_one():
    """A ds (rigid-link) linker enforces the SAME motion between the joined nodes;
    a ss (soft WLC) linker lets them separate.  Under the same clamp, the rigidly
    linked part B tracks part A's tip far more closely than the compliant one."""
    offset = np.array([3.0, 0.0, 0.0])
    rigid = _two_parts(FEMRigidLink(node_i=1, node_j=2, offset=offset))
    soft = _two_parts(FEMSpring(node_i=1, node_j=2, k_trans=_wlc_k_trans(6), k_rot=0.0))
    # Both couple (part B moves); the rigid one transmits the load into part B far
    # more than the compliant WLC tether (which lets the two nodes separate).
    u_rigid, u_soft = _part_b_moves(rigid), _part_b_moves(soft)
    assert u_rigid > 1e-9 and u_soft > 1e-9
    assert u_rigid > u_soft * 10                        # ds bridge ≫ ss tether coupling
