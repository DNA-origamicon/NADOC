"""
CanDo-style Finite Element Method (FEM) solver for DNA origami.

Models each helix as a sequence of Euler-Bernoulli beam elements.  Crossovers
are either rigid penalty springs (standard DX crossovers) or compliant WLC
springs (crossovers with extra ssDNA bases — NADOC extension over CanDo).

Reference parameters from Castro et al., Nature Methods 8, 221-229 (2011):
  EA  = 1100 pN      stretch stiffness
  EI  = 230  pN·nm²  bending stiffness (isotropic)
  GJ  = 460  pN·nm²  torsional stiffness

ssDNA WLC spring constant (Marko & Siggia 1995):
  k_ss = 3 k_BT / (2 L_c L_p)   (low-force regime, translational spring only)
  L_p  = 1.5 nm, L_c = n_bases × 0.63 nm/base, k_BT = 4.11 pN·nm @ 310 K

Architecture notes
──────────────────
- FEM nodes sit on the helix axis, one per active bp.
- Node DOF ordering: [u_x, u_y, u_z, θ_x, θ_y, θ_z] (translations then rotations).
  The beam axis is the LOCAL z direction.
- Global stiffness K is assembled as a scipy lil_matrix (n_dof × n_dof) then
  converted to csr for solving.
- Boundary condition: pin all 6 DOF at node 0 of the first helix to remove
  the 6 rigid-body modes.
- Crossovers couple connected axis nodes as stiff rigid links (u_B = u_A + θ_A×r_AB).
- Pre-stress (assemble_prestress_force): loop/skip eigenstrain + the square-lattice
  register over-twist (SQ helices are intrinsically over-wound vs their natural helicity,
  so they carry a global twist even with no loop/skips — see assemble_prestress_force).
  Honeycomb without loop/skips relaxes to u ≈ 0.
- RMSF is computed from the 30 lowest eigenmodes of the free-DOF stiffness
  matrix: RMSF_i = sqrt(k_BT × Σ_m φ²_m,i / λ_m)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import eigsh, spsolve

from backend.core.constants import BDNA_TWIST_PER_BP_RAD, SQUARE_TWIST_PER_BP_RAD
from backend.core.geometry import _frame_from_helix_axis
from backend.core.models import Design, Direction, LatticeType, StrandType
from backend.core.sequences import domain_bp_range


# ── Duplex-core bp extraction ─────────────────────────────────────────────────

def _duplex_bp_per_helix(design: Design) -> Dict[str, set]:
    """Per helix, the bp indices covered by BOTH a scaffold and a staple strand.

    This is the duplex core — the region that behaves as double-stranded DNA. It
    excludes ssDNA overhangs, the auto_scaffold cap extension past the staples, and
    any single-stranded scaffold, matching CanDo's "nodes = base pairs" convention.
    """
    scaf: Dict[str, set] = {h.id: set() for h in design.helices}
    stap: Dict[str, set] = {h.id: set() for h in design.helices}
    for s in design.strands:
        if s.is_reference:
            continue
        target = scaf if s.strand_type == StrandType.SCAFFOLD else stap
        for dm in s.domains:
            if dm.helix_id in target:
                target[dm.helix_id].update(domain_bp_range(dm))
    return {hid: scaf[hid] & stap[hid] for hid in scaf}


def _nick_bps_per_helix(design: Design) -> Dict[str, set]:
    """Per helix, the bp indices at a strand 5'/3' terminus (a nick).

    A nick is a break in one of the two duplex backbones; CanDo softens the local
    bending + torsional stiffness there by NICK_FACTOR (0.01). We take every strand's
    first-domain 5' bp and last-domain 3' bp on their respective helices.
    """
    nicks: Dict[str, set] = {h.id: set() for h in design.helices}
    for s in design.strands:
        if s.is_reference or not s.domains:
            continue
        d5, d3 = s.domains[0], s.domains[-1]
        if d5.helix_id in nicks:
            nicks[d5.helix_id].add(d5.start_bp)
        if d3.helix_id in nicks:
            nicks[d3.helix_id].add(d3.end_bp)
    return nicks

# ── CanDo default geometry + mechanics (cando-dna-origami.org defaults) ────────
# These are the exact CanDo submission defaults so the FEM matches the reference solver.
FEM_RISE_PER_BP = 0.34    # nm — axial rise per bp (CanDo; NADOC's BDNA_RISE_PER_BP=0.334)
HELIX_DIAMETER  = 2.25    # nm — helix diameter (cross-section geometry from NADOC axes)
BP_PER_TURN     = 10.5    # bp — crossover spacing / helicity

# Square-lattice REGISTER over-twist (emergent global twist that exists with ZERO loop/skips).
# The square-lattice crossover geometry demands ~10.67 bp/turn (SQUARE_TWIST_PER_BP = 33.75°/bp)
# while the duplex's natural helicity is ~10.5 bp/turn (BDNA = 34.3°/bp). That per-bp mismatch is
# a rest-twist eigenstrain the crossovers cannot relax → a global bundle twist, which CanDo
# reproduces (e.g. 3x6x400 unskipped ≈ +64°) and which deletions are placed to relieve. Honeycomb
# has natural == lattice helicity, so this term is exactly zero there (battery untouched). Lattice-
# INVARIANT physics: the twist is emergent from the crossover register, not a per-lattice constant.
_SQ_REGISTER_TWIST_PER_BP_RAD = BDNA_TWIST_PER_BP_RAD - SQUARE_TWIST_PER_BP_RAD   # ≈ +0.55°/bp
# Fraction of one bp of natural twist that a single deletion relieves from the register over-twist.
# The exact per-skip register recipe is not published (the least-documented CanDo step); this is
# calibrated to the CanDo web solver on 3x6x400 (unskipped +64° → 150-skip +24.8°) and cross-checked
# for direction/magnitude on 2x3x100. Exposed as a constant so it can be refined against more data.
SQ_SKIP_RELIEF_FACTOR = 0.5

EA_DS   = 1100.0   # pN — dsDNA axial stretch stiffness
EI_DS   = 230.0    # pN·nm² — dsDNA bending stiffness (isotropic)
GJ_DS   = 460.0    # pN·nm² — dsDNA torsional stiffness
NICK_FACTOR = 0.01 # nicked backbone: bending + torsional stiffness ×0.01, axial retained
L_P_SS  = 1.5      # nm — ssDNA persistence length
RISE_SS = 0.63     # nm — ssDNA rise per base (single-stranded)
KBT     = 4.11     # pN·nm — thermal energy at ~298 K (CanDo RMSF reference temperature)

K_PENALTY = 1.0e6  # pN/nm — effective spring constant for "rigid" crossovers
# E-field body load: the shared field descriptor stores force-per-NUCLEOTIDE in pN
# (the cross-engine-comparable value; oxDNA applies exactly this per bead — see
# oxdna_interface.OXDNA_FORCE_PN + project_oxdna_efield). A duplex FEM axis node
# carries BOTH strands of one bp = two charged backbones, so its nodal load is
# 2 × force_per_nt along the field direction (same convention, doubled per node).
FEM_FIELD_CHARGES_PER_NODE = 2
N_RMSF_MODES = 200 # lowest eigenmodes for RMSF (CanDo uses 200 modes + equipartition @ 298 K)
_MIN_FEM_NODES = 2 # a beam FEM needs ≥1 element (2 nodes); fewer duplex bp → nothing to solve

# Crossover = rigid zero-length link (CanDo). Modeled as a stiff beam spanning the
# inter-helix offset: it couples the two duplex nodes with the correct rigid-link geometry
# (u_B = u_A + θ_A × r_AB), so the bundle bends as a composite AND the axial differential
# that creates the bend is preserved — unlike a zero-relative-displacement spring, which
# over-constrains the axial DOF and suppresses the bend.
XOVER_STIFF_SCALE = 100.0  # crossover-link stiffness relative to DNA (≈10× stiffer coupling)


# ── Mesh data structures ───────────────────────────────────────────────────────

@dataclass
class FEMNode:
    """One node on the helix axis; 6 DOF."""
    helix_id: str
    global_bp: int          # global bp index (matches NucleotidePosition.bp_index)
    position: np.ndarray    # 3D axis position, nm


@dataclass
class FEMElement:
    """Two-node beam element. Used both for the DNA duplex (default DNA stiffness) and
    for crossover rigid links (stiff, spanning the inter-helix offset)."""
    node_i: int             # index into FEMMesh.nodes
    node_j: int             # index into FEMMesh.nodes (j = i+1 along helix for DNA)
    length: float           # nm
    R: np.ndarray           # 3×3 rotation: columns = [x̂, ŷ, ẑ_local] in global frame
    ea: float = EA_DS       # per-element stiffness (crossover links override with rigid values)
    ei: float = EI_DS
    gj: float = GJ_DS


@dataclass
class FEMSpring:
    """
    Spring constraint between two nodes (crossover junction).

    Enforces zero *relative* displacement: both nodes must move by the same
    amount.  k_rot = 0 for ssDNA linkers (translational spring only).
    No pre-stress force is stored here; the spring contributes only to K.
    """
    node_i: int
    node_j: int
    k_trans: float
    k_rot: float


@dataclass
class FEMRigidLink:
    """Crossover as a RIGID zero-length link (CanDo). Enforces exact rigid-body
    kinematics between the two duplex nodes: u_j = u_i + θ_i × r_ij and θ_j = θ_i,
    where r_ij is the inter-helix offset. Applied as a penalty on the constraint
    residual C·d = 0 — unlike a stiff beam it has NO residual compliance, so the bundle
    bends as a true composite and the twist damping is not defeated by soft (nicked) helices."""
    node_i: int
    node_j: int
    offset: np.ndarray      # r_ij = pos_j − pos_i (nm)


@dataclass
class FEMMesh:
    nodes:    List[FEMNode]    = field(default_factory=list)
    elements: List[FEMElement] = field(default_factory=list)
    springs:  List[FEMSpring]  = field(default_factory=list)
    rigid_links: List[FEMRigidLink] = field(default_factory=list)


# ── Mesh builder ──────────────────────────────────────────────────────────────

def build_fem_mesh(design: Design) -> FEMMesh:
    """
    Build an FEMMesh from a NADOC Design.

    One FEMNode is placed at each active bp position along every helix axis.
    Beam elements connect consecutive nodes within a helix.
    Crossover springs connect the matched bp positions at each crossover.
    Crossovers with extra_bases get WLC ssDNA springs; standard crossovers
    get rigid penalty springs.

    Crossover indices that fall just outside a helix's bp range (e.g. scaffold
    routing junctions) are clamped to the nearest helix endpoint so they
    still contribute mechanical coupling between adjacent helix ends.
    """
    mesh = FEMMesh()
    # Map (helix_id, global_bp) → node index for crossover wiring.
    node_map: Dict[Tuple[str, int], int] = {}
    # Per-helix bp range for clamping out-of-range crossover indices.
    helix_bp_range: Dict[str, Tuple[int, int]] = {}

    # Duplex-core bp per helix: positions covered by BOTH a scaffold and a staple.
    # Meshing the full axis (round(len/rise)) over-counts — auto_scaffold extends the
    # helix ~21 bp past the staples at the caps, and those crossover-free cantilever
    # tails produce huge (unphysical) RMSF. CanDo nodes = base pairs (duplex), so we
    # restrict FEM nodes to the duplex core.
    duplex_bp = _duplex_bp_per_helix(design)
    nick_bp = _nick_bps_per_helix(design)   # strand 5'/3' termini → softened beams

    # ── Nodes & beam elements ──────────────────────────────────────────────────
    for helix in design.helices:
        start   = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
        end     = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
        axis_v  = end - start
        length  = float(np.linalg.norm(axis_v))
        if length < 1e-9:
            continue
        axis_hat = axis_v / length
        R = _frame_from_helix_axis(axis_hat)   # cols = [x̂, ŷ, ẑ=axis_hat]

        bps = sorted(duplex_bp.get(helix.id, ()))
        if len(bps) < 2:
            continue
        helix_bp_range[helix.id] = (bps[0], bps[-1])

        first_node_idx = len(mesh.nodes)
        for global_bp in bps:
            pos = start + axis_hat * ((global_bp - helix.bp_start) * FEM_RISE_PER_BP)
            idx = len(mesh.nodes)
            mesh.nodes.append(FEMNode(helix_id=helix.id, global_bp=global_bp, position=pos.copy()))
            node_map[(helix.id, global_bp)] = idx

        # Beam elements between consecutive duplex nodes (length scales with the bp gap).
        # A beam spanning a nick (strand terminus in either backbone) gets bending +
        # torsional stiffness ×NICK_FACTOR (axial retained) — CanDo's nick model.
        nicks = nick_bp.get(helix.id, set())
        for k in range(len(bps) - 1):
            gap = bps[k + 1] - bps[k]
            nicked = bps[k] in nicks or bps[k + 1] in nicks
            mesh.elements.append(FEMElement(
                node_i=first_node_idx + k,
                node_j=first_node_idx + k + 1,
                length=gap * FEM_RISE_PER_BP,
                R=R.copy(),
                ei=EI_DS * (NICK_FACTOR if nicked else 1.0),
                gj=GJ_DS * (NICK_FACTOR if nicked else 1.0),
            ))

    # ── Crossover springs ─────────────────────────────────────────────────────
    def _resolve_node(helix_id: str, bp_idx: int) -> Optional[int]:
        """
        Look up node index for (helix_id, bp_idx).  If bp_idx is outside the
        helix range (scaffold routing junctions can sit a few bp beyond the
        terminus), clamp to the nearest endpoint node so the structural
        coupling is preserved.
        """
        if (helix_id, bp_idx) in node_map:
            return node_map[(helix_id, bp_idx)]
        if helix_id not in helix_bp_range:
            return None
        bp_lo, bp_hi = helix_bp_range[helix_id]
        clamped = max(bp_lo, min(bp_hi, bp_idx))
        return node_map.get((helix_id, clamped))

    for xo in design.crossovers:
        ni = _resolve_node(xo.half_a.helix_id, xo.half_a.index)
        nj = _resolve_node(xo.half_b.helix_id, xo.half_b.index)
        if ni is None or nj is None:
            continue
        if ni == nj:
            continue  # degenerate spring (same node after clamping)

        n_extra = len(xo.extra_bases) if xo.extra_bases else 0
        if n_extra > 0:
            # ssDNA WLC spring — translational only, no rotational stiffness.
            L_c     = n_extra * RISE_SS
            k_trans = 3.0 * KBT / (2.0 * L_c * L_P_SS)
            mesh.springs.append(FEMSpring(node_i=ni, node_j=nj, k_trans=k_trans, k_rot=0.0))
            continue

        # Standard DX crossover — rigid zero-length link (exact constraint, no compliance).
        offset = mesh.nodes[nj].position - mesh.nodes[ni].position
        mesh.rigid_links.append(FEMRigidLink(node_i=ni, node_j=nj, offset=offset))

    return mesh


# ── Element stiffness matrices ────────────────────────────────────────────────

def _beam_stiffness_local(L: float, EA: float = EA_DS, EI: float = EI_DS,
                          GJ: float = GJ_DS) -> np.ndarray:
    """
    12×12 Euler-Bernoulli beam stiffness matrix in LOCAL frame.

    DOF ordering: [u1, v1, w1, θx1, θy1, θz1,  u2, v2, w2, θx2, θy2, θz2]
    Local beam axis = z direction.
    u = x-displacement, v = y-displacement, w = axial (z), θ_z = torsion.
    ``EA/EI/GJ`` default to dsDNA; crossover links pass rigid (scaled) values.
    """
    K = np.zeros((12, 12), dtype=float)

    ea  = EA / L
    gj  = GJ / L
    # Bending in x-z plane (EI_y), couples u and θ_y (indices 0,4,6,10).
    ei  = EI
    c1  = 12.0 * ei / L**3
    c2  =  6.0 * ei / L**2
    c3  =  4.0 * ei / L
    c4  =  2.0 * ei / L

    # Axial: w1(2), w2(8)
    K[2, 2] =  ea;  K[2, 8] = -ea
    K[8, 2] = -ea;  K[8, 8] =  ea

    # Torsion: θz1(5), θz2(11)
    K[5, 5]  =  gj;  K[5, 11]  = -gj
    K[11, 5] = -gj;  K[11, 11] =  gj

    # Bending in x-z plane: u1(0), θy1(4), u2(6), θy2(10)
    K[0, 0]  =  c1;  K[0, 4]  =  c2;  K[0, 6]  = -c1;  K[0, 10]  =  c2
    K[4, 0]  =  c2;  K[4, 4]  =  c3;  K[4, 6]  = -c2;  K[4, 10]  =  c4
    K[6, 0]  = -c1;  K[6, 4]  = -c2;  K[6, 6]  =  c1;  K[6, 10]  = -c2
    K[10, 0] =  c2;  K[10, 4] =  c4;  K[10, 6] = -c2;  K[10, 10] =  c3

    # Bending in y-z plane: v1(1), θx1(3), v2(7), θx2(9)
    # Sign convention: positive v couples with negative θx at near end.
    K[1, 1] =  c1;  K[1, 3]  = -c2;  K[1, 7]  = -c1;  K[1, 9]  = -c2
    K[3, 1] = -c2;  K[3, 3]  =  c3;  K[3, 7]  =  c2;  K[3, 9]  =  c4
    K[7, 1] = -c1;  K[7, 3]  =  c2;  K[7, 7]  =  c1;  K[7, 9]  =  c2
    K[9, 1] = -c2;  K[9, 3]  =  c4;  K[9, 7]  =  c2;  K[9, 9]  =  c3

    return K


def _transform_to_global(K_local: np.ndarray, R: np.ndarray) -> np.ndarray:
    """
    Transform a 12×12 element stiffness matrix from local to global coordinates.

    R (3×3): columns are the local frame axes expressed in the global frame
             (output of _frame_from_helix_axis).
    T_3 = R.T maps a global vector to local frame, so:
        d_local = T_3 @ d_global  →  K_global = T12.T @ K_local @ T12
    where T12 = block_diag(R.T, R.T, R.T, R.T).
    """
    T12 = np.zeros((12, 12), dtype=float)
    RT = R.T
    for b in range(4):
        T12[3*b:3*b+3, 3*b:3*b+3] = RT
    return T12.T @ K_local @ T12


# ── Global stiffness assembly ──────────────────────────────────────────────────

def assemble_global_stiffness(
    mesh: FEMMesh,
) -> Tuple[lil_matrix, np.ndarray]:
    """
    Assemble global stiffness matrix K.

    Returns (K, f) as (lil_matrix, ndarray).  K has shape (n_dof, n_dof)
    where n_dof = 6 × len(mesh.nodes).  f is always zero — no pre-stress
    forces are applied.  Crossover springs contribute only to K (they enforce
    zero relative displacement, not collapse to zero absolute distance).
    """
    n = len(mesh.nodes)
    n_dof = 6 * n
    K = lil_matrix((n_dof, n_dof), dtype=float)
    f = np.zeros(n_dof, dtype=float)

    # ── Beam elements ─────────────────────────────────────────────────────────
    # Elements may have variable length (bp gaps) and stiffness (DNA vs crossover link).
    _kloc_cache: Dict[Tuple[float, float, float, float], np.ndarray] = {}
    for el in mesh.elements:
        L = el.length if el.length > 1e-9 else FEM_RISE_PER_BP
        key = (L, el.ea, el.ei, el.gj)
        K_local = _kloc_cache.get(key)
        if K_local is None:
            K_local = _beam_stiffness_local(L, el.ea, el.ei, el.gj)
            _kloc_cache[key] = K_local
        K_g = _transform_to_global(K_local, el.R)
        di = 6 * el.node_i
        dj = 6 * el.node_j
        # Assemble 4 quadrants of the 12×12 global element matrix.
        K[di:di+6, di:di+6] += K_g[0:6,  0:6]
        K[di:di+6, dj:dj+6] += K_g[0:6,  6:12]
        K[dj:dj+6, di:di+6] += K_g[6:12, 0:6]
        K[dj:dj+6, dj:dj+6] += K_g[6:12, 6:12]

    # ── Crossover springs ─────────────────────────────────────────────────────
    for sp in mesh.springs:
        di = 6 * sp.node_i
        dj = 6 * sp.node_j
        kt = sp.k_trans
        kr = sp.k_rot

        # Translational spring: 3×3 identity × k_trans added to diagonal blocks,
        # subtracted from off-diagonal blocks.
        for dim in range(3):
            K[di+dim, di+dim] += kt
            K[dj+dim, dj+dim] += kt
            K[di+dim, dj+dim] -= kt
            K[dj+dim, di+dim] -= kt

        # Rotational spring (zero for ssDNA linkers).
        if kr != 0.0:
            for dim in range(3):
                K[di+3+dim, di+3+dim] += kr
                K[dj+3+dim, dj+3+dim] += kr
                K[di+3+dim, dj+3+dim] -= kr
                K[dj+3+dim, di+3+dim] -= kr

    # ── Crossover rigid links (penalty on the exact constraint C·d = 0) ─────────
    # d = [u_i, θ_i, u_j, θ_j] (12). Constraint rows:
    #   translational: u_j − u_i + skew(r)·θ_i = 0
    #   rotational:    θ_j − θ_i = 0
    # K += K_PENALTY · Cᵀ C on the (i,j) DOF block.
    for lk in mesh.rigid_links:
        rx, ry, rz = lk.offset
        skew = np.array([[0.0, -rz, ry], [rz, 0.0, -rx], [-ry, rx, 0.0]])
        I3 = np.eye(3)
        C = np.zeros((6, 12))
        C[0:3, 0:3] = -I3          # −u_i
        C[0:3, 3:6] = skew         # +skew(r)·θ_i
        C[0:3, 6:9] = I3           # +u_j
        C[3:6, 3:6] = -I3          # −θ_i
        C[3:6, 9:12] = I3          # +θ_j
        Kc = K_PENALTY * (C.T @ C)
        di, dj = 6 * lk.node_i, 6 * lk.node_j
        idx = list(range(di, di + 6)) + list(range(dj, dj + 6))
        for a in range(12):
            ia = idx[a]
            for b in range(12):
                v = Kc[a, b]
                if v != 0.0:
                    K[ia, idx[b]] += v

    return K, f


# ── Loop/skip pre-stress (eigenstrain → equivalent nodal forces) ─────────────────

# One deletion removes one base pair of helical twist (2π / bp_per_turn) and one rise of
# axial length. CanDo encodes this as a temperature eigenstrain per beam; here we build the
# equivalent nodal force vector for the LINEAR solve (K u = f_prestress).


def assemble_prestress_force(mesh: FEMMesh, design: Design,
                             axial: bool = True, torsion: bool = True) -> np.ndarray:
    """Equivalent nodal-force vector for the loop/skip eigenstrain.

    Per helix, the net loop/skip content imposes a rest-twist offset (a deletion
    OVER-twists: the remaining bases must span the same crossover register → torsional
    pre-stress) and a rest-length offset (a deletion SHORTENS). Both are distributed
    uniformly over the helix's beam elements (weighted by element length) and converted
    to equivalent local nodal loads:

        torsional:  T0 = GJ · φ0 / L   on the two θ_z DOFs (±)
        axial:      N0 = EA · δ0 / L   on the two axial DOFs (±)

    with φ0 = -Σδ · (2π/bp_per_turn)  (skip δ=-1 → +overtwist) and
         δ0 =  Σδ · rise              (skip → shorter rest length),
    then rotated to global via the element frame. Uniform per-helix content → global
    twist; a cross-section gradient → global bend (via the crossover-coupled bundle).

    SQUARE-LATTICE REGISTER OVER-TWIST (2026-07-04): a square-lattice bundle carries an
    intrinsic global twist even with ZERO loop/skips — its crossover geometry demands
    ~10.67 bp/turn while the duplex's natural helicity is ~10.5 bp/turn, and that per-bp
    mismatch (_SQ_REGISTER_TWIST_PER_BP_RAD) is a rest-twist eigenstrain the crossovers
    cannot relax. This is the emergent twist the CanDo web solver reports (3x6x400
    unskipped ≈ +64°) and that deletions are placed to RELIEVE. So for square designs the
    torsional term becomes φ0 = register·N_bp + f·Σδ·(2π/bp_per_turn), where the register
    over-twist is present at Σδ=0 and each deletion (δ=-1) subtracts a fraction
    SQ_SKIP_RELIEF_FACTOR of it (skips straighten the strut; validated vs CanDo — unskipped
    +64° → 150-skip +24.8° on 3x6x400). Honeycomb has natural == lattice helicity → the
    register term is exactly zero, so this branch leaves the honeycomb battery untouched.

    NOTE (bend under-conversion, exp36 2026-07-03): this axial-force eigenstrain converts
    ~0.68 of the programmed bend (CanDo converts ~0.95); ~67% of the eigenstrain energy
    relieves as internal axial stretch. A rest-CURVATURE reformulation (differential →
    composite bending moments) was tried and REJECTED — imposing κ as per-element moments
    leaves only net end-couples after assembly, which a long crossover-coupled bundle does
    not transmit into a uniform curvature (response is topology/length-dependent: 6HB→0.62,
    4HB→0.42, 420bp→0.32 of analytic). The bend gap lives in the discrete STIFFNESS
    response, not the eigenstrain load. See experiments/exp36 bend_diagnostics_results.md.
    """
    n_dof = 6 * len(mesh.nodes)
    f = np.zeros(n_dof, dtype=float)

    net = {h.id: sum(ls.delta for ls in h.loop_skips) for h in design.helices}
    # DNA beams only (both nodes on the same helix); crossover links span two helices
    # and carry no eigenstrain.
    elems_by_helix: Dict[str, List[FEMElement]] = {}
    for el in mesh.elements:
        hi = mesh.nodes[el.node_i].helix_id
        if hi == mesh.nodes[el.node_j].helix_id:
            elems_by_helix.setdefault(hi, []).append(el)

    twist_per_del = 2.0 * math.pi / BP_PER_TURN   # rad of over/under-twist per mark
    is_square = design.lattice_type == LatticeType.SQUARE

    for hid, elems in elems_by_helix.items():
        nd = net.get(hid, 0)
        if not elems:
            continue
        L_helix = sum(e.length for e in elems)
        if L_helix <= 0:
            continue
        if is_square:
            # Square lattice carries an intrinsic REGISTER over-twist even at nd=0 (see
            # _SQ_REGISTER_TWIST_PER_BP_RAD): distribute (natural − lattice) rest-twist over the
            # helix's duplex bp, then let deletions RELIEVE it (nd<0 subtracts a fraction
            # SQ_SKIP_RELIEF_FACTOR of one bp of natural twist per mark). This is the CanDo
            # behaviour: unskipped SQ bundles are globally twisted; skips straighten them.
            n_bp = L_helix / FEM_RISE_PER_BP
            phi0_total = _SQ_REGISTER_TWIST_PER_BP_RAD * n_bp + SQ_SKIP_RELIEF_FACTOR * nd * twist_per_del
        else:
            if nd == 0:
                continue
            phi0_total = -nd * twist_per_del      # honeycomb: deletion → positive over-twist
        dax_total  = nd * FEM_RISE_PER_BP    # net skips (nd<0) → shorter rest length
        if phi0_total == 0.0 and dax_total == 0.0:
            continue

        for el in elems:
            frac = el.length / L_helix
            # Per-element stiffness: a nicked (soft) element applies a proportionally
            # smaller eigenstrain force, so a nick RELAXES the local over-twist rather
            # than over-rotating it — the CanDo torsional-swivel behaviour.
            T0 = el.gj * (phi0_total * frac) / el.length if torsion else 0.0
            N0 = el.ea * (dax_total * frac) / el.length if axial else 0.0
            f_local = np.zeros(12, dtype=float)
            f_local[2], f_local[8]  = -N0, +N0     # axial (local z) at node i, j
            f_local[5], f_local[11] = -T0, +T0     # torsion (θ_z) at node i, j
            for b in range(4):                     # 4 triplets: trans_i, rot_i, trans_j, rot_j
                fg = el.R @ f_local[3 * b:3 * b + 3]
                node = el.node_i if b < 2 else el.node_j
                off = 6 * node + (0 if b % 2 == 0 else 3)
                f[off:off + 3] += fg
    return f


# ── External E-field body load ──────────────────────────────────────────────────

def assemble_field_force(mesh: FEMMesh, field: Optional[dict]) -> np.ndarray:
    """Equivalent nodal-force vector for a uniform electric field (E-field body load).

    A uniform field applies the SAME constant force to every charged backbone bead —
    the tethered-arm regime (Kopperger 2018): with part of the bundle anchored, the free
    region deflects along the force while the anchors absorb the net thrust (see
    ``project_oxdna_efield``; a field run WITHOUT an anchor just streams the whole COM).

    ``field`` mirrors the shared oxDNA descriptor: ``{"field_pN": <force per nucleotide,
    pN>, "dir": [x, y, z]}`` — the same per-nucleotide force oxDNA applies per bead, so the
    two engines are driven by an identical, comparable load. Each duplex axis node carries
    :data:`FEM_FIELD_CHARGES_PER_NODE` (=2) backbones, so its translational load is
    ``2 · field_pN · dir_hat`` (pN); rotational DOF get none (a pure body force, no couple).
    ``None`` / zero magnitude / zero direction → a zero vector (no field, exact no-op).

    Three-Layer Law: the field is a JOB-REQUEST annotation read here only; it never touches
    topology. Unlike the loop/skip eigenstrain (which co-rotates with the elements in the
    corotational solve), this is a DEAD load — fixed in the lab frame as the bundle bends —
    so it is assembled once in global coordinates and NOT reframed per load step.
    """
    n_dof = 6 * len(mesh.nodes)
    f = np.zeros(n_dof, dtype=float)
    if not field:
        return f
    mag_pn = float(field.get("field_pN", 0.0) or 0.0)
    direction = np.asarray(field.get("dir") or (0.0, 0.0, 0.0), dtype=float)
    dnorm = float(np.linalg.norm(direction))
    if mag_pn == 0.0 or dnorm <= 1e-12:
        return f
    force_vec = FEM_FIELD_CHARGES_PER_NODE * mag_pn * (direction / dnorm)   # pN, global
    for node in range(len(mesh.nodes)):
        f[6 * node: 6 * node + 3] += force_vec       # translational DOF only
    return f


# ── Boundary conditions ────────────────────────────────────────────────────────

def apply_boundary_conditions(
    K: lil_matrix,
    f: np.ndarray,
    mesh: FEMMesh,
    fixed_nodes: Optional[List[int]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Pin all 6 DOF of the given ``fixed_nodes`` (Dirichlet BC), or — when none are
    supplied — the single node nearest the geometric centroid.

    ``fixed_nodes`` are anchor node indices (see :func:`resolve_anchor_nodes`): the
    physical tether holds those axis nodes clamped while the rest of the bundle
    deflects under the load. Any anchor set of ≥1 fully-clamped node also removes
    the 6 rigid-body modes, so it doubles as the constraint the solve needs.

    With NO anchors the legacy centroid pin is used: pinning the centroid node
    (rather than node 0) avoids a pure cantilever effect where RMSF increases
    monotonically from one end. The resulting RMSF is symmetric around the centre
    and reflects actual crossover-driven stiffness variation rather than distance
    from an arbitrary boundary. An empty ``fixed_nodes`` (a stale anchor selection
    that resolved to nothing) also falls back to the centroid pin, so the system
    never goes singular.

    Returns (K_free, f_free, free_dofs).
    """
    if fixed_nodes:
        pinned = {dof for node in fixed_nodes
                  for dof in range(6 * node, 6 * node + 6)}
    else:
        positions = np.array([n.position for n in mesh.nodes])
        centroid  = positions.mean(axis=0)
        fixed_node = int(np.argmin(np.linalg.norm(positions - centroid, axis=1)))
        pinned = set(range(6 * fixed_node, 6 * fixed_node + 6))

    n_dof = K.shape[0]
    free_dofs = np.array([i for i in range(n_dof) if i not in pinned], dtype=int)

    K_csr = K.tocsr()
    K_free = K_csr[free_dofs, :][:, free_dofs]
    f_free = f[free_dofs]
    return K_free, f_free, free_dofs


# ── Geometrically-nonlinear pre-stress solve (incremental corotational) ──────────

def _reframe_elements(mesh: FEMMesh, positions: List[np.ndarray]) -> None:
    """Recompute each beam element's length + frame from the CURRENT node positions
    (the corotational step): the element z-axis follows its chord, so as the bundle
    bends the element stiffness and eigenstrain load rotate with it."""
    for el in mesh.elements:
        v = positions[el.node_j] - positions[el.node_i]
        L = float(np.linalg.norm(v))
        if L < 1e-9:
            continue
        el.length = L
        el.R = _frame_from_helix_axis(v / L)


def solve_prestress_shape(
    design: Design,
    mesh: FEMMesh,
    n_steps: int = 30,
    fixed_nodes: Optional[List[int]] = None,
    field: Optional[dict] = None,
) -> np.ndarray:
    """Geometrically-nonlinear equilibrium shape under the loop/skip eigenstrain.

    Incremental corotational load-stepping: the eigenstrain force is applied in
    ``n_steps`` increments; after each increment the node positions are updated and the
    element frames recomputed from the deformed geometry (:func:`_reframe_elements`), so
    the elements co-rotate with the bending structure. This captures the large-deflection
    kinematics a single linear solve misses (a linear solve under-predicts a 90° bend as
    ~35°). Returns the final Nx3 node positions (nm). The straight/linear result is the
    ``n_steps=1`` limit.

    ``fixed_nodes`` (anchor node indices) are held clamped at every load step, so
    the anchored region stays at its rest position while the rest deflects; with
    ``None`` the centroid pin is used (pure free relaxation).

    ``field`` (optional, :func:`assemble_field_force`) adds a uniform E-field body load
    on top of the eigenstrain. It is a DEAD load — computed once in global coordinates and
    applied in the same ``n_steps`` increments — so as the bundle bends the field keeps
    pointing along the lab-frame direction (unlike the co-rotating eigenstrain). A field
    load needs an anchor to hold against (COM drift); with none, the centroid pin absorbs it.
    """
    positions = [n.position.copy() for n in mesh.nodes]
    f_field = assemble_field_force(mesh, field)      # dead load: global, not reframed
    for _ in range(n_steps):
        _reframe_elements(mesh, positions)
        K, _ = assemble_global_stiffness(mesh)
        f = (assemble_prestress_force(mesh, design) + f_field) / n_steps
        K_free, f_free, free = apply_boundary_conditions(K, f, mesh, fixed_nodes)
        du = solve_equilibrium(K_free, f_free, K.shape[0], free)
        for i in range(len(positions)):
            positions[i] = positions[i] + du[6 * i: 6 * i + 3]
    # restore the mesh frames to the pristine (undeformed) geometry for callers.
    _reframe_elements(mesh, [n.position for n in mesh.nodes])
    return np.array(positions)


# ── Equilibrium solve ──────────────────────────────────────────────────────────

def solve_equilibrium(
    K_free,
    f_free: np.ndarray,
    n_dof: int,
    free_dofs: np.ndarray,
) -> np.ndarray:
    """
    Solve K_free · u_free = f_free for the equilibrium displacements.

    Returns the full displacement vector u (zeros at pinned DOF).
    Raises ValueError if the system is singular (disconnected structure).
    """
    # NOTE: do NOT use warnings.catch_warnings()/filterwarnings here. The warnings
    # filter list is PROCESS-GLOBAL and not thread-safe. This solver runs in a
    # background daemon thread (cando_runner); flipping the global filter to "error"
    # leaked into concurrently-served HTTP handlers and promoted FastAPI's
    # ORJSONResponse DeprecationWarning to a real exception → intermittent 500s on
    # unrelated endpoints (e.g. GET /api/cando/jobs while a solve was mid-flight).
    # A singular/under-constrained system makes spsolve emit a MatrixRankWarning and
    # return NaNs, which the NaN/Inf guard below already catches — so no
    # warning-to-error trick is needed to detect it.
    try:
        u_free = spsolve(K_free, f_free)
    except Exception as exc:
        raise ValueError(
            "Stiffness matrix is singular — the design may have disconnected helices "
            "with no crossovers. Add crossovers to create a connected structure."
        ) from exc

    if np.any(np.isnan(u_free)) or np.any(np.isinf(u_free)):
        raise ValueError(
            "Stiffness matrix is singular — the design may have disconnected helices "
            "with no crossovers. Add crossovers to create a connected structure."
        )
    u = np.zeros(n_dof, dtype=float)
    u[free_dofs] = u_free
    return u


# ── RMSF computation ───────────────────────────────────────────────────────────

def compute_rmsf(
    K_free,
    free_dofs: np.ndarray,
    n_nodes: int,
    n_modes: int = N_RMSF_MODES,
) -> np.ndarray:
    """
    Estimate per-node RMSF (nm) from the n_modes lowest eigenmodes of K_free.

    RMSF_i = sqrt(k_BT × Σ_m  φ²_{m,i} / λ_m)

    Only translational DOF (x, y, z) contribute; rotational DOF are excluded.
    Returns an array of shape (n_nodes,).
    """
    n_free = len(free_dofs)
    # Clamp n_modes to a safe value below the matrix rank.
    k = min(n_modes, n_free - 2)
    if k < 1:
        return np.zeros(n_nodes, dtype=float)

    try:
        # Shift-invert mode (sigma=0): factorises K_free once via SuperLU, then
        # extracts the k smallest eigenvalues with fast Krylov convergence.
        # Typically 10-100× faster than which='SM' for sparse structural matrices.
        eigenvalues, eigenvectors = eigsh(K_free, k=k, sigma=0, which='LM')
    except Exception:
        return np.zeros(n_nodes, dtype=float)

    # Guard against near-zero / negative eigenvalues from numerical noise.
    eigenvalues = np.maximum(eigenvalues, 1e-12)

    # Build a set of free DOF indices for quick lookup.
    free_set = set(free_dofs.tolist())

    rmsf = np.zeros(n_nodes, dtype=float)
    for node_idx in range(n_nodes):
        variance = 0.0
        for dim in range(3):          # translational DOF only
            global_dof = 6 * node_idx + dim
            if global_dof not in free_set:
                continue
            # Position of this global DOF among the free DOFs.
            local_pos = np.searchsorted(free_dofs, global_dof)
            if local_pos >= n_free or free_dofs[local_pos] != global_dof:
                continue
            phi_row = eigenvectors[local_pos, :]        # shape (k,)
            variance += float(KBT * np.sum(phi_row**2 / eigenvalues))
        rmsf[node_idx] = math.sqrt(max(variance, 0.0))

    return rmsf


def compute_rmsf_nma(
    K,
    n_nodes: int,
    n_modes: int = N_RMSF_MODES,
    n_rigid: int = 6,
) -> np.ndarray:
    """Per-node RMSF (nm) via FREE-FREE normal-mode analysis — CanDo's method.

    Unlike :func:`compute_rmsf` (which pins a node and inherits a cantilever
    RMSF-grows-with-distance artifact), this leaves the structure free and projects
    out the ``n_rigid`` (=6) rigid-body modes, then sums the equipartition
    fluctuation over the next ``n_modes`` elastic modes:

        <u_i²> = k_BT · Σ_m  φ²_{m,i} / λ_m        (m over elastic modes)
        RMSF_i = sqrt(<u_x²> + <u_y²> + <u_z²>)

    This is the mass-independent static-fluctuation covariance kBT·K⁻¹ restricted to
    the low-frequency modes, matching CanDo's 200-mode equipartition RMSF at 298 K.
    Takes the FULL (un-pinned) global stiffness ``K``.
    """
    Kc = K.tocsr()
    n_dof = Kc.shape[0]
    k = min(n_modes + n_rigid, n_dof - 2)
    if k <= n_rigid:
        return np.zeros(n_nodes, dtype=float)

    try:
        vals, vecs = eigsh(Kc, k=k, sigma=1e-6, which="LM")
    except Exception:
        return np.zeros(n_nodes, dtype=float)

    order = np.argsort(vals)
    vals, vecs = vals[order], vecs[:, order]
    # Drop the rigid-body modes (≈0) and keep the elastic ones.
    lam = np.maximum(vals[n_rigid:], 1e-12)
    phi = vecs[:, n_rigid:]

    rmsf = np.zeros(n_nodes, dtype=float)
    for node_idx in range(n_nodes):
        var = 0.0
        for dim in range(3):                 # translational DOF only
            row = phi[6 * node_idx + dim, :]
            var += float(KBT * np.sum(row**2 / lam))
        rmsf[node_idx] = math.sqrt(max(var, 0.0))
    return rmsf


# ── Deformed position output ───────────────────────────────────────────────────

def deformed_positions(design: "Design", mesh: FEMMesh, u: np.ndarray) -> List[dict]:
    """Backbone display positions only (see :func:`deformed_positions_with_axis`)."""
    return deformed_positions_with_axis(design, mesh, u)[0]


def _rmf_frames(points: np.ndarray, seed_perp: np.ndarray):
    """Rotation-minimising frame (double-reflection, Wang et al. 2008) along an ordered 3-D
    polyline ``points`` (N×3).  Returns ``(tangents, e1, e2)`` — per-vertex unit tangent + the two
    cross-section axes, transported with MINIMAL twist so no spurious roll accrues along the curve.
    ``e1[0]`` is ``seed_perp`` projected ⊥ to the first tangent (ties the winding phase to the
    straight helix frame); ``e2 = tangent × e1``."""
    pts = np.asarray(points, dtype=float)
    n = len(pts)
    tans = np.zeros((n, 3))
    for i in range(n):
        if n == 1:
            v = np.array([0.0, 0.0, 1.0])
        elif i == 0:
            v = pts[1] - pts[0]
        elif i == n - 1:
            v = pts[-1] - pts[-2]
        else:
            v = pts[i + 1] - pts[i - 1]
        nv = float(np.linalg.norm(v))
        tans[i] = v / nv if nv > 1e-12 else (tans[i - 1] if i > 0 else np.array([0.0, 0.0, 1.0]))
    e1 = np.zeros((n, 3))
    e2 = np.zeros((n, 3))
    r = seed_perp - float(seed_perp @ tans[0]) * tans[0]
    if np.linalg.norm(r) < 1e-9:                              # seed parallel to tangent → pick any ⊥
        alt = np.array([1.0, 0.0, 0.0]) if abs(tans[0][0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        r = alt - float(alt @ tans[0]) * tans[0]
    e1[0] = r / np.linalg.norm(r)
    e2[0] = np.cross(tans[0], e1[0])
    for i in range(1, n):
        v1 = pts[i] - pts[i - 1]
        c1 = float(v1 @ v1)
        if c1 < 1e-18:                                        # coincident vertices → carry frame
            e1[i], e2[i] = e1[i - 1], np.cross(tans[i], e1[i - 1])
            continue
        rL = e1[i - 1] - (2.0 / c1) * float(v1 @ e1[i - 1]) * v1
        tL = tans[i - 1] - (2.0 / c1) * float(v1 @ tans[i - 1]) * v1
        v2 = tans[i] - tL
        c2 = float(v2 @ v2)
        ei = rL - (2.0 / c2) * float(v2 @ rL) * v2 if c2 > 1e-18 else rL
        nrm = float(np.linalg.norm(ei))
        e1[i] = ei / nrm if nrm > 1e-12 else e1[i - 1]
        e2[i] = np.cross(tans[i], e1[i])
    return tans, e1, e2


def _wound_backbones_for_helix(helix, straight_nucs, node_anchors):
    """Re-place a helix's straight backbone beads onto the FEM-DEFORMED axis with the cross-section
    frame carried along the curve (so beads wind correctly around a bent/twisted bundle instead of
    keeping their straight-frame radial direction).  Physical-layer / display only.

    ``node_anchors`` = list of ``(global_bp, straight_axis_position, deformed_axis_position)`` for
    this helix's duplex-core FEM nodes.  A rotation-minimising frame (RMF) is transported along the
    deformed axis, seeded from the straight helix frame.  Each bead is anchored to its OWN bp's node
    (nearest node for ssDNA ends / loop copies outside the core): its straight offset is split into
    an AXIAL part (rebuilt along the local deformed tangent) and a PERPENDICULAR part (its exact
    winding angle + radius, rebuilt in the transported cross-section frame).  This preserves helix
    radius, groove, and per-bp winding EXACTLY while following the deformed bend + twist.

    Returns ``(positions, normals, tangents)`` — three lists aligned 1:1 with ``straight_nucs``.
    ``normals``/``tangents`` are each bead's DESIGN base-normal + axis-tangent transported from the
    straight helix frame ``(e1s, e2s, axis_hat)`` into the wound frame ``(e1, e2, tan)`` — the exact
    same rotation the backbone winding uses — so the base-pair SLABS follow the wound backbones
    instead of keeping their straight-frame orientation (which left slabs splayed radially on a
    bent/mark-dense bundle).  Falls back to straight positions + design normals/tangents when the
    helix has < 2 duplex-core nodes (no axis to follow)."""
    start = helix.axis_start.to_array()
    end = helix.axis_end.to_array()
    axis_hat = (end - start)
    axis_hat = axis_hat / (np.linalg.norm(axis_hat) or 1.0)
    frame = _frame_from_helix_axis(axis_hat)
    e1s, e2s = frame[:, 0], frame[:, 1]

    anchors = sorted(node_anchors, key=lambda a: a[0])       # by global_bp
    if len(anchors) < 2:
        return (
            [n.position for n in straight_nucs],
            [n.base_normal for n in straight_nucs],
            [n.axis_tangent for n in straight_nucs],
        )
    bps = np.array([float(a[0]) for a in anchors])
    def_pts = np.array([a[2] for a in anchors])
    tans, E1, E2 = _rmf_frames(def_pts, e1s)
    # bp coordinate is drift-free: the FEM mesh spaces nodes at FEM_RISE_PER_BP (0.34) while the
    # display geometry uses the helix's own rise, so parametrise by bp (not absolute axial) — both
    # sides are then in the SAME units and a normal bead maps exactly onto its own bp's node.
    rise_geom = float(np.linalg.norm(end - start)) / max(1, helix.length_bp)

    def _at_bp(x: float):
        """Deformed axis position + RMF frame (e1, e2, tangent) at bp coordinate ``x`` (linear
        interp between the bracketing nodes; tangent-extrapolated in bp units beyond the ends —
        for ssDNA tips)."""
        if x <= bps[0]:
            return def_pts[0] + (x - bps[0]) * rise_geom * tans[0], E1[0], E2[0], tans[0]
        if x >= bps[-1]:
            return def_pts[-1] + (x - bps[-1]) * rise_geom * tans[-1], E1[-1], E2[-1], tans[-1]
        k = int(np.searchsorted(bps, x)) - 1
        k = max(0, min(k, len(bps) - 2))
        span = bps[k + 1] - bps[k]
        f = (x - bps[k]) / span if span > 1e-9 else 0.0
        pos = def_pts[k] * (1 - f) + def_pts[k + 1] * f
        near = k if f < 0.5 else k + 1
        return pos, E1[near], E2[near], tans[near]

    def _transport(d, e1, e2, tan):
        """Rotate a straight-frame direction into the wound frame: express in (e1s, e2s, axis_hat)
        then rebuild in (e1, e2, tan).  Both frames orthonormal → a pure rotation (norm preserved)."""
        w = float(d @ e1s) * e1 + float(d @ e2s) * e2 + float(d @ axis_hat) * tan
        n = float(np.linalg.norm(w))
        return w / n if n > 1e-12 else w

    positions, normals, tangents = [], [], []
    for nuc in straight_nucs:
        p = nuc.position
        s = float((p - start) @ axis_hat)
        perp = p - (start + s * axis_hat)                    # pure radial (⊥ axis line): winding
        r = float(np.linalg.norm(perp))
        az = math.atan2(float(perp @ e2s), float(perp @ e1s))
        # axial position as a bp coordinate: bp_start + s/rise_geom (== bp for a normal bead,
        # bp ± ½ for a loop copy's ±½-rise bulge) — so loop copies stay separated along the axis.
        x = helix.bp_start + (s / rise_geom if rise_geom > 1e-9 else 0.0)
        pos, e1, e2, tan = _at_bp(x)
        positions.append(pos + r * (math.cos(az) * e1 + math.sin(az) * e2))
        # Transport the base-normal + axis-tangent through the SAME straight→wound rotation so the
        # slab frame (built from bnDir + tanDir) tracks the wound backbone.
        normals.append(_transport(np.asarray(nuc.base_normal, dtype=float), e1, e2, tan))
        tangents.append(_transport(np.asarray(nuc.axis_tangent, dtype=float), e1, e2, tan))
    return positions, normals, tangents


def deformed_positions_with_axis(
    design: "Design",
    mesh: FEMMesh,
    u: np.ndarray,
) -> Tuple[List[dict], List[dict]]:
    """
    Apply FEM displacements to the actual backbone bead positions from the
    geometry layer and return ``(positions, axis)``: the per-nucleotide backbone
    display list AND the per-bp helix-axis (centre) node list, both rigid-body
    aligned to the displayed design frame with the SAME transform.

    The FEM model tracks axis-level displacements only.  Each backbone bead
    sits at HELIX_RADIUS from the axis in the radial direction.  The correct
    deformed backbone position is therefore:

        deformed_backbone = original_backbone + u_axis_node

    i.e., a rigid translation of the bead by the same displacement that moved
    its helix axis node.  This preserves the radial offset and keeps beads
    visible at the correct distance from the axis.

    COVERAGE / gap-fill: the FEM mesh nodes are the DUPLEX-CORE bp only.  ssDNA
    scaffold ends and loop/skip inserted bases have no mesh node, so they carry no
    FEM displacement of their own.  Emitting only the meshed beads strands those
    nucleotides at their native positions while the duplex core swings to the
    deformed shape — the connecting bonds then stretch across the gap (visible as
    long straight lines off the ends of a bent bundle).  To keep every nucleotide
    moving CONSISTENTLY, an uncovered nucleotide rides along with the nearest
    FEM-covered bp in the SAME helix (nearest by bp index — the duplex bp it sits
    next to).  This mirrors mrDNA's display reconstruction
    (:func:`mrdna_runner._display_positions`).  Purely geometric, display-only.

    FRAME ALIGNMENT: the FEM mesh is built on the STRAIGHT helix axes, so the FEM
    shape (straight base + eigenstrain bend) lives in the straight frame.  But the
    renderer draws the DISPLAYED geometry — ``nucleotide_positions`` with the design's
    DeformationOps + cluster transforms applied (:func:`deformation.deformed_nucleotide_
    positions`), which for a bent design is a very different pose.  Emitting the raw
    straight-frame FEM shape makes the whole model JUMP frames when the display toggles
    on.  So the FEM shape is rigid-body superimposed (Kabsch) onto the displayed geometry
    over the shared beads — it overlays the design in place and shows the FEM's own
    predicted curvature without a spurious translation/rotation, exactly as the mrDNA /
    oxDNA overlays do.  Rigid alignment preserves every intrinsic quantity (bond lengths,
    twist, curvature) — only the global pose changes.  Display-only; topology untouched.

    Returns a list of dicts covering EVERY nucleotide (incl. each loop-insert copy):
    {helix_id, bp_index, direction, copy, backbone_position, nx, ny, nz, tx, ty, tz}
    where (nx,ny,nz) is the wound base-normal (slab bnDir) and (tx,ty,tz) the wound
    axis-tangent (slab tanDir) — so the renderer's base slabs follow the wound backbones.
    """
    from backend.core.geometry import nucleotide_positions
    from backend.core.deformation import deformed_nucleotide_positions

    # Per-helix duplex-core FEM nodes: helix_id → [(straight_axis_pos, deformed_axis_pos)].
    # These anchor the rotation-minimising frame that carries each backbone bead's winding around
    # the DEFORMED axis (bend + global twist), instead of only translating it (which left beads
    # pointing in their straight-frame radial direction → visibly wrong on a curved bundle).
    node_anchors: Dict[str, list] = {}
    for idx, node in enumerate(mesh.nodes):
        disp = u[6 * idx: 6 * idx + 3]
        node_anchors.setdefault(node.helix_id, []).append(
            (node.global_bp, node.position, node.position + disp))

    # LOOP-COPY INDEX: a loop insertion places several nucleotides at ONE
    # (helix, bp, direction); the renderer distinguishes them by a `copy` index =
    # appearance order within that key (helix_renderer `_copySeenBB`).  We assign the
    # SAME index here — a running per-key counter over the nucleotide_positions order
    # (verified identical to the geometry endpoint's order) — so applyFemPositions /
    # applyScalarColors address EVERY loop copy, not only copy 0 (else the extra loop
    # bases strand at their native position/colour, uncovered by the deform/flex/
    # deviation overlays).  Plain (non-loop) nucleotides are the sole copy 0.
    from collections import Counter

    seen: Counter = Counter()
    meta: List[Tuple[str, int, str, int]] = []
    fem_pts:  List[np.ndarray] = []   # FEM-predicted (straight base + eigenstrain) position
    disp_pts: List[np.ndarray] = []   # displayed (DeformationOp/cluster) position — Kabsch target
    fem_nrm:  List[np.ndarray] = []   # wound base-normal (slab bnDir) per bead
    fem_tan:  List[np.ndarray] = []   # wound axis-tangent (slab tanDir) per bead
    for helix in design.helices:
        straight = list(nucleotide_positions(helix))
        shown    = list(deformed_nucleotide_positions(helix, design))
        # deformed_nucleotide_positions transforms the same list → same order/length.
        # If they ever diverge, fall back to the straight positions as the target (no jump
        # correction, but never a mis-pairing).
        if len(shown) != len(straight):
            shown = straight
        # Wind every bead (incl. ssDNA ends + loop copies, by their axial coordinate) onto the
        # deformed axis with the transported cross-section frame — one call per helix.  The
        # normals/tangents ride the SAME rotation so the base slabs follow the wound backbones.
        wound, wnrm, wtan = _wound_backbones_for_helix(helix, straight, node_anchors.get(helix.id, []))
        for nuc, dn, w, wn, wt in zip(straight, shown, wound, wnrm, wtan):
            fem_pts.append(w)
            disp_pts.append(dn.position)
            fem_nrm.append(np.asarray(wn, dtype=float))
            fem_tan.append(np.asarray(wt, dtype=float))
            k = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
            meta.append((*k, seen[k]))
            seen[k] += 1

    fem_arr = np.asarray(fem_pts)
    cs, cd, R = _kabsch_transform(fem_arr, np.asarray(disp_pts))
    aligned = _apply_transform(fem_arr, cs, cd, R)
    # Rotate the direction vectors by the SAME Kabsch rotation (translation-free) so the slab
    # frame stays consistent with the aligned backbones.
    nrm_aligned = np.asarray(fem_nrm) @ R.T if fem_nrm else np.zeros((0, 3))
    tan_aligned = np.asarray(fem_tan) @ R.T if fem_tan else np.zeros((0, 3))
    positions = [
        {"helix_id": m[0], "bp_index": m[1], "direction": m[2], "copy": m[3],
         "backbone_position": p.tolist(),
         "nx": float(n[0]), "ny": float(n[1]), "nz": float(n[2]),
         "tx": float(t[0]), "ty": float(t[1]), "tz": float(t[2])}
        for m, p, n, t in zip(meta, aligned, nrm_aligned, tan_aligned)
    ]

    # The FEM AXIS-node positions (one per duplex-core bp = mesh node), carried through
    # the SAME rigid alignment as the backbones so they overlay in-frame.  These are the
    # true helix-CENTRE positions (not the backbone midpoint, which precesses around the
    # axis and makes a tube wobble along the helical groove) — the CanDo-style cylinder
    # rep threads its tubes through these.  Only duplex core → no ssDNA nodes.
    axis: List[dict] = []
    if mesh.nodes:
        node_pts = np.array([mesh.nodes[i].position + u[6 * i: 6 * i + 3]
                             for i in range(len(mesh.nodes))])
        node_aligned = _apply_transform(node_pts, cs, cd, R)
        axis = [
            {"helix_id": node.helix_id, "bp_index": node.global_bp,
             "position": node_aligned[i].tolist()}
            for i, node in enumerate(mesh.nodes)
        ]
    return positions, axis


def _kabsch_transform(src: np.ndarray, dst: np.ndarray):
    """Return ``(cs, cd, R)`` defining the rigid transform ``x → (x - cs) @ R.T + cd``
    that least-squares best-fits ``src`` onto ``dst`` (rotation + translation, no scale/
    reflection).  Degenerate inputs (< 3 points) give ``R = I`` (pure centroid shift)."""
    cs = src.mean(0) if src.shape[0] else np.zeros(3)
    cd = dst.mean(0) if dst.shape[0] else np.zeros(3)
    if src.shape[0] < 3:
        return cs, cd, np.eye(3)
    S, D = src - cs, dst - cd
    U, _, Vt = np.linalg.svd(S.T @ D)
    d = np.sign(np.linalg.det(Vt.T @ U.T))       # guard against a reflection
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return cs, cd, R


def _apply_transform(pts: np.ndarray, cs: np.ndarray, cd: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Apply a ``(cs, cd, R)`` rigid transform (from :func:`_kabsch_transform`)."""
    if pts.shape[0] == 0:
        return pts
    return (pts - cs) @ R.T + cd


def _rigid_superpose(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Kabsch: return ``src`` rigid-body transformed to least-squares best-fit ``dst``.
    Both are (N, 3).  Used to overlay the FEM-predicted shape onto the displayed design
    frame so the deform toggle doesn't jump."""
    if src.shape[0] == 0:
        return src
    cs, cd, R = _kabsch_transform(src, dst)
    return _apply_transform(src, cs, cd, R)


# ── Public shape-prediction entry point ──────────────────────────────────────────

def resolve_anchor_nodes(
    design: "Design", mesh: FEMMesh, anchors: Optional[List[dict]]
) -> Tuple[List[int], List[Tuple[str, int]]]:
    """Resolve anchor descriptors to (sorted FEM node indices, their (helix_id, bp) keys).

    Reuses the shared oxDNA anchor-scope resolver (``resolve_anchor_particles`` —
    overhang / cluster / domain / strand / base) to turn the descriptors into
    per-nucleotide ``(helix_id, bp, direction)`` keys, then collapses each onto the
    single duplex-core AXIS node it belongs to (FEM nodes are direction-independent,
    one per bp — both strands of a bp pin the same node). Nucleotides whose bp is not
    in the meshed duplex core (ssDNA overhang, auto_scaffold cap extension, extra-base
    inserts) drop silently, matching ``resolve_anchor_particles``' stale-selection
    tolerance. Anchors are a JOB-REQUEST annotation, never a topology edit (Three-Layer
    Law): this only reads positions/keys.
    """
    if not anchors:
        return [], []
    from backend.physics.oxdna_interface import resolve_anchor_particles

    _parts, keys = resolve_anchor_particles(design, anchors)
    node_by_hb = {(n.helix_id, n.global_bp): i for i, n in enumerate(mesh.nodes)}
    selected: dict[int, Tuple[str, int]] = {}
    for k in keys:
        hb = (k[0], k[1])                       # (helix_id, bp) — drop direction
        idx = node_by_hb.get(hb)
        if idx is not None:
            selected[idx] = hb
    nodes = sorted(selected)
    return nodes, [selected[i] for i in nodes]


def predict_shape(
    design: "Design",
    *,
    nonlinear: bool = True,
    n_steps: int = 20,
    with_rmsf: bool = True,
    anchors: Optional[List[dict]] = None,
    field: Optional[dict] = None,
) -> dict:
    """Predict the CanDo-style equilibrium shape + flexibility of ``design`` (Physical layer).

    The single entry point for the in-app "Predict shape (FEM)" feature. **Defaults to the
    geometrically-NONLINEAR corotational solve** (``nonlinear=True``): validated against the
    real CanDo web service on the exp36 battery, it reproduces CanDo's bend to ~0.95 on
    moderate bends, whereas the single linear solve under-predicts by ~10% (it straightens
    the arc ends). ``nonlinear=False`` runs the fast linear solve for previews.

    ``anchors`` (optional) is a list of anchor-scope descriptors (the shared oxDNA scopes —
    overhang / cluster / domain / strand / base) resolved to duplex-core node indices via
    :func:`resolve_anchor_nodes` and clamped as Dirichlet boundary conditions: the anchored
    bp are held at their rest positions while the rest of the bundle deflects under the
    loop/skip eigenstrain. A selection that resolves to nothing falls back to the free
    centroid-pinned solve (a no-op). Anchors are a job-request annotation, never a topology
    edit. The RMSF stays the free-free NMA flexibility regardless (an intrinsic property of
    the elastic network, calibrated against CanDo).

    ``field`` (optional) is the shared uniform-E-field descriptor ``{"field_pN", "dir"}``
    (:func:`assemble_field_force`) — the same per-nucleotide force oxDNA applies — added as a
    dead body load and solved (nonlinearly by default) for the deflection. A field needs
    ≥1 anchor to hold against (COM drift): pass ``anchors`` alongside it. The comparable
    field-response descriptor is measured by ``shape_metrics.field_response_profile`` on the
    returned frame vs the same design's field-off frame (the C2 oracle). Also a job-request
    annotation, never a topology edit.

    Three-Layer Law: the returned positions are DISPLAY-ONLY (Physical layer); this never
    mutates the topological or geometric layers. Returns::

        {"solver": "nonlinear"|"linear",
         "positions": [{helix_id, bp_index, direction, backbone_position}, ...],
         "anchor_keys": [[helix_id, bp], ...],   # duplex nodes actually clamped
         "rmsf":      [{helix_id, bp_index, rmsf_nm}, ...]  # omitted if with_rmsf=False
        }

    ``rmsf`` is the free-free NMA per-bp RMSF (nm), CanDo-matched (~0.9), keyed to the same
    duplex-core nodes as ``positions`` (one entry per axis node, direction-independent).

    Raises ``ValueError`` when the design has no double-helical core to solve (fewer than
    :data:`_MIN_FEM_NODES` duplex base pairs) — e.g. a lone unpaired scaffold/ssDNA strand.
    A beam FEM needs at least one element (two nodes); an empty mesh otherwise crashes deep
    in the solver with a cryptic ``AxisError``.  The job runner surfaces this message.
    """
    mesh = build_fem_mesh(design)
    if len(mesh.nodes) < _MIN_FEM_NODES:
        raise ValueError(
            f"CanDo FEM shape prediction needs a double-helical (duplex) core of at least "
            f"{_MIN_FEM_NODES} base pairs, but this design meshed {len(mesh.nodes)}. "
            "There is no paired region to solve — pair the scaffold with staples first."
        )

    fixed_nodes, anchor_keys = resolve_anchor_nodes(design, mesh, anchors)

    if nonlinear:
        positions = solve_prestress_shape(
            design, mesh, n_steps=n_steps, fixed_nodes=fixed_nodes, field=field)
        u = np.zeros(6 * len(mesh.nodes), dtype=float)
        for i in range(len(mesh.nodes)):
            u[6 * i: 6 * i + 3] = positions[i] - mesh.nodes[i].position
    else:
        K, _ = assemble_global_stiffness(mesh)
        f = assemble_prestress_force(mesh, design) + assemble_field_force(mesh, field)
        K_free, f_free, free = apply_boundary_conditions(K, f, mesh, fixed_nodes)
        u = solve_equilibrium(K_free, f_free, K.shape[0], free)

    positions, axis = deformed_positions_with_axis(design, mesh, u)
    out: dict = {
        "solver": "nonlinear" if nonlinear else "linear",
        "positions": positions,
        "axis": axis,   # per-bp helix-CENTRE nodes for the CanDo-style cylinder rep
        "anchor_keys": [[hid, bp] for (hid, bp) in anchor_keys],
    }
    if with_rmsf:
        K, _ = assemble_global_stiffness(mesh)
        rmsf = compute_rmsf_nma(K, len(mesh.nodes))
        out["rmsf"] = [
            {"helix_id": node.helix_id, "bp_index": node.global_bp,
             "rmsf_nm": float(rmsf[i])}
            for i, node in enumerate(mesh.nodes)
        ]
    return out


def normalize_rmsf(
    rmsf: np.ndarray,
    mesh: FEMMesh,
) -> dict:
    """
    Normalize per-node RMSF to [0, 1] and return a dict keyed by
    "{helix_id}:{bp_index}:{direction}" for both FORWARD and REVERSE.
    """
    rmsf_max = float(rmsf.max()) if rmsf.max() > 0 else 1.0
    result = {}
    for idx, node in enumerate(mesh.nodes):
        val = float(rmsf[idx]) / rmsf_max
        for direction in (Direction.FORWARD, Direction.REVERSE):
            key = f"{node.helix_id}:{node.global_bp}:{direction.value}"
            result[key] = val
    return result
