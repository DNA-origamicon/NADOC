"""
Coarse-grained helix-level physics (CG-XPBD).

Model
─────
  Each helix is represented as a chain of **axis control points** (CPs),
  one per base-pair index.  A CP is the midpoint between the FORWARD and
  REVERSE backbone beads on the helix axis.

  Constraints
  ───────────
  1. Backbone bonds    — consecutive CPs within the same helix.
     Rest length = (1 + delta) × BDNA_RISE_PER_BP, where delta comes
     from Helix.loop_skips at that bp_index.
       loop (+1) → segment wants to be LONGER  → outer arc pushed out
       skip (−1) → segment wants to be SHORTER → inner arc pulled in
     Starting from straight positions, loop-modified segments are
     compressed by delta × BDNA_RISE_PER_BP, driving bend convergence.

  2. Crossover bonds   — inter-helix bonds detected from strand topology.
     Rest length = axis-to-axis distance in the straight geometry.
     Weighted by crossover_weight so they dominate constraint resolution
     and transmit loop/skip strain across the bundle.

  3. Bending bonds     — 2nd-neighbour CPs within the same helix.
     Rest length = 2 × BDNA_RISE_PER_BP; keeps helices rod-like.

  Output
  ──────
  CPs are expanded back to per-nucleotide backbone positions using a
  Gram-Schmidt frame: the original straight-geometry normals are
  re-orthogonalised against the current local tangent, so the helix
  cross-section rotates correctly as the axis curve evolves.

Architecture
────────────
  Topological layer  → Design (ground truth, never modified)
  Geometric layer    → straight axis positions + phase normals
  Physical layer     → CGSimState / relaxed axis positions (display only)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from backend.core.constants import (
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.models import Design, Direction


# ── Default parameters ────────────────────────────────────────────────────────

DEFAULT_CG_BACKBONE_STIFFNESS: float = 1.0   # backbone bond weight
DEFAULT_CG_BENDING_STIFFNESS:  float = 0.8   # 2nd-neighbour bending weight
DEFAULT_CG_CROSSOVER_WEIGHT:   float = 30.0  # crossover stiffness relative to backbone
DEFAULT_CG_SUBSTEPS:           int   = 80    # substeps per streamed frame
DEFAULT_CG_NOISE:              float = 0.0   # nm/substep thermal kick


# ── Simulation state ──────────────────────────────────────────────────────────


@dataclass
class CGSimState:
    """
    Mutable state for the coarse-grained helix simulation.

    positions : (N, 3) float64 — current helix axis control point positions.
    backbone_ij   : (M, 2) int32  — consecutive backbone bond pairs.
    backbone_rest : (M,)   float64 — backbone rest lengths (loop/skip encoded).
    crossover_ij  : (K, 2) int32  — inter-helix crossover bond pairs.
    crossover_rest: (K,)   float64 — crossover rest lengths.
    bending_ij    : (P, 2) int32  — 2nd-neighbour bending pairs.
    bending_rest  : (P,)   float64 — bending rest lengths.
    index_map : {(helix_id, bp_index) → particle_idx}
    particles : [(helix_id, bp_index), ...]

    fwd_normals : (N, 3) float64 — FORWARD backbone unit normals at each CP
                  (from straight geometry).  Used for position expansion.
    rev_normals : (N, 3) float64 — REVERSE backbone unit normals at each CP
                  (= fwd_normals rotated by BDNA_MINOR_GROOVE_ANGLE_RAD).
    """
    positions:       np.ndarray
    backbone_ij:     np.ndarray
    backbone_rest:   np.ndarray
    crossover_ij:    np.ndarray
    crossover_rest:  np.ndarray
    bending_ij:      np.ndarray
    bending_rest:    np.ndarray
    index_map:       Dict[Tuple[str, int], int]
    particles:       List[Tuple[str, int]]
    fwd_normals:     np.ndarray   # (N, 3) original straight normals for FORWARD
    rev_normals:     np.ndarray   # (N, 3) original straight normals for REVERSE

    step:                int   = 0
    backbone_stiffness:  float = DEFAULT_CG_BACKBONE_STIFFNESS
    bending_stiffness:   float = DEFAULT_CG_BENDING_STIFFNESS
    crossover_weight:    float = DEFAULT_CG_CROSSOVER_WEIGHT
    substeps_per_frame:  int   = DEFAULT_CG_SUBSTEPS
    noise_amplitude:     float = DEFAULT_CG_NOISE

    rng: np.random.Generator = field(
        default_factory=np.random.default_rng,
        repr=False, compare=False,
    )


# ── Geometry helpers ──────────────────────────────────────────────────────────


def _vec3_to_np(v) -> np.ndarray:
    """Convert a Vec3 Pydantic model (or any x/y/z object) to a float64 ndarray."""
    return np.array([v.x, v.y, v.z], dtype=np.float64)


def _axis_position(helix, k: int) -> np.ndarray:
    """Straight-geometry axis position for bp index k on helix."""
    s = _vec3_to_np(helix.axis_start)
    e = _vec3_to_np(helix.axis_end)
    # axis_end = axis_start + length_bp × rise × unit, so k/length_bp gives
    # the fractional position along the full axis span.
    return s + (k / helix.length_bp) * (e - s)


def _build_local_frame(helix) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build the local orthonormal frame (tangent, u, v) for a straight helix.

    tangent : unit vector along helix axis.
    u, v    : two perpendicular unit vectors spanning the cross-section plane.
    """
    s = _vec3_to_np(helix.axis_start)
    e = _vec3_to_np(helix.axis_end)
    tang = e - s
    length = float(np.linalg.norm(tang))
    tang = tang / length if length > 1e-12 else np.array([0.0, 0.0, 1.0])

    # Choose u perpendicular to tang using the least-aligned world axis.
    ref = np.array([1.0, 0.0, 0.0])
    if abs(tang[0]) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    u = np.cross(tang, ref)
    u /= np.linalg.norm(u)
    v = np.cross(tang, u)
    return tang, u, v


def _normals_for_helix(helix) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute per-bp FORWARD and REVERSE normals in the straight geometry.

    Returns fwd_norms (N, 3) and rev_norms (N, 3).
    """
    N = helix.length_bp
    _, u, v = _build_local_frame(helix)
    phi0 = helix.phase_offset

    angles_fwd = phi0 + np.arange(N) * BDNA_TWIST_PER_BP_RAD
    angles_rev = angles_fwd + BDNA_MINOR_GROOVE_ANGLE_RAD

    fwd = (np.outer(np.cos(angles_fwd), u)
           + np.outer(np.sin(angles_fwd), v))  # (N, 3)
    rev = (np.outer(np.cos(angles_rev), u)
           + np.outer(np.sin(angles_rev), v))
    return fwd, rev


# ── Simulation builder ────────────────────────────────────────────────────────


def build_cg_simulation(design: Design) -> CGSimState:
    """
    Build a CGSimState from the active design.

    Control points are placed at straight-geometry axis positions.
    Loop/skip modifications from Helix.loop_skips are encoded directly
    into backbone bond rest lengths, creating genuine strain in modified
    segments when the simulation starts.

    Parameters
    ----------
    design : Design (topological layer) — provides helix geometry and
             strand topology.  Deformations field is ignored; the CG
             model always starts from straight axis positions so that
             loop/skip strain can drive convergence.
    """
    # Build a helix lookup for fast access.
    helix_map = {h.id: h for h in design.helices}

    # ── Particle array ────────────────────────────────────────────────────────
    index_map:  Dict[Tuple[str, int], int] = {}
    particles:  List[Tuple[str, int]] = []
    pos_list:   list[np.ndarray] = []
    fwd_norm_list: list[np.ndarray] = []
    rev_norm_list: list[np.ndarray] = []

    for h in design.helices:
        fwd_norms, rev_norms = _normals_for_helix(h)
        for k in range(h.length_bp):
            key = (h.id, k)
            idx = len(particles)
            index_map[key] = idx
            particles.append(key)
            pos_list.append(_axis_position(h, k))
            fwd_norm_list.append(fwd_norms[k])
            rev_norm_list.append(rev_norms[k])

    n = len(particles)
    if n == 0:
        empty2 = np.empty((0, 2), dtype=np.int32)
        empty1 = np.empty(0, dtype=np.float64)
        empty3 = np.empty((0, 3), dtype=np.float64)
        return CGSimState(
            positions=empty3.copy(),
            backbone_ij=empty2, backbone_rest=empty1,
            crossover_ij=empty2, crossover_rest=empty1,
            bending_ij=empty2,  bending_rest=empty1,
            index_map=index_map, particles=particles,
            fwd_normals=empty3.copy(), rev_normals=empty3.copy(),
        )

    positions  = np.array(pos_list,      dtype=np.float64)   # (N, 3)
    fwd_normals = np.array(fwd_norm_list, dtype=np.float64)  # (N, 3)
    rev_normals = np.array(rev_norm_list, dtype=np.float64)

    # ── Loop/skip maps (helix_id → {bp_index: delta}) ─────────────────────────
    ls_map: dict[str, dict[int, int]] = {}
    for h in design.helices:
        if h.loop_skips:
            ls_map[h.id] = {ls.bp_index: ls.delta for ls in h.loop_skips}

    # ── Backbone and bending bonds ─────────────────────────────────────────────
    backbone_pairs:  list[tuple[int, int, float]] = []
    bending_pairs:   list[tuple[int, int, float]] = []
    backbone_set:    set[tuple[int, int]] = set()

    for h in design.helices:
        ls = ls_map.get(h.id, {})
        for k in range(h.length_bp - 1):
            ia = index_map[(h.id, k)]
            ib = index_map[(h.id, k + 1)]
            delta = ls.get(k, 0)
            rest = max(0.0, (1 + delta) * BDNA_RISE_PER_BP)
            pair = (min(ia, ib), max(ia, ib))
            backbone_set.add(pair)
            backbone_pairs.append((ia, ib, rest))

        # Bending: 2nd-neighbour within helix.
        for k in range(h.length_bp - 2):
            ia = index_map[(h.id, k)]
            ib = index_map[(h.id, k + 2)]
            rest = float(np.linalg.norm(positions[ib] - positions[ia]))
            bending_pairs.append((ia, ib, rest))

    # ── Crossover bonds (detected from strand domain junctions) ───────────────
    # Walk each strand's domain list in 5'→3' order.  Whenever two consecutive
    # domains are on different helices, add an inter-helix bond between the 3'
    # bp of the first domain and the 5' bp of the second domain.
    crossover_pairs: list[tuple[int, int, float]] = []
    crossover_set:   set[tuple[int, int]] = set()

    for strand in design.strands:
        domains = strand.domains
        for di in range(len(domains) - 1):
            dom_a = domains[di]
            dom_b = domains[di + 1]
            if dom_a.helix_id == dom_b.helix_id:
                continue  # same helix — not a crossover
            # 3' end of dom_a (= dom_a.end_bp) and 5' end of dom_b (= dom_b.start_bp)
            bp_a = dom_a.end_bp
            bp_b = dom_b.start_bp
            key_a = (dom_a.helix_id, bp_a)
            key_b = (dom_b.helix_id, bp_b)
            ia = index_map.get(key_a)
            ib = index_map.get(key_b)
            if ia is None or ib is None:
                continue
            pair = (min(ia, ib), max(ia, ib))
            if pair in crossover_set or pair in backbone_set:
                continue
            crossover_set.add(pair)
            # Rest length = straight-geometry axis-to-axis distance at this junction.
            rest = float(np.linalg.norm(positions[ib] - positions[ia]))
            crossover_pairs.append((ia, ib, rest))

    def _to_arrays(pairs):
        if pairs:
            ij   = np.array([(a, b) for a, b, _ in pairs], dtype=np.int32)
            rest = np.array([r       for _, _, r in pairs], dtype=np.float64)
        else:
            ij   = np.empty((0, 2), dtype=np.int32)
            rest = np.empty(0,      dtype=np.float64)
        return ij, rest

    backbone_ij,  backbone_rest  = _to_arrays(backbone_pairs)
    crossover_ij, crossover_rest = _to_arrays(crossover_pairs)
    bending_ij,   bending_rest   = _to_arrays(bending_pairs)

    return CGSimState(
        positions=positions,
        backbone_ij=backbone_ij,   backbone_rest=backbone_rest,
        crossover_ij=crossover_ij, crossover_rest=crossover_rest,
        bending_ij=bending_ij,     bending_rest=bending_rest,
        index_map=index_map, particles=particles,
        fwd_normals=fwd_normals,   rev_normals=rev_normals,
    )


# ── XPBD step ─────────────────────────────────────────────────────────────────


def cg_xpbd_step(sim: CGSimState, n_substeps: int = 10) -> None:
    """
    Perform one CG-XPBD update (n_substeps Jacobi iterations).

    Backbone and bending bonds use sim.backbone_stiffness / bending_stiffness.
    Crossover bonds use backbone_stiffness × crossover_weight so they dominate
    constraint resolution and transmit loop/skip strain across the bundle.

    Modifies sim.positions in-place.  Increments sim.step by one.
    """
    pos = sim.positions
    n   = len(pos)

    cxo_stiffness = sim.backbone_stiffness * sim.crossover_weight

    for _ in range(n_substeps):

        # ── Thermal noise ──────────────────────────────────────────────────────
        if sim.noise_amplitude > 0.0 and n > 0:
            pos += sim.noise_amplitude * sim.rng.standard_normal((n, 3))

        # ── Backbone bonds ─────────────────────────────────────────────────────
        if len(sim.backbone_ij) > 0 and sim.backbone_stiffness > 0.0:
            ai   = sim.backbone_ij[:, 0]
            bi   = sim.backbone_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            v    = dist > 1e-12
            fac  = np.zeros(len(sim.backbone_ij))
            fac[v] = sim.backbone_stiffness * 0.5 * (dist[v] - sim.backbone_rest[v]) / dist[v]
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── Crossover bonds (high weight) ──────────────────────────────────────
        if len(sim.crossover_ij) > 0 and cxo_stiffness > 0.0:
            ai   = sim.crossover_ij[:, 0]
            bi   = sim.crossover_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            v    = dist > 1e-12
            fac  = np.zeros(len(sim.crossover_ij))
            fac[v] = cxo_stiffness * 0.5 * (dist[v] - sim.crossover_rest[v]) / dist[v]
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── Bending bonds ──────────────────────────────────────────────────────
        if len(sim.bending_ij) > 0 and sim.bending_stiffness > 0.0:
            ai   = sim.bending_ij[:, 0]
            bi   = sim.bending_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            v    = dist > 1e-12
            fac  = np.zeros(len(sim.bending_ij))
            fac[v] = sim.bending_stiffness * 0.5 * (dist[v] - sim.bending_rest[v]) / dist[v]
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

    sim.step += 1


# ── Position expansion ────────────────────────────────────────────────────────


def _reorthogonalise(normals: np.ndarray, tangents: np.ndarray) -> np.ndarray:
    """
    Gram-Schmidt: remove the tangent component from each normal, renormalise.

    normals  : (N, 3) original unit normals
    tangents : (N, 3) current local axis tangents
    Returns  : (N, 3) normals perpendicular to tangents, unit length.
    """
    dot  = (normals * tangents).sum(axis=1, keepdims=True)  # (N, 1)
    proj = normals - dot * tangents
    lengths = np.linalg.norm(proj, axis=1, keepdims=True)
    # Guard against degenerate cases (tangent parallel to original normal).
    safe = lengths[:, 0] > 1e-10
    proj[safe]  = proj[safe] / lengths[safe]
    proj[~safe] = normals[~safe]  # fallback: keep original
    return proj


def cg_positions_to_updates(sim: CGSimState) -> list[dict]:
    """
    Expand current CG axis positions to per-nucleotide backbone positions.

    For each control point (helix_id, bp_index) at position p:
      1. Compute local tangent from adjacent CPs (central difference).
      2. Gram-Schmidt: re-orthogonalise original fwd/rev normals against tangent.
      3. FORWARD bead:  p + HELIX_RADIUS × fwd_normal
         REVERSE bead:  p + HELIX_RADIUS × rev_normal

    Returns list of {"helix_id", "bp_index", "direction", "backbone_position"}
    matching the format used by GET /api/design/geometry.
    """
    n   = len(sim.positions)
    pos = sim.positions

    # ── Compute local tangents (central difference, forward/backward at ends) ──
    tangents = np.empty_like(pos)
    if n >= 2:
        # Interior: central difference.
        tangents[1:-1] = pos[2:] - pos[:-2]
        # Endpoints: one-sided.
        tangents[0]    = pos[1]  - pos[0]
        tangents[-1]   = pos[-1] - pos[-2]
    elif n == 1:
        # Degenerate: single point, use Z as fallback tangent.
        tangents[0] = np.array([0.0, 0.0, 1.0])

    lengths = np.linalg.norm(tangents, axis=1, keepdims=True)
    safe = lengths[:, 0] > 1e-12
    tangents[safe]  = tangents[safe] / lengths[safe]
    tangents[~safe] = np.array([0.0, 0.0, 1.0])

    # ── But tangents must be per-helix — adjacent helices share index space ───
    # The tangent computation above mixes CPs from different helices because
    # particles are ordered helix-by-helix.  Fix: compute tangents only within
    # each helix's CP range using boundary awareness.
    #
    # We detect helix boundaries by grouping consecutive particles with the
    # same helix_id and recomputing their tangents independently.
    helix_id_seq = [p[0] for p in sim.particles]
    if n > 1:
        # Mark positions where the helix changes.
        for i in range(1, n):
            if helix_id_seq[i] != helix_id_seq[i - 1]:
                # i is the first CP of a new helix; i-1 is the last of the prev.
                # Fix the tangents at these boundaries.
                tangents[i - 1] = (pos[i - 1] - pos[i - 2]
                                   if i >= 2 and helix_id_seq[i - 2] == helix_id_seq[i - 1]
                                   else tangents[i - 1])
                tangents[i]     = (pos[i + 1] - pos[i]
                                   if i + 1 < n and helix_id_seq[i + 1] == helix_id_seq[i]
                                   else tangents[i])
                # Renormalise fixed entries.
                for idx in (i - 1, i):
                    norm = np.linalg.norm(tangents[idx])
                    if norm > 1e-12:
                        tangents[idx] /= norm

    # ── Re-orthogonalise normals against current tangents ─────────────────────
    fwd = _reorthogonalise(sim.fwd_normals, tangents)
    rev = _reorthogonalise(sim.rev_normals, tangents)

    # ── Emit per-nucleotide position updates ──────────────────────────────────
    result = []
    for idx, (helix_id, bp_index) in enumerate(sim.particles):
        fwd_pos = pos[idx] + HELIX_RADIUS * fwd[idx]
        rev_pos = pos[idx] + HELIX_RADIUS * rev[idx]
        result.append({
            "helix_id": helix_id,
            "bp_index": bp_index,
            "direction": "FORWARD",
            "backbone_position": fwd_pos.tolist(),
        })
        result.append({
            "helix_id": helix_id,
            "bp_index": bp_index,
            "direction": "REVERSE",
            "backbone_position": rev_pos.tolist(),
        })
    return result


# ── Diagnostics ───────────────────────────────────────────────────────────────


def cg_sim_energy(sim: CGSimState) -> float:
    """Total squared constraint violation energy."""
    pos = sim.positions
    energy = 0.0
    for ij, rest in [
        (sim.backbone_ij,  sim.backbone_rest),
        (sim.crossover_ij, sim.crossover_rest),
        (sim.bending_ij,   sim.bending_rest),
    ]:
        if len(ij) > 0:
            dist = np.linalg.norm(pos[ij[:, 1]] - pos[ij[:, 0]], axis=1)
            energy += float(np.sum((dist - rest) ** 2))
    return energy
