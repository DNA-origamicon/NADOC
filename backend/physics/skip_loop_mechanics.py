"""
Physical layer — skip/loop mechanics translation.

Translates Helix.loop_skips (topological layer) into fast-mode XPBD constraint
parameters (physical layer).  This is the scientifically critical layer that
makes skip-induced bending/twisting emerge from the constraint solver.

Physical model
──────────────
Each LoopSkip on a helix modifies the preferred inter-segment twist angle:
  delta = -1 (skip):  removes one bp worth of twist → preferred twist decreases
                       by SKIP_TWIST_DEFICIT_DEG = -34.3° per skip.
  delta = +1 (loop):  adds one bp worth of twist → preferred twist increases
                       by +34.3° per loop.

Skips reduce the effective arc length on that helix, which (when combined with
backbone distance constraints that maintain inter-segment spacing) produces a
net compression force on the skip side → bundle bends toward the skip side.

Loop insertions create a flexible joint between the two flanking segments with
ssDNA bending stiffness (ALPHA_BEND_SSDNA ≫ ALPHA_BEND_DSDNA).

Data source
───────────
All loop/skip information is read from Helix.loop_skips: List[LoopSkip].
This is the canonical storage location (Phase 7 topological layer).
Domain objects do NOT carry skip_positions or loop_positions fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from backend.core.constants import (
    ALPHA_BEND_SSDNA,
    BDNA_TWIST_PER_BP_DEG,
    FAST_SEGMENT_BP,
    SKIP_TWIST_DEFICIT_DEG,
    SSDNA_RISE_PER_BASE_NM,
)
from backend.core.models import Helix


@dataclass(frozen=True)
class LoopJointSpec:
    """
    Specifies a flexible loop-joint particle to be inserted between two
    adjacent helix segments.

    The joint sits between segment[seg_before_idx] and segment[seg_before_idx+1].
    The joint particle has ssDNA bending stiffness (large alpha = very flexible).
    """
    helix_id: str
    seg_before_idx: int    # joint between segment[i] and segment[i+1]
    loop_bp_count: int     # sum of positive delta values in this segment's bp range
    alpha_bend: float      # XPBD compliance for bending (ALPHA_BEND_SSDNA)
    rest_length_nm: float  # preferred distance to flanking segments (n_bases × 0.59 nm)


def compute_segment_bp_ranges(helix: Helix) -> List[Tuple[int, int]]:
    """
    Return list of (bp_start, bp_end_exclusive) for each FAST_SEGMENT_BP-sized
    segment of this helix.

    Segments are aligned to helix.bp_start.  The last segment may be shorter
    than FAST_SEGMENT_BP if helix.length_bp is not an exact multiple.

    Note: uses helix.bp_start as the first segment boundary (matches the
    global bp index convention used by LoopSkip.bp_index).
    """
    ranges: List[Tuple[int, int]] = []
    bp = helix.bp_start
    end = helix.bp_start + helix.length_bp
    while bp < end:
        bp_next = min(bp + FAST_SEGMENT_BP, end)
        ranges.append((bp, bp_next))
        bp = bp_next
    return ranges


def compute_segment_twist_deficit(
    helix: Helix,
    seg_bp_start: int,
    seg_bp_end: int,
) -> float:
    """
    Return the cumulative twist modification (degrees) for a segment due to
    skips and loops within [seg_bp_start, seg_bp_end).

    Each skip (delta=-1) contributes SKIP_TWIST_DEFICIT_DEG = -34.3°.
    Each loop (delta=+1) contributes +34.3° (one extra bp of twist).

    Uses helix.twist_per_bp_rad to determine the sign convention, but
    the magnitude is always BDNA_TWIST_PER_BP_DEG per modification.
    """
    deficit = 0.0
    for ls in helix.loop_skips:
        if seg_bp_start <= ls.bp_index < seg_bp_end:
            # skip (delta=-1) → deficit = -SKIP_TWIST_DEFICIT_DEG × (-1 × -1) ... use -delta:
            # -delta × SKIP_TWIST_DEFICIT_DEG where SKIP_TWIST_DEFICIT_DEG = -34.3:
            #   skip (delta=-1): -(-1) × (-34.3) = 1 × (-34.3) = -34.3° ✓
            #   loop (delta=+1): -(+1) × (-34.3) = -1 × (-34.3) = +34.3° ✓
            deficit += -ls.delta * SKIP_TWIST_DEFICIT_DEG
    return deficit


def compute_preferred_segment_twist_rad(
    helix: Helix,
    seg_bp_start: int,
    seg_bp_end: int,
) -> float:
    """
    Return the preferred inter-segment dihedral angle (radians) for this segment.

    = (segment_bp_count × helix.twist_per_bp_rad) + twist_deficit_rad

    The helix.twist_per_bp_rad handles both HC (34.3°/bp) and SQ (33.75°/bp)
    lattice types automatically — no lattice_type check needed here.
    """
    segment_bp_count = seg_bp_end - seg_bp_start
    nominal_twist_rad = segment_bp_count * helix.twist_per_bp_rad
    deficit_rad = math.radians(compute_segment_twist_deficit(helix, seg_bp_start, seg_bp_end))
    return nominal_twist_rad + deficit_rad


def compute_loop_joints(
    helix: Helix,
    seg_ranges: List[Tuple[int, int]],
) -> List[LoopJointSpec]:
    """
    Return LoopJointSpec for every segment that contains at least one loop
    insertion (delta > 0).

    The joint particle is placed between segment[i] and segment[i+1], where
    segment[i] is the segment containing the loop.  If a helix has loops in
    multiple segments, each generates a separate LoopJointSpec.

    Skips (delta < 0) produce no joint — they only modify the twist deficit.

    The loop joint rest length = total_loop_bases × SSDNA_RISE_PER_BASE_NM.
    """
    joints: List[LoopJointSpec] = []
    for seg_idx, (bp_s, bp_e) in enumerate(seg_ranges):
        loop_count = sum(
            ls.delta
            for ls in helix.loop_skips
            if bp_s <= ls.bp_index < bp_e and ls.delta > 0
        )
        if loop_count > 0:
            joints.append(LoopJointSpec(
                helix_id=helix.id,
                seg_before_idx=seg_idx,
                loop_bp_count=loop_count,
                alpha_bend=ALPHA_BEND_SSDNA,
                rest_length_nm=loop_count * SSDNA_RISE_PER_BASE_NM,
            ))
    return joints
