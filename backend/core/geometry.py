"""
Geometric layer — nucleotide position calculations.

This module derives 3D nucleotide positions and orientation frames from the
topological Helix model.  It operates purely on Helix objects and returns
NucleotidePosition records; it never modifies Design or any topology model.

Coordinate convention
─────────────────────
The helix axis runs from helix.axis_start to helix.axis_end.

FORWARD strand backbone at bp i:
    backbone = axis_point + HELIX_RADIUS × radial(twist_angle)

REVERSE strand backbone at bp i:
    backbone = axis_point + HELIX_RADIUS × radial(twist_angle + groove_offset)

where twist_angle = phase_offset + i × BDNA_TWIST_PER_BP_RAD.

Minor groove convention
───────────────────────
The groove_offset is chosen so that the minor groove angle is 150° measured
CLOCKWISE from the scaffold backbone to the staple backbone (viewing the
cross-section with the axis pointing away from the viewer):

  FORWARD helix  (scaffold = fwd strand, staple = rev strand):
      groove_offset = −BDNA_MINOR_GROOVE_ANGLE_RAD   (CW 150° from fwd → rev)

  REVERSE helix  (scaffold = rev strand, staple = fwd strand):
      groove_offset = +BDNA_MINOR_GROOVE_ANGLE_RAD   (CW 150° from rev → fwd,
                                                       i.e. rev = fwd + 150° CCW)

  Unknown direction (helix.direction is None):
      groove_offset = +BDNA_MINOR_GROOVE_ANGLE_RAD   (same as REVERSE fallback)

Base normals are cross-strand vectors, NOT inward radials:
    FORWARD base_normal = normalize(REVERSE_backbone − FORWARD_backbone)
    REVERSE base_normal = −FORWARD_base_normal

Base bead is displaced from the backbone along the base_normal:
    base_position = backbone + BASE_DISPLACEMENT × base_normal

B-DNA parameters (all from constants.py, never hardcoded here):
  rise              = 0.334 nm/bp
  twist             = 34.3 deg/bp
  helix radius      = 1.0 nm
  minor groove      = 150° (clockwise scaffold→staple)
  base displacement = 0.3 nm
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

import numpy as np

from backend.core.constants import (
    BASE_DISPLACEMENT,
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.models import Direction, Helix


@dataclass(frozen=True)
class NucleotidePosition:
    """
    Position and orientation frame for a single nucleotide.

    Attributes
    ----------
    helix_id : str
    bp_index : int  (0-based)
    direction : Direction
    position : np.ndarray shape (3,)
        Backbone (sugar-phosphate) bead, in nm, world frame.
        Sits at HELIX_RADIUS from the helix axis.
    base_position : np.ndarray shape (3,)
        Base bead, in nm.  Displaced from backbone by BASE_DISPLACEMENT
        along base_normal (the cross-strand direction).
    base_normal : np.ndarray shape (3,)
        Unit vector pointing from this backbone toward the paired strand's
        backbone at the same bp index (cross-strand, NOT inward radial).
        FORWARD: normalize(REVERSE_backbone − FORWARD_backbone).
        REVERSE: −FORWARD_base_normal.
    axis_tangent : np.ndarray shape (3,)
        Unit vector along the helix axis (axis_start → axis_end).
    """
    helix_id: str
    bp_index: int
    direction: Direction
    position: np.ndarray       # backbone bead
    base_position: np.ndarray  # base bead
    base_normal: np.ndarray    # cross-strand unit vector
    axis_tangent: np.ndarray

    def __getitem__(self, key: str):
        """Dict-style access for compatibility with xpbd.py's build_simulation."""
        if key == "helix_id":
            return self.helix_id
        if key == "bp_index":
            return self.bp_index
        if key == "direction":
            return self.direction
        if key == "backbone_position":
            return self.position
        raise KeyError(key)


def _frame_from_helix_axis(axis_vec: np.ndarray) -> np.ndarray:
    """
    Right-handed orthonormal frame whose z-column aligns with axis_vec.
    Returns 3×3 matrix with columns [x_hat, y_hat, z_hat].
    """
    z_hat = axis_vec / np.linalg.norm(axis_vec)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(z_hat, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    x_hat = np.cross(ref, z_hat)
    x_hat /= np.linalg.norm(x_hat)
    y_hat = np.cross(z_hat, x_hat)
    return np.column_stack([x_hat, y_hat, z_hat])


def nucleotide_positions(helix: Helix) -> List[NucleotidePosition]:
    """
    Compute 3D positions for every nucleotide on both strands of *helix*.

    Returns 2 × effective_nucleotide_count NucleotidePosition objects,
    ordered by bp_index (bp_start … bp_start+length_bp-1), FORWARD first at each index.

    bp_index values are *global* — the same physical axial position maps to the
    same bp_index regardless of which helix it is on.  The invariant is:
        axis_point = axis_start + (global_bp - bp_start) * BDNA_RISE_PER_BP * axis_hat

    Loop/skip handling (Dietz et al. 2009):
    - Skip (delta=-1): the bp is absent — no NucleotidePosition emitted for
      that index. The axial position advances by BDNA_RISE_PER_BP as normal
      (the "gap" is bridged by a longer backbone bond in the strand graph).
    - Loop (delta=+1): two nucleotides share that bp_index, placed at
      ±0.5 × BDNA_RISE_PER_BP offset along the axis from the nominal
      axis_point. Both have the same twist angle (the extra base bulges
      out; we don't attempt to re-optimize local geometry here).
    The bp_index field on the returned NucleotidePosition always equals the
    global bp index; loop positions use the same bp_index as their companion
    to allow the renderer to pair them correctly.
    LoopSkip.bp_index values stored on the helix are also global.
    """
    start    = helix.axis_start.to_array()
    end      = helix.axis_end.to_array()
    axis_vec = end - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")

    axis_hat = axis_vec / length
    frame    = _frame_from_helix_axis(axis_hat)
    twist    = helix.twist_per_bp_rad  # may differ from BDNA default for square lattice

    # Build a dict of global_bp_index → total delta for fast lookup.
    # Multiple LoopSkip entries at the same bp_index have their deltas summed
    # (e.g., two delta=-1 entries at bp=0 → ls_map[0]=-2, emitting no nucleotide
    # at that position and skipping the column entirely).
    ls_map: dict[int, int] = {}
    for ls in helix.loop_skips:
        ls_map[ls.bp_index] = ls_map.get(ls.bp_index, 0) + ls.delta

    # +150° from scaffold to staple (cadnano CW = world CCW = math +): forward helix, +150°; reverse helix, −150°.
    minor_groove_rad = (BDNA_MINOR_GROOVE_ANGLE_RAD if helix.direction == Direction.FORWARD
                        else -BDNA_MINOR_GROOVE_ANGLE_RAD)

    results: List[NucleotidePosition] = []

    def _emit(axis_pt: np.ndarray, local_bp: int, global_bp: int) -> None:
        # local_bp drives the twist angle (geometry); global_bp is the bp_index label.
        fwd_angle = helix.phase_offset + local_bp * twist
        rev_angle = fwd_angle + minor_groove_rad

        fwd_radial = (math.cos(fwd_angle) * frame[:, 0]
                      + math.sin(fwd_angle) * frame[:, 1])
        rev_radial = (math.cos(rev_angle) * frame[:, 0]
                      + math.sin(rev_angle) * frame[:, 1])

        fwd_backbone = axis_pt + HELIX_RADIUS * fwd_radial
        rev_backbone = axis_pt + HELIX_RADIUS * rev_radial

        base_pair_vec = rev_backbone - fwd_backbone
        base_pair_hat = base_pair_vec / np.linalg.norm(base_pair_vec)

        fwd_base = fwd_backbone + BASE_DISPLACEMENT * base_pair_hat
        rev_base = rev_backbone - BASE_DISPLACEMENT * base_pair_hat

        results.append(NucleotidePosition(
            helix_id=helix.id,
            bp_index=global_bp,
            direction=Direction.FORWARD,
            position=fwd_backbone,
            base_position=fwd_base,
            base_normal=base_pair_hat,
            axis_tangent=axis_hat,
        ))
        results.append(NucleotidePosition(
            helix_id=helix.id,
            bp_index=global_bp,
            direction=Direction.REVERSE,
            position=rev_backbone,
            base_position=rev_base,
            base_normal=-base_pair_hat,
            axis_tangent=axis_hat,
        ))

    for local_i in range(helix.length_bp):
        global_bp = local_i + helix.bp_start
        delta = ls_map.get(global_bp, 0)
        axis_point = start + axis_hat * (local_i * BDNA_RISE_PER_BP)

        if delta <= -1:
            # Skip (any negative delta): omit this bp entirely.
            # Axial position counter still advances — the gap is bridged by
            # a longer backbone bond in the strand graph topology.
            continue
        elif delta >= 1:
            # Loop (any positive delta): emit delta+1 nucleotides at this bp,
            # evenly spaced along the axis over (delta+1) × RISE intervals.
            n_copies = delta + 1
            for k in range(n_copies):
                offset = (k - (n_copies - 1) / 2.0) * BDNA_RISE_PER_BP
                _emit(axis_point + axis_hat * offset, local_i, global_bp)
        else:
            _emit(axis_point, local_i, global_bp)

    return results


# ── Vectorised position array API ──────────────────────────────────────────────

def nucleotide_positions_arrays(helix: Helix) -> dict:
    """
    Vectorised nucleotide position computation.

    Returns a dict of numpy arrays for all nucleotides on both strands of
    *helix*.  All arrays have length M = 2 × effective_bp_count.

    Layout
    ------
    Pairs are interleaved: index 2k is FORWARD at helix-local bp k,
    index 2k+1 is REVERSE at the same bp — matching nucleotide_positions().

    Keys
    ----
    helix_id       : str
    bp_indices     : (M,) int   — global bp indices
    local_bps      : (M,) int   — helix-local indices (0 = bp_start)
    directions     : (M,) int   — 0 = FORWARD, 1 = REVERSE
    positions      : (M, 3)     — backbone bead positions (nm)
    base_positions : (M, 3)     — base bead positions (nm)
    base_normals   : (M, 3)     — cross-strand unit vectors
    axis_tangents  : (M, 3)     — helix-axis tangent (uniform for straight helix)

    Falls back to nucleotide_positions() and converts when the helix has
    loop/skip modifications (rare; keeps loop/skip semantics correct).
    """
    start    = helix.axis_start.to_array()
    end_arr  = helix.axis_end.to_array()
    axis_vec = end_arr - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")
    axis_hat = axis_vec / length
    frame    = _frame_from_helix_axis(axis_hat)
    twist    = helix.twist_per_bp_rad

    if helix.loop_skips:
        # Rare slow path — fall back to the scalar loop and convert.
        return _nuc_arrays_from_list(helix.id, helix.bp_start,
                                     nucleotide_positions(helix), axis_hat)

    # ── Fast path: no loop/skips ─────────────────────────────────────────────
    N = helix.length_bp
    if N == 0:
        empty3 = np.empty((0, 3), dtype=np.float64)
        return {
            'helix_id': helix.id,
            'bp_indices': np.empty(0, dtype=np.intp),
            'local_bps':  np.empty(0, dtype=np.intp),
            'directions': np.empty(0, dtype=np.intp),
            'positions':     empty3.copy(), 'base_positions': empty3.copy(),
            'base_normals':  empty3.copy(), 'axis_tangents':  empty3.copy(),
        }

    local_bps  = np.arange(N, dtype=np.intp)           # (N,)
    global_bps = local_bps + helix.bp_start             # (N,)

    # Axis points for all bps: shape (N, 3)
    axis_pts = start + axis_hat * (local_bps.astype(float)[:, None] * BDNA_RISE_PER_BP)

    # Twist angles and trig: shape (N,)
    angles = helix.phase_offset + local_bps * twist
    cos_a  = np.cos(angles)
    sin_a  = np.sin(angles)
    fx     = frame[:, 0]   # (3,)
    fy     = frame[:, 1]   # (3,)

    # +150° from scaffold to staple (cadnano CW = world CCW = math +): forward helix, +150°; reverse helix, −150°.
    minor_groove_rad = (BDNA_MINOR_GROOVE_ANGLE_RAD if helix.direction == Direction.FORWARD
                        else -BDNA_MINOR_GROOVE_ANGLE_RAD)

    # Radial directions for forward and reverse strands: (N, 3)
    fwd_radials = cos_a[:, None] * fx + sin_a[:, None] * fy
    rev_angles  = angles + minor_groove_rad
    rev_radials = np.cos(rev_angles)[:, None] * fx + np.sin(rev_angles)[:, None] * fy

    # Backbone positions: (N, 3)
    fwd_bb = axis_pts + HELIX_RADIUS * fwd_radials
    rev_bb = axis_pts + HELIX_RADIUS * rev_radials

    # Base normals (cross-strand unit vectors): (N, 3)
    bp_vecs  = rev_bb - fwd_bb
    bp_hats  = bp_vecs / np.linalg.norm(bp_vecs, axis=1, keepdims=True)

    # Base positions: (N, 3)
    fwd_base = fwd_bb + BASE_DISPLACEMENT * bp_hats
    rev_base = rev_bb - BASE_DISPLACEMENT * bp_hats

    # Interleave fwd/rev → shape (2N, 3)
    # Order: fwd@bp0, rev@bp0, fwd@bp1, rev@bp1, …
    M = 2 * N
    positions      = np.empty((M, 3), dtype=np.float64)
    base_positions = np.empty((M, 3), dtype=np.float64)
    base_normals   = np.empty((M, 3), dtype=np.float64)

    positions[0::2]      = fwd_bb;    positions[1::2]      = rev_bb
    base_positions[0::2] = fwd_base;  base_positions[1::2] = rev_base
    base_normals[0::2]   = bp_hats;   base_normals[1::2]   = -bp_hats

    axis_tangents = np.broadcast_to(axis_hat, (M, 3)).copy()

    return {
        'helix_id':      helix.id,
        'bp_indices':    np.repeat(global_bps, 2),
        'local_bps':     np.repeat(local_bps, 2),
        'directions':    np.tile(np.array([0, 1], dtype=np.intp), N),
        'positions':     positions,
        'base_positions': base_positions,
        'base_normals':  base_normals,
        'axis_tangents': axis_tangents,
    }


def nucleotide_positions_arrays_extended(helix: Helix, lo_bp: int) -> dict:
    """Compute straight-geometry nucleotide positions for bp in [lo_bp, helix.bp_start - 1].

    This covers strand domains that extend *below* the physical helix span (e.g., a
    scaffold strand that crosses over to a negative bp to form a single-stranded loop).
    The axis formula is the same as nucleotide_positions_arrays() — the helix axis is
    simply extrapolated backward from axis_start.  Deformation does NOT apply here.

    Returns the same dict-of-arrays format as nucleotide_positions_arrays().
    Returns an empty dict if lo_bp >= helix.bp_start (nothing to compute).
    """
    if lo_bp >= helix.bp_start:
        empty3 = np.empty((0, 3), dtype=np.float64)
        return {
            'helix_id': helix.id,
            'bp_indices': np.empty(0, dtype=np.intp),
            'local_bps':  np.empty(0, dtype=np.intp),
            'directions': np.empty(0, dtype=np.intp),
            'positions':     empty3.copy(), 'base_positions': empty3.copy(),
            'base_normals':  empty3.copy(), 'axis_tangents':  empty3.copy(),
        }

    start    = helix.axis_start.to_array()
    end_arr  = helix.axis_end.to_array()
    axis_vec = end_arr - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")
    axis_hat = axis_vec / length
    frame    = _frame_from_helix_axis(axis_hat)
    twist    = helix.twist_per_bp_rad

    # local_bps are negative: lo_bp - bp_start to -1
    lo_local = lo_bp - helix.bp_start   # negative
    local_bps  = np.arange(lo_local, 0, dtype=np.intp)   # e.g., [-14, -13, ..., -1]
    global_bps = local_bps + helix.bp_start

    N = len(local_bps)
    axis_pts = start + axis_hat * (local_bps.astype(float)[:, None] * BDNA_RISE_PER_BP)

    minor_groove_rad = (BDNA_MINOR_GROOVE_ANGLE_RAD if helix.direction == Direction.FORWARD
                        else -BDNA_MINOR_GROOVE_ANGLE_RAD)

    angles = helix.phase_offset + local_bps * twist
    cos_a  = np.cos(angles)
    sin_a  = np.sin(angles)
    fx     = frame[:, 0]
    fy     = frame[:, 1]

    fwd_radials = cos_a[:, None] * fx + sin_a[:, None] * fy
    rev_angles  = angles + minor_groove_rad
    rev_radials = np.cos(rev_angles)[:, None] * fx + np.sin(rev_angles)[:, None] * fy

    fwd_bb = axis_pts + HELIX_RADIUS * fwd_radials
    rev_bb = axis_pts + HELIX_RADIUS * rev_radials

    bp_vecs  = rev_bb - fwd_bb
    bp_hats  = bp_vecs / np.linalg.norm(bp_vecs, axis=1, keepdims=True)

    fwd_base = fwd_bb + BASE_DISPLACEMENT * bp_hats
    rev_base = rev_bb - BASE_DISPLACEMENT * bp_hats

    M = 2 * N
    positions      = np.empty((M, 3), dtype=np.float64)
    base_positions = np.empty((M, 3), dtype=np.float64)
    base_normals   = np.empty((M, 3), dtype=np.float64)

    positions[0::2]      = fwd_bb;    positions[1::2]      = rev_bb
    base_positions[0::2] = fwd_base;  base_positions[1::2] = rev_base
    base_normals[0::2]   = bp_hats;   base_normals[1::2]   = -bp_hats

    axis_tangents = np.broadcast_to(axis_hat, (M, 3)).copy()

    return {
        'helix_id':      helix.id,
        'bp_indices':    np.repeat(global_bps, 2),
        'local_bps':     np.repeat(local_bps, 2),
        'directions':    np.tile(np.array([0, 1], dtype=np.intp), N),
        'positions':     positions,
        'base_positions': base_positions,
        'base_normals':  base_normals,
        'axis_tangents': axis_tangents,
    }


def nucleotide_positions_arrays_extended_right(helix: Helix, hi_bp: int) -> dict:
    """Compute straight-geometry nucleotide positions for bp in [helix.bp_start + helix.length_bp, hi_bp].

    Symmetric to nucleotide_positions_arrays_extended() but for the high-bp side.
    Covers strand domains that extend *above* the physical helix span (e.g., a
    scaffold strand whose right end is extended to a right-side crossover position).
    The axis formula is identical — the helix axis is extrapolated forward from axis_end.
    Deformation does NOT apply here.

    Returns the same dict-of-arrays format as nucleotide_positions_arrays().
    Returns an empty dict if hi_bp < helix.bp_start + helix.length_bp (nothing to compute).
    """
    helix_hi = helix.bp_start + helix.length_bp   # first bp past the helix
    if hi_bp < helix_hi:
        empty3 = np.empty((0, 3), dtype=np.float64)
        return {
            'helix_id': helix.id,
            'bp_indices': np.empty(0, dtype=np.intp),
            'local_bps':  np.empty(0, dtype=np.intp),
            'directions': np.empty(0, dtype=np.intp),
            'positions':     empty3.copy(), 'base_positions': empty3.copy(),
            'base_normals':  empty3.copy(), 'axis_tangents':  empty3.copy(),
        }

    start    = helix.axis_start.to_array()
    end_arr  = helix.axis_end.to_array()
    axis_vec = end_arr - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")
    axis_hat = axis_vec / length
    frame    = _frame_from_helix_axis(axis_hat)
    twist    = helix.twist_per_bp_rad

    # local_bps are positive beyond the helix length: helix.length_bp to hi_local
    hi_local   = hi_bp - helix.bp_start + 1  # +1 so hi_bp is included
    local_bps  = np.arange(helix.length_bp, hi_local, dtype=np.intp)
    global_bps = local_bps + helix.bp_start

    N = len(local_bps)
    axis_pts = start + axis_hat * (local_bps.astype(float)[:, None] * BDNA_RISE_PER_BP)

    minor_groove_rad = (BDNA_MINOR_GROOVE_ANGLE_RAD if helix.direction == Direction.FORWARD
                        else -BDNA_MINOR_GROOVE_ANGLE_RAD)

    angles = helix.phase_offset + local_bps * twist
    cos_a  = np.cos(angles)
    sin_a  = np.sin(angles)
    fx     = frame[:, 0]
    fy     = frame[:, 1]

    fwd_radials = cos_a[:, None] * fx + sin_a[:, None] * fy
    rev_angles  = angles + minor_groove_rad
    rev_radials = np.cos(rev_angles)[:, None] * fx + np.sin(rev_angles)[:, None] * fy

    fwd_bb = axis_pts + HELIX_RADIUS * fwd_radials
    rev_bb = axis_pts + HELIX_RADIUS * rev_radials

    bp_vecs  = rev_bb - fwd_bb
    bp_hats  = bp_vecs / np.linalg.norm(bp_vecs, axis=1, keepdims=True)

    fwd_base = fwd_bb + BASE_DISPLACEMENT * bp_hats
    rev_base = rev_bb - BASE_DISPLACEMENT * bp_hats

    M = 2 * N
    positions      = np.empty((M, 3), dtype=np.float64)
    base_positions = np.empty((M, 3), dtype=np.float64)
    base_normals   = np.empty((M, 3), dtype=np.float64)

    positions[0::2]      = fwd_bb;    positions[1::2]      = rev_bb
    base_positions[0::2] = fwd_base;  base_positions[1::2] = rev_base
    base_normals[0::2]   = bp_hats;   base_normals[1::2]   = -bp_hats

    axis_tangents = np.broadcast_to(axis_hat, (M, 3)).copy()

    return {
        'helix_id':      helix.id,
        'bp_indices':    np.repeat(global_bps, 2),
        'local_bps':     np.repeat(local_bps, 2),
        'directions':    np.tile(np.array([0, 1], dtype=np.intp), N),
        'positions':     positions,
        'base_positions': base_positions,
        'base_normals':  base_normals,
        'axis_tangents': axis_tangents,
    }


def _nuc_arrays_from_list(
    helix_id: str,
    bp_start: int,
    nucs: List[NucleotidePosition],
    axis_hat: np.ndarray,
) -> dict:
    """Convert List[NucleotidePosition] to the nucleotide_positions_arrays dict format."""
    if not nucs:
        empty3 = np.empty((0, 3), dtype=np.float64)
        return {
            'helix_id': helix_id,
            'bp_indices': np.empty(0, dtype=np.intp),
            'local_bps':  np.empty(0, dtype=np.intp),
            'directions': np.empty(0, dtype=np.intp),
            'positions':     empty3.copy(), 'base_positions': empty3.copy(),
            'base_normals':  empty3.copy(), 'axis_tangents':  empty3.copy(),
        }
    bp_idx = np.array([n.bp_index for n in nucs], dtype=np.intp)
    return {
        'helix_id':      helix_id,
        'bp_indices':    bp_idx,
        'local_bps':     bp_idx - bp_start,
        'directions':    np.array(
            [0 if n.direction == Direction.FORWARD else 1 for n in nucs],
            dtype=np.intp,
        ),
        'positions':      np.array([n.position      for n in nucs], dtype=np.float64),
        'base_positions': np.array([n.base_position for n in nucs], dtype=np.float64),
        'base_normals':   np.array([n.base_normal   for n in nucs], dtype=np.float64),
        'axis_tangents':  np.array([n.axis_tangent  for n in nucs], dtype=np.float64),
    }


def helix_axis_point(helix: Helix, bp_index: int) -> np.ndarray:
    """Return the world-space position of the helix axis at *bp_index*."""
    start    = helix.axis_start.to_array()
    end      = helix.axis_end.to_array()
    axis_vec = end - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")
    return start + (axis_vec / length) * ((bp_index - helix.bp_start) * BDNA_RISE_PER_BP)
