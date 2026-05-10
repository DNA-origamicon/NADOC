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
- Crossover springs enforce zero relative displacement between connected axis
  nodes (both nodes must move together).  No pre-stress force is applied —
  for a correctly-designed DNA origami the equilibrium is the designed
  geometry (u ≈ 0).  Torsional pre-stress from helix under/over-winding is
  not modelled; the primary output is the RMSF heatmap.
- RMSF is computed from the 30 lowest eigenmodes of the free-DOF stiffness
  matrix: RMSF_i = sqrt(k_BT × Σ_m φ²_m,i / λ_m)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import eigsh, spsolve

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import _frame_from_helix_axis
from backend.core.models import Design, Direction

# ── Physical constants (SI-pN-nm unit system) ─────────────────────────────────

EA_DS   = 1100.0   # pN — dsDNA axial stretch stiffness
EI_DS   = 230.0    # pN·nm² — dsDNA bending stiffness (isotropic)
GJ_DS   = 460.0    # pN·nm² — dsDNA torsional stiffness
L_P_SS  = 1.5      # nm — ssDNA persistence length
RISE_SS = 0.63     # nm — ssDNA rise per base (single-stranded)
KBT     = 4.11     # pN·nm — thermal energy at 310 K

K_PENALTY = 1.0e6  # pN/nm — effective spring constant for "rigid" crossovers
N_RMSF_MODES = 30  # number of lowest eigenmodes used for RMSF approximation


# ── Mesh data structures ───────────────────────────────────────────────────────

@dataclass
class FEMNode:
    """One node on the helix axis; 6 DOF."""
    helix_id: str
    global_bp: int          # global bp index (matches NucleotidePosition.bp_index)
    position: np.ndarray    # 3D axis position, nm


@dataclass
class FEMElement:
    """Euler-Bernoulli beam element between two adjacent nodes on the same helix."""
    node_i: int             # index into FEMMesh.nodes
    node_j: int             # index into FEMMesh.nodes (j = i+1 along helix)
    length: float           # nm
    R: np.ndarray           # 3×3 rotation: columns = [x̂, ŷ, ẑ_local] in global frame


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
class FEMMesh:
    nodes:    List[FEMNode]    = field(default_factory=list)
    elements: List[FEMElement] = field(default_factory=list)
    springs:  List[FEMSpring]  = field(default_factory=list)


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

        n_bp = round(length / BDNA_RISE_PER_BP)
        first_node_idx = len(mesh.nodes)
        bp_lo = helix.bp_start
        bp_hi = helix.bp_start + n_bp - 1
        helix_bp_range[helix.id] = (bp_lo, bp_hi)

        for local_i in range(n_bp):
            global_bp = local_i + helix.bp_start
            pos = start + axis_hat * (local_i * BDNA_RISE_PER_BP)
            idx = len(mesh.nodes)
            mesh.nodes.append(FEMNode(helix_id=helix.id, global_bp=global_bp, position=pos.copy()))
            node_map[(helix.id, global_bp)] = idx

        # Beam elements between consecutive nodes.
        for local_i in range(n_bp - 1):
            ni = first_node_idx + local_i
            nj = first_node_idx + local_i + 1
            mesh.elements.append(FEMElement(
                node_i=ni, node_j=nj,
                length=BDNA_RISE_PER_BP,
                R=R.copy(),
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
            k_rot   = 0.0
        else:
            # Standard DX crossover — rigid penalty spring.
            k_trans = K_PENALTY
            k_rot   = K_PENALTY

        mesh.springs.append(FEMSpring(
            node_i=ni, node_j=nj,
            k_trans=k_trans, k_rot=k_rot,
        ))

    return mesh


# ── Element stiffness matrices ────────────────────────────────────────────────

def _beam_stiffness_local(L: float) -> np.ndarray:
    """
    12×12 Euler-Bernoulli beam stiffness matrix in LOCAL frame.

    DOF ordering: [u1, v1, w1, θx1, θy1, θz1,  u2, v2, w2, θx2, θy2, θz2]
    Local beam axis = z direction.
    u = x-displacement, v = y-displacement, w = axial (z), θ_z = torsion.
    """
    K = np.zeros((12, 12), dtype=float)

    ea  = EA_DS / L
    gj  = GJ_DS / L
    # Bending in x-z plane (EI_y), couples u and θ_y (indices 0,4,6,10).
    ei  = EI_DS
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
    K_local = _beam_stiffness_local(BDNA_RISE_PER_BP)  # same L for all elements
    for el in mesh.elements:
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

    return K, f


# ── Boundary conditions ────────────────────────────────────────────────────────

def apply_boundary_conditions(
    K: lil_matrix,
    f: np.ndarray,
    mesh: FEMMesh,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Pin all 6 DOF of the node nearest the geometric centroid to remove
    rigid-body modes.

    Pinning the centroid node (rather than node 0) avoids a pure cantilever
    effect where RMSF increases monotonically from one end of the structure.
    The resulting RMSF is symmetric around the centre and reflects actual
    crossover-driven stiffness variation rather than distance from an arbitrary
    boundary.

    Returns (K_free, f_free, free_dofs).
    """
    positions = np.array([n.position for n in mesh.nodes])
    centroid  = positions.mean(axis=0)
    fixed_node = int(np.argmin(np.linalg.norm(positions - centroid, axis=1)))

    n_dof = K.shape[0]
    pinned = set(range(6 * fixed_node, 6 * fixed_node + 6))
    free_dofs = np.array([i for i in range(n_dof) if i not in pinned], dtype=int)

    K_csr = K.tocsr()
    K_free = K_csr[free_dofs, :][:, free_dofs]
    f_free = f[free_dofs]
    return K_free, f_free, free_dofs


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
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=Warning)
        try:
            u_free = spsolve(K_free, f_free)
        except Exception as exc:
            raise ValueError(
                "Stiffness matrix is singular — the design may have disconnected helices "
                "with no crossovers. Add crossovers to create a connected structure."
            ) from exc

    if np.any(np.isnan(u_free)) or np.any(np.isinf(u_free)):
        raise ValueError(
            "FEM solve produced invalid displacements (NaN/Inf). "
            "The structure may be under-constrained — ensure all helices are connected by crossovers."
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


# ── Deformed position output ───────────────────────────────────────────────────

def deformed_positions(
    design: "Design",
    mesh: FEMMesh,
    u: np.ndarray,
) -> List[dict]:
    """
    Apply FEM displacements to the actual backbone bead positions from the
    geometry layer and return the resulting positions.

    The FEM model tracks axis-level displacements only.  Each backbone bead
    sits at HELIX_RADIUS from the axis in the radial direction.  The correct
    deformed backbone position is therefore:

        deformed_backbone = original_backbone + u_axis_node

    i.e., a rigid translation of the bead by the same displacement that moved
    its helix axis node.  This preserves the radial offset and keeps beads
    visible at the correct distance from the axis.

    Returns a list of dicts: {helix_id, bp_index, direction, backbone_position}
    """
    from backend.core.geometry import nucleotide_positions

    # Build: (helix_id, global_bp, direction) → original backbone position
    orig: Dict[Tuple[str, int, str], np.ndarray] = {}
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            orig[(nuc.helix_id, nuc.bp_index, nuc.direction.value)] = nuc.position

    results = []
    for idx, node in enumerate(mesh.nodes):
        disp = u[6 * idx : 6 * idx + 3]
        for direction in (Direction.FORWARD, Direction.REVERSE):
            key = (node.helix_id, node.global_bp, direction.value)
            base = orig.get(key)
            if base is None:
                continue
            results.append({
                "helix_id":          node.helix_id,
                "bp_index":          node.global_bp,
                "direction":         direction.value,
                "backbone_position": (base + disp).tolist(),
            })
    return results


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
