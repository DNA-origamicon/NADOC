"""
Physical layer — fast-mode helix-segment XPBD engine.

Each helix is discretised into 21-bp segments (2 full B-DNA turns).
Each segment is a particle with position and orientation.  Loop insertions
add LoopJoint particles with ssDNA bending stiffness.

Constraint types
────────────────
  BackboneConstraint  — distance between consecutive segment/joint particles
                        along each helix.  Rest length accounts for skips.
  BendConstraint      — 2nd-neighbor distance along each helix particle list.
                        alpha = ALPHA_BEND_DSDNA for normal junctions;
                        ALPHA_BEND_SSDNA for junctions involving a loop joint.
  CrossoverConstraint — inter-helix segment distance.  Uses explicit
                        Design.crossovers when present; falls back to spatial
                        proximity coupling for pure-topology test designs.
  RepulsionConstraint — soft repulsion for non-bonded pairs < FAST_REPULSION_DIST.

XPBD formulation: Müller 2020 (compliance-based).
  α̃ = α / dt²
  Δλ = (−C − α̃·λ) / (∇C^T M^{−1} ∇C + α̃)
  Δx = M^{−1} ∇C Δλ
"""

from __future__ import annotations

import math
import queue
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numba
import numpy as np

from backend.core.constants import (
    ALPHA_BACKBONE,
    ALPHA_BEND_DSDNA,
    ALPHA_BEND_SSDNA,
    ALPHA_CROSSOVER,
    ALPHA_REPULSION,
    BDNA_RISE_PER_BP,
    FAST_CROSSOVER_DIST_HC_NM,
    FAST_CROSSOVER_DIST_SQ_NM,
    FAST_MAX_FRAMES,
    FAST_REPULSION_CUTOFF_NM,
    FAST_REPULSION_DIST_NM,
    FAST_SEGMENT_BP,
    XPBD_CONVERGENCE_CONSECUTIVE_FRAMES,
    XPBD_CONVERGENCE_THRESHOLD_NM,
    XPBD_ITERATIONS,
    XPBD_SUBSTEPS,
)
from backend.core.models import Design, LatticeType
from backend.physics.skip_loop_mechanics import (
    LoopJointSpec,
    compute_loop_joints,
    compute_segment_bp_ranges,
)

# Module-level constants (used directly in tests)
CONVERGENCE_THRESHOLD: float = XPBD_CONVERGENCE_THRESHOLD_NM
CONVERGENCE_STREAK: int = XPBD_CONVERGENCE_CONSECUTIVE_FRAMES
_DT: float = 0.1          # XPBD timestep; scales compliance
_DT2: float = _DT * _DT   # precomputed

# Numba-visible scalar aliases for imported constants.
# Numba captures these as literals at JIT compile time.
_NB_ALPHA_BB:  float = ALPHA_BACKBONE
_NB_ALPHA_XO:  float = ALPHA_CROSSOVER
_NB_ALPHA_REP: float = ALPHA_REPULSION
_NB_REP_DIST:  float = FAST_REPULSION_DIST_NM
_NB_DT2:       float = _DT2


@dataclass
class FastSimState:
    """Particle system for fast-mode helix-segment XPBD."""

    # Particle state — N particles
    pos:      np.ndarray   # (N, 3) float64 — positions in nm
    orient:   np.ndarray   # (N, 4) float64 — quaternions [qx,qy,qz,qw]
    prev_pos: np.ndarray   # (N, 3) float64 — previous substep positions (updated per substep)
    mass:     np.ndarray   # (N,)   float64 — 1.0 segments, 0.3 loop joints

    # Backbone: consecutive particles along each helix (including joints)
    bb_ij:    np.ndarray   # (B, 2) int32
    bb_rest:  np.ndarray   # (B,)   float64

    # Bend: 2nd-neighbor pairs along each helix particle list
    bn_ij:    np.ndarray   # (Bn, 2) int32
    bn_alpha: np.ndarray   # (Bn,)   float64 — per-pair compliance
    bn_rest:  np.ndarray   # (Bn,)   float64 — initial 2nd-neighbor distances

    # Crossover: inter-helix distance constraints
    xo_ij:    np.ndarray   # (X, 2) int32
    xo_rest:  np.ndarray   # (X,)   float64

    # Repulsion: non-bonded pairs within cutoff (rebuilt every 10 frames)
    rep_ij:   np.ndarray   # (R, 2) int32

    # Metadata
    particle_ids:      List[str]             # label per particle
    helix_segment_map: Dict[str, List[int]]  # helix_id → segment particle indices
    is_loop_joint:     np.ndarray            # (N,) bool — True for joint particles

    frame_count: int = 0
    converged:   bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _effective_segment_length(helix, bp_s: int, bp_e: int) -> float:
    """
    Effective backbone rest length for the segment [bp_s, bp_e).

    Each skip (delta=-1) in the range reduces the effective bp count by 1.
    Loops (delta>0) in the range are handled via joint particles; ignore them
    here so we don't double-count their path contribution.
    """
    skip_count = sum(
        1 for ls in helix.loop_skips
        if bp_s <= ls.bp_index < bp_e and ls.delta < 0
    )
    effective_bp = max(1, (bp_e - bp_s) - skip_count)
    return effective_bp * BDNA_RISE_PER_BP


def _find_helix_neighbors(design: Design) -> Dict[str, List[str]]:
    """
    Return a dict mapping helix_id → list of neighboring helix_ids.
    Two helices are neighbors if their axis XY distance ≤ 1.15 × lattice spacing.
    """
    helix_xy: Dict[str, np.ndarray] = {}
    for h in design.helices:
        helix_xy[h.id] = np.array([h.axis_start.x, h.axis_start.y])

    if design.lattice_type == LatticeType.HONEYCOMB:
        spacing = FAST_CROSSOVER_DIST_HC_NM
    else:
        spacing = FAST_CROSSOVER_DIST_SQ_NM

    cutoff = spacing * 1.15
    neighbors: Dict[str, List[str]] = {h.id: [] for h in design.helices}
    ids = list(helix_xy.keys())
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            dist = float(np.linalg.norm(helix_xy[a] - helix_xy[b]))
            if dist <= cutoff:
                neighbors[a].append(b)
                neighbors[b].append(a)
    return neighbors


def _rebuild_repulsion_pairs(sim: FastSimState) -> None:
    """
    Rebuild the non-bonded repulsion pair list using spatial proximity.
    Any pair (i, j) with |pos[i] - pos[j]| < FAST_REPULSION_CUTOFF_NM is
    included, excluding pairs already connected by backbone or crossover constraints.
    """
    N = sim.pos.shape[0]
    bonded: set = set()
    for k in range(sim.bb_ij.shape[0]):
        i, j = int(sim.bb_ij[k, 0]), int(sim.bb_ij[k, 1])
        bonded.add((min(i, j), max(i, j)))
    for k in range(sim.xo_ij.shape[0]):
        i, j = int(sim.xo_ij[k, 0]), int(sim.xo_ij[k, 1])
        bonded.add((min(i, j), max(i, j)))

    cutoff2 = FAST_REPULSION_CUTOFF_NM ** 2
    pairs = []
    for i in range(N):
        for j in range(i + 1, N):
            if (i, j) in bonded:
                continue
            d = sim.pos[j] - sim.pos[i]
            if float(np.dot(d, d)) < cutoff2:
                pairs.append([i, j])

    if pairs:
        sim.rep_ij = np.array(pairs, dtype=np.int32)
    else:
        sim.rep_ij = np.empty((0, 2), dtype=np.int32)


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────


def build_fast_simulation(design: Design) -> FastSimState:
    """
    Build a FastSimState from a Design.

    Reads only from the topological layer (design.helices, design.crossovers).
    Never modifies the Design or calls geometry.py.
    """
    # ── Pass 1: Particle positions and metadata ───────────────────────────────

    pos_list:    List[np.ndarray] = []
    mass_list:   List[float]      = []
    pid_list:    List[str]        = []
    is_joint:    List[bool]       = []

    # helix_all_particles: helix_id → particle indices in segment/joint order
    helix_all_particles: Dict[str, List[int]] = {}
    # helix_segment_map: helix_id → segment-only particle indices
    helix_segment_map:   Dict[str, List[int]] = {}
    # mapping: particle_idx → (helix_id, is_loop_joint)
    particle_helix: List[Tuple[str, bool]] = []

    pidx = 0
    helix_map = {h.id: h for h in design.helices}

    for h in design.helices:
        seg_ranges   = compute_segment_bp_ranges(h)
        loop_joints  = compute_loop_joints(h, seg_ranges)
        joint_by_seg = {j.seg_before_idx: j for j in loop_joints}

        axis_s = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        axis_e = np.array([h.axis_end.x,   h.axis_end.y,   h.axis_end.z])
        total_bp = h.length_bp if h.length_bp > 0 else 1

        helix_all_particles[h.id] = []
        helix_segment_map[h.id]   = []

        for seg_idx, (bp_s, bp_e) in enumerate(seg_ranges):
            # Segment centroid: midpoint of bp range along axis
            frac = (bp_s + bp_e) * 0.5 / total_bp
            p = axis_s + frac * (axis_e - axis_s)

            pos_list.append(p.copy())
            mass_list.append(1.0)
            pid_list.append(f"{h.id}_s{seg_idx}")
            is_joint.append(False)
            helix_all_particles[h.id].append(pidx)
            helix_segment_map[h.id].append(pidx)
            particle_helix.append((h.id, False))
            pidx += 1

            # Insert loop joint AFTER this segment if present
            if seg_idx in joint_by_seg:
                frac_j = bp_e / total_bp
                jp = axis_s + frac_j * (axis_e - axis_s)

                pos_list.append(jp.copy())
                mass_list.append(0.3)
                pid_list.append(f"{h.id}_loop_{seg_idx}_{seg_idx + 1}")
                is_joint.append(True)
                helix_all_particles[h.id].append(pidx)
                particle_helix.append((h.id, True))
                pidx += 1

    N = pidx
    pos      = np.array(pos_list,  dtype=np.float64)
    mass     = np.array(mass_list, dtype=np.float64)
    orient   = np.zeros((N, 4), dtype=np.float64)
    orient[:, 3] = 1.0   # identity quaternion
    prev_pos = pos.copy()
    is_joint_arr = np.array(is_joint, dtype=bool)

    # ── Pass 2: Backbone constraints ─────────────────────────────────────────

    bb_ij_list:   List[List[int]] = []
    bb_rest_list: List[float]     = []

    for h in design.helices:
        all_p = helix_all_particles[h.id]
        seg_ranges  = compute_segment_bp_ranges(h)
        loop_joints = compute_loop_joints(h, seg_ranges)
        joint_by_seg = {j.seg_before_idx: j for j in loop_joints}

        # Build per-particle info: (particle_idx, is_joint, seg_idx_or_None, joint_spec_or_None)
        info: List[Tuple[int, bool, Optional[int], Optional[LoopJointSpec]]] = []
        seg_cursor = 0
        for p in all_p:
            if not is_joint_arr[p]:
                info.append((p, False, seg_cursor, None))
                seg_cursor += 1
            else:
                # Joint inserted after seg_cursor-1
                info.append((p, True, None, joint_by_seg.get(seg_cursor - 1)))

        for k in range(len(info) - 1):
            pi, pi_is_j, pi_seg, pi_jspec = info[k]
            pj, pj_is_j, pj_seg, pj_jspec = info[k + 1]

            if not pi_is_j and not pj_is_j:
                # seg → seg (no joint between them): effective length from skip count
                bp_s, bp_e = seg_ranges[pi_seg]
                rest = _effective_segment_length(h, bp_s, bp_e)
            elif not pi_is_j and pj_is_j:
                # seg → joint: half the joint's rest length
                joint = pj_jspec
                rest = joint.rest_length_nm * 0.5 if joint else BDNA_RISE_PER_BP
            else:
                # joint → seg: other half
                joint = pi_jspec
                rest = joint.rest_length_nm * 0.5 if joint else BDNA_RISE_PER_BP

            bb_ij_list.append([pi, pj])
            bb_rest_list.append(rest)

    bb_ij   = np.array(bb_ij_list,   dtype=np.int32)  if bb_ij_list   else np.empty((0, 2), np.int32)
    bb_rest = np.array(bb_rest_list, dtype=np.float64) if bb_rest_list else np.empty(0, np.float64)

    # Build backbone-rest lookup for Pass 3: (i,j) → rest length
    # This lets bend constraints use the sum of their two backbone rests, which
    # guarantees the triangle inequality is satisfiable (prevents incompatible constraints).
    _bb_rest_lookup: Dict[Tuple[int, int], float] = {
        (pair[0], pair[1]): r
        for pair, r in zip(bb_ij_list, bb_rest_list)
    }

    # ── Pass 3: Bend constraints ──────────────────────────────────────────────

    bn_ij_list:   List[List[int]] = []
    bn_alpha_list: List[float]   = []
    bn_rest_list:  List[float]   = []

    for h in design.helices:
        all_p = helix_all_particles[h.id]
        if len(all_p) < 3:
            continue
        for k in range(len(all_p) - 2):
            pi = all_p[k]
            pm = all_p[k + 1]   # middle particle
            pk = all_p[k + 2]
            # Alpha: ssDNA if either endpoint is a loop joint, else dsDNA
            if is_joint_arr[pi] or is_joint_arr[pk]:
                alpha = ALPHA_BEND_SSDNA
            else:
                alpha = ALPHA_BEND_DSDNA
            # Rest = sum of the two backbone rests (pi→pm) + (pm→pk).
            # This guarantees the constraint is satisfiable: the collinear
            # configuration achieves exactly this distance, and any bending
            # reduces it → constraint resists bending.
            r1 = _bb_rest_lookup.get((pi, pm), 0.0)
            r2 = _bb_rest_lookup.get((pm, pk), 0.0)
            rest = r1 + r2
            bn_ij_list.append([pi, pk])
            bn_alpha_list.append(alpha)
            bn_rest_list.append(rest)

    bn_ij    = np.array(bn_ij_list,    dtype=np.int32)   if bn_ij_list    else np.empty((0, 2), np.int32)
    bn_alpha = np.array(bn_alpha_list, dtype=np.float64) if bn_alpha_list else np.empty(0, np.float64)
    bn_rest  = np.array(bn_rest_list,  dtype=np.float64) if bn_rest_list  else np.empty(0, np.float64)

    # ── Pass 4: Crossover constraints ─────────────────────────────────────────

    xo_ij_list:   List[List[int]] = []
    xo_rest_list: List[float]     = []

    strand_map = {s.id: s for s in design.strands}

    if design.crossovers and design.strands:
        # Build from explicit topology
        n_segs_map = {h.id: len(helix_segment_map[h.id]) for h in design.helices}
        for xover in design.crossovers:
            if xover.strand_a_id not in strand_map or xover.strand_b_id not in strand_map:
                continue
            sa = strand_map[xover.strand_a_id]
            sb = strand_map[xover.strand_b_id]
            if xover.domain_a_index >= len(sa.domains) or xover.domain_b_index >= len(sb.domains):
                continue
            da = sa.domains[xover.domain_a_index]
            db = sb.domains[xover.domain_b_index]
            if da.helix_id not in helix_map or db.helix_id not in helix_map:
                continue
            ha = helix_map[da.helix_id]
            hb = helix_map[db.helix_id]
            # Map bp to segment index
            seg_a = min(
                (da.end_bp - ha.bp_start) // FAST_SEGMENT_BP,
                n_segs_map[da.helix_id] - 1,
            )
            seg_b = min(
                (db.start_bp - hb.bp_start) // FAST_SEGMENT_BP,
                n_segs_map[db.helix_id] - 1,
            )
            seg_a = max(0, seg_a)
            seg_b = max(0, seg_b)
            pi = helix_segment_map[da.helix_id][seg_a]
            pj = helix_segment_map[db.helix_id][seg_b]
            rest = float(np.linalg.norm(pos[pi] - pos[pj]))
            xo_ij_list.append([pi, pj])
            xo_rest_list.append(max(rest, 0.1))
    else:
        # Implicit crossovers: spatial neighbor coupling, one constraint per segment pair
        neighbors = _find_helix_neighbors(design)
        seen: set = set()
        for h_id, nbr_ids in neighbors.items():
            for nh_id in nbr_ids:
                key = (min(h_id, nh_id), max(h_id, nh_id))
                if key in seen:
                    continue
                seen.add(key)
                segs_a = helix_segment_map[h_id]
                segs_b = helix_segment_map[nh_id]
                n = min(len(segs_a), len(segs_b))
                for k in range(n):
                    pi = segs_a[k]
                    pj = segs_b[k]
                    rest = float(np.linalg.norm(pos[pi] - pos[pj]))
                    xo_ij_list.append([pi, pj])
                    xo_rest_list.append(max(rest, 0.1))

    xo_ij   = np.array(xo_ij_list,   dtype=np.int32)   if xo_ij_list   else np.empty((0, 2), np.int32)
    xo_rest = np.array(xo_rest_list, dtype=np.float64)  if xo_rest_list else np.empty(0, np.float64)

    sim = FastSimState(
        pos=pos,
        orient=orient,
        prev_pos=prev_pos,
        mass=mass,
        bb_ij=bb_ij,
        bb_rest=bb_rest,
        bn_ij=bn_ij,
        bn_alpha=bn_alpha,
        bn_rest=bn_rest,
        xo_ij=xo_ij,
        xo_rest=xo_rest,
        rep_ij=np.empty((0, 2), dtype=np.int32),
        particle_ids=pid_list,
        helix_segment_map=helix_segment_map,
        is_loop_joint=is_joint_arr,
    )
    _rebuild_repulsion_pairs(sim)
    return sim


# ─────────────────────────────────────────────────────────────────────────────
# Numba helpers — must be @njit to be callable from other @njit functions
# ─────────────────────────────────────────────────────────────────────────────


@numba.njit(cache=True)
def _norm3(v: np.ndarray) -> float:
    """Euclidean norm of a 3-element 1-D array (no scipy required)."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


# ─────────────────────────────────────────────────────────────────────────────
# Constraint solver — Numba JIT
# ─────────────────────────────────────────────────────────────────────────────


@numba.njit(cache=True)
def _project_distance_constraint(
    pos: np.ndarray,
    i: int,
    j: int,
    rest: float,
    alpha: float,
    lam: float,
    inv_mi: float,
    inv_mj: float,
) -> Tuple[float, float]:
    """
    XPBD Müller 2020 distance constraint.
    Returns (Δλ, max_displacement).
    Modifies pos in-place.
    """
    alpha_tilde = alpha / _NB_DT2
    d = pos[j] - pos[i]
    dist = _norm3(d)
    if dist < 1e-9:
        return 0.0, 0.0
    d_hat = d / dist
    C = dist - rest
    denom = (inv_mi + inv_mj) + alpha_tilde
    d_lambda = (-C - alpha_tilde * lam) / denom
    corr = d_lambda * d_hat
    disp_i = inv_mi * corr
    disp_j = inv_mj * corr
    pos[i] -= disp_i
    pos[j] += disp_j
    return d_lambda, max(_norm3(disp_i), _norm3(disp_j))


@numba.njit(cache=True)
def _solve_constraints_inner(
    pos:      np.ndarray,  # (N, 3) float64 — modified in place
    mass:     np.ndarray,  # (N,)   float64
    bb_ij:    np.ndarray,  # (B, 2) int32
    bb_rest:  np.ndarray,  # (B,)   float64
    bn_ij:    np.ndarray,  # (Bn, 2) int32
    bn_alpha: np.ndarray,  # (Bn,)  float64
    bn_rest:  np.ndarray,  # (Bn,)  float64
    xo_ij:   np.ndarray,   # (X, 2) int32
    xo_rest: np.ndarray,   # (X,)   float64
    rep_ij:  np.ndarray,   # (R, 2) int32
    n_iterations: int,
) -> float:
    """
    One XPBD substep: reset lambdas, run n_iterations of Gauss-Seidel
    constraint projection.  Returns max per-particle displacement (nm).
    """
    n_bb  = bb_ij.shape[0]
    n_bn  = bn_ij.shape[0]
    n_xo  = xo_ij.shape[0]
    n_rep = rep_ij.shape[0]

    lam_bb  = np.zeros(n_bb,  dtype=np.float64)
    lam_bn  = np.zeros(n_bn,  dtype=np.float64)
    lam_xo  = np.zeros(n_xo,  dtype=np.float64)

    max_disp = 0.0

    for _ in range(n_iterations):
        # Backbone constraints
        for k in range(n_bb):
            i, j = int(bb_ij[k, 0]), int(bb_ij[k, 1])
            inv_mi = 1.0 / mass[i]
            inv_mj = 1.0 / mass[j]
            dl, disp = _project_distance_constraint(
                pos, i, j, float(bb_rest[k]), _NB_ALPHA_BB, float(lam_bb[k]),
                inv_mi, inv_mj,
            )
            lam_bb[k] += dl
            if disp > max_disp:
                max_disp = disp

        # Bend constraints
        for k in range(n_bn):
            i, j = int(bn_ij[k, 0]), int(bn_ij[k, 1])
            inv_mi = 1.0 / mass[i]
            inv_mj = 1.0 / mass[j]
            dl, disp = _project_distance_constraint(
                pos, i, j, float(bn_rest[k]), float(bn_alpha[k]), float(lam_bn[k]),
                inv_mi, inv_mj,
            )
            lam_bn[k] += dl
            if disp > max_disp:
                max_disp = disp

        # Crossover constraints
        for k in range(n_xo):
            i, j = int(xo_ij[k, 0]), int(xo_ij[k, 1])
            inv_mi = 1.0 / mass[i]
            inv_mj = 1.0 / mass[j]
            dl, disp = _project_distance_constraint(
                pos, i, j, float(xo_rest[k]), _NB_ALPHA_XO, float(lam_xo[k]),
                inv_mi, inv_mj,
            )
            lam_xo[k] += dl
            if disp > max_disp:
                max_disp = disp

        # Repulsion constraints (one-directional: only push apart)
        alpha_tilde_rep = _NB_ALPHA_REP / _NB_DT2
        for k in range(n_rep):
            i, j = int(rep_ij[k, 0]), int(rep_ij[k, 1])
            d = pos[j] - pos[i]
            dist = _norm3(d)
            if dist < 1e-9 or dist >= _NB_REP_DIST:
                continue
            d_hat = d / dist
            C = dist - _NB_REP_DIST   # C < 0 (too close)
            inv_mi = 1.0 / mass[i]
            inv_mj = 1.0 / mass[j]
            denom = (inv_mi + inv_mj) + alpha_tilde_rep
            d_lambda = -C / denom   # positive (push apart)
            corr = d_lambda * d_hat
            disp_i = _norm3(inv_mi * corr)
            disp_j = _norm3(inv_mj * corr)
            pos[i] -= inv_mi * corr
            pos[j] += inv_mj * corr
            disp = max(disp_i, disp_j)
            if disp > max_disp:
                max_disp = disp

    return max_disp


# Fraction of velocity removed per substep for XPBD damping.
# At 10 substeps/frame: per-frame velocity retention = (1-_SUBSTEP_DAMPING)^10
# 0.05 → ~0.60 per frame; system settles in ~15-30 frames.
_SUBSTEP_DAMPING: float = 0.05


def fast_xpbd_step(sim: FastSimState) -> float:
    """
    Run XPBD_SUBSTEPS substeps with XPBD_ITERATIONS iterations each.

    Each substep applies velocity-Verlet-style integration with damping:
      dp = (pos - prev_pos) * (1 - damping)   # damped inertia
      prev_pos ← pos
      pos ← pos + dp                           # predict
      project constraints → pos                # correct

    Returns max constraint-correction magnitude (nm) across all substeps.
    Convergence ↔ max_disp < CONVERGENCE_THRESHOLD for CONVERGENCE_STREAK frames.
    """
    max_disp_total = 0.0

    for _ in range(XPBD_SUBSTEPS):
        # Damped inertia: carry forward (1-damping) of previous displacement
        dp = (sim.pos - sim.prev_pos) * (1.0 - _SUBSTEP_DAMPING)
        sim.prev_pos[:] = sim.pos
        sim.pos += dp   # predict

        max_disp = _solve_constraints_inner(
            sim.pos,
            sim.mass,
            sim.bb_ij,
            sim.bb_rest,
            sim.bn_ij,
            sim.bn_alpha,
            sim.bn_rest,
            sim.xo_ij,
            sim.xo_rest,
            sim.rep_ij,
            XPBD_ITERATIONS,
        )
        if max_disp > max_disp_total:
            max_disp_total = max_disp

    sim.frame_count += 1
    if sim.frame_count % 10 == 0:
        _rebuild_repulsion_pairs(sim)

    return max_disp_total


# ─────────────────────────────────────────────────────────────────────────────
# Output serialisation
# ─────────────────────────────────────────────────────────────────────────────


def positions_to_fast_updates(sim: FastSimState) -> List[dict]:
    """Serialise current positions to WebSocket-ready dicts."""
    updates = []
    for idx, pid in enumerate(sim.particle_ids):
        x, y, z = float(sim.pos[idx, 0]), float(sim.pos[idx, 1]), float(sim.pos[idx, 2])
        qx, qy, qz, qw = (float(sim.orient[idx, k]) for k in range(4))
        updates.append({
            "id":     pid,
            "pos":    [x, y, z],
            "orient": [qx, qy, qz, qw],
        })
    return updates


# ─────────────────────────────────────────────────────────────────────────────
# Background solver
# ─────────────────────────────────────────────────────────────────────────────


class FastXPBDSolver:
    """
    Wraps FastSimState + background thread.
    Pushes (frame, converged, updates) to an output queue.
    """

    def __init__(self, design: Design):
        self._sim    = build_fast_simulation(design)
        self._queue: queue.Queue = queue.Queue(maxsize=32)
        self._stop   = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def get_updates(self) -> Optional[Tuple[int, bool, List[dict]]]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _run(self) -> None:
        sim = self._sim
        streak = 0
        for frame in range(FAST_MAX_FRAMES):
            if self._stop.is_set():
                break
            max_disp = fast_xpbd_step(sim)
            updates  = positions_to_fast_updates(sim)
            try:
                self._queue.put_nowait((frame, False, updates))
            except queue.Full:
                pass  # drop if consumer is slow

            if max_disp < CONVERGENCE_THRESHOLD:
                streak += 1
            else:
                streak = 0
            if streak >= CONVERGENCE_STREAK:
                try:
                    self._queue.put((frame, True, updates), timeout=1.0)
                except queue.Full:
                    pass
                break


# ─────────────────────────────────────────────────────────────────────────────
# Warm-start for detailed mode
# ─────────────────────────────────────────────────────────────────────────────


def warmstart_from_fast(fast_sim: FastSimState, design: Design, geometry) -> "SimState":
    """
    Build a detailed-mode SimState (xpbd.py) with nucleotide positions
    derived from fast-mode converged segment positions.

    Each nucleotide's position is set by distributing it around the converged
    segment centre using standard B-DNA geometry (helix_radius, twist, rise).
    This gives lower initial constraint residuals than initialising from
    canonical axis geometry.
    """
    from backend.physics.xpbd import build_simulation

    helix_map = {h.id: h for h in design.helices}

    # Build the fast-mode helix-to-segment position map
    seg_pos_map: Dict[str, List[np.ndarray]] = {}
    for h_id, seg_indices in fast_sim.helix_segment_map.items():
        seg_pos_map[h_id] = [fast_sim.pos[idx].copy() for idx in seg_indices]

    # Build an adjusted geometry list where each nucleotide position is
    # displaced from the converged segment centre rather than the canonical axis.
    from backend.core.geometry import NucleotidePosition

    adjusted: List = []
    for np_orig in geometry:
        h = helix_map.get(np_orig.helix_id)
        if h is None:
            adjusted.append(np_orig)
            continue
        seg_ranges = compute_segment_bp_ranges(h)
        if not seg_ranges:
            adjusted.append(np_orig)
            continue
        # Find which segment this nucleotide falls in
        bp = np_orig.bp_index
        seg_idx = min((bp - h.bp_start) // FAST_SEGMENT_BP, len(seg_ranges) - 1)
        seg_idx = max(0, seg_idx)

        segs = seg_pos_map.get(h.id)
        if segs is None or seg_idx >= len(segs):
            adjusted.append(np_orig)
            continue

        # Offset from canonical axis to fast-mode segment centre
        seg_centre_fast = segs[seg_idx]
        # Canonical segment centre
        bp_s, bp_e = seg_ranges[seg_idx]
        frac = (bp_s + bp_e) * 0.5 / h.length_bp
        axis_s = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        axis_e = np.array([h.axis_end.x,   h.axis_end.y,   h.axis_end.z])
        seg_centre_canon = axis_s + frac * (axis_e - axis_s)

        delta = seg_centre_fast - seg_centre_canon
        new_pos      = np_orig.position + delta
        new_base_pos = np_orig.base_position + delta

        adjusted.append(NucleotidePosition(
            helix_id=np_orig.helix_id,
            bp_index=np_orig.bp_index,
            direction=np_orig.direction,
            position=new_pos,
            base_position=new_base_pos,
            base_normal=np_orig.base_normal,
            axis_tangent=np_orig.axis_tangent,
        ))

    return build_simulation(design, adjusted)


# ─────────────────────────────────────────────────────────────────────────────
# Numba AOT precompilation — trigger JIT at import time so the first real
# WebSocket request does not pay the compilation cost.
# cache=True persists compiled bytecode to __pycache__ after the first run.
# ─────────────────────────────────────────────────────────────────────────────

def _precompile_numba() -> None:
    _p  = np.zeros((4, 3), np.float64)
    _m  = np.ones(4, np.float64)
    _ij = np.array([[0, 1], [1, 2]], dtype=np.int32)
    _r  = np.array([1.0, 1.0], np.float64)
    _a  = np.array([1e-5, 1e-5], np.float64)
    _r1 = np.array([1.0], np.float64)
    _ij1 = np.array([[0, 1]], dtype=np.int32)
    _rep = np.empty((0, 2), dtype=np.int32)
    _solve_constraints_inner(_p, _m, _ij1, _r1, _ij, _a, _r, _ij1, _r1, _rep, 1)


_precompile_numba()
