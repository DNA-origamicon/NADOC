"""CanDo-style "jointed cylinder" geometry for the FEM-predicted shape.

CanDo renders a solved structure as a set of smooth tubes — one per helix, each a
chain of short cylinders (radius = duplex radius) threaded through the per-bp axis
positions — plus thin connector cylinders at the crossovers (the "joints").  This
module reproduces that representation from a CanDo job's cached display positions
(the ``deformed_positions`` list, already rigid-body aligned to the displayed frame),
so the in-app "CanDo style output" toggle draws exactly the familiar CanDo look.

Purely geometric / Physical-layer — display-only, never mutates topology.

The tubes thread through the FEM AXIS nodes (the true helix centre, one per duplex-core
bp) — NOT the backbone midpoint, which precesses around the axis along the helical groove
and makes the tube wobble.  Because the axis nodes exist only for the meshed duplex core,
ssDNA ends are naturally excluded (no grey fall-back).  The aligned axis nodes are cached
with the job (``display.json`` ``axis``); for older jobs cached without them,
:func:`axis_from_backbones` reconstructs a (wobblier) axis from the backbone midpoints,
restricted to the RMSF/duplex-core bp so ssDNA is still excluded.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.models import Design
from backend.physics.fem_solver import HELIX_DIAMETER

# Cylinder radii (nm), matching the CanDo BILD: helix tube = duplex radius (11.25 Å),
# crossover joint connector = thin (2.0 Å).
TUBE_RADIUS_NM = HELIX_DIAMETER / 2.0   # 1.125 nm
JOINT_RADIUS_NM = 0.20                   # nm


def axis_from_backbones(
    display_positions: List[dict],
    rmsf: Optional[List[dict]] = None,
) -> List[dict]:
    """Fallback axis for jobs cached WITHOUT the solver's ``axis`` list: reconstruct each
    duplex bp's centre as the midpoint of its two strand backbones (copy 0).  Restricted
    to bp that carry an RMSF node (the meshed duplex core) so ssDNA ends are excluded —
    at the cost of the backbone-groove wobble the cached axis avoids.  Returns the same
    ``[{helix_id, bp_index, position}]`` shape as the solver's axis."""
    rmsf_bp = {(r["helix_id"], r["bp_index"]) for r in rmsf or []}
    fwd: Dict[Tuple[str, int], List[float]] = {}
    rev: Dict[Tuple[str, int], List[float]] = {}
    for p in display_positions:
        if p.get("copy", 0) != 0:
            continue
        key = (p["helix_id"], p["bp_index"])
        if rmsf_bp and key not in rmsf_bp:      # keep only meshed duplex core (drop ssDNA)
            continue
        pos = p.get("backbone_position")
        if pos is None:
            continue
        if p.get("direction") == "FORWARD":
            fwd[key] = pos
        elif p.get("direction") == "REVERSE":
            rev[key] = pos
    out: List[dict] = []
    for key, a in fwd.items():
        b = rev.get(key)
        if b is None:
            continue
        out.append({"helix_id": key[0], "bp_index": key[1],
                    "position": [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0]})
    return out


def compute_cylinders(
    design: Design,
    axis_nodes: List[dict],
    rmsf: Optional[List[dict]] = None,
) -> dict:
    """Build the CanDo-style cylinder representation of a job's predicted shape.

    ``axis_nodes`` is the solver's per-bp helix-CENTRE list ``[{helix_id, bp_index,
    position}]`` (from ``display.json`` ``axis``, or :func:`axis_from_backbones`).  Only
    duplex-core bp appear → no ssDNA, no grey fall-back.

    Returns::

        {"tube_radius_nm": 1.125, "joint_radius_nm": 0.2,
         "helices": [{"helix_id": str,
                      "points": [[x,y,z], ...],   # per-helix axis tube, bp-ordered
                      "rmsf":   [float|None, ...]}],   # per-node RMSF (nm), parallel to points
         "joints":  [[[x,y,z],[x,y,z]], ...],          # crossover connectors
         "joint_rmsf": [float|None, ...],              # per-joint RMSF (mean of both ends)
         "has_rmsf": bool, "rmsf_min": float, "rmsf_p95": float, "rmsf_max": float,
         "n_helices": int, "n_joints": int}

    Positions are in nm in the displayed (aligned) frame — the same frame the deform
    overlay uses — so the tubes drop straight onto the model without a jump.

    When ``rmsf`` (the job's per-node NMA RMSF, ``[{helix_id, bp_index, rmsf_nm}]``) is
    given, every cylinder segment is tagged with the RMSF at its bp so the overlay can
    colour it with CanDo's jet heat map — bluest at the ``rmsf_min`` (0th percentile),
    reddest at the ``rmsf_p95`` (95th percentile, clamped above), exactly as CanDo's
    ``structure_NMA_RMSF.bild`` does.
    """
    axis: Dict[Tuple[str, int], List[float]] = {
        (n["helix_id"], n["bp_index"]): n["position"] for n in axis_nodes
    }
    rmsf_by_node: Dict[Tuple[str, int], float] = {}
    for r in rmsf or []:
        v = r.get("rmsf_nm")
        if v is not None:
            rmsf_by_node[(r["helix_id"], r["bp_index"])] = float(v)

    helices: List[dict] = []
    for helix in design.helices:
        keyed = sorted(
            (bp, axis[(hid, bp)]) for (hid, bp) in axis if hid == helix.id
        )  # sort by bp index → ordered along the helix
        if len(keyed) >= 2:
            helices.append({
                "helix_id": helix.id,
                "points": [p for _, p in keyed],
                "rmsf": [rmsf_by_node.get((helix.id, bp)) for bp, _ in keyed],
            })

    joints: List[list] = []
    joint_rmsf: List[Optional[float]] = []
    for xo in design.crossovers:
        a = axis.get((xo.half_a.helix_id, xo.half_a.index))
        b = axis.get((xo.half_b.helix_id, xo.half_b.index))
        if a is not None and b is not None:
            joints.append([a, b])
            ra = rmsf_by_node.get((xo.half_a.helix_id, xo.half_a.index))
            rb = rmsf_by_node.get((xo.half_b.helix_id, xo.half_b.index))
            both = [x for x in (ra, rb) if x is not None]
            joint_rmsf.append(sum(both) / len(both) if both else None)

    vals = [v for v in rmsf_by_node.values()]
    has_rmsf = len(vals) > 0
    rmsf_min = float(min(vals)) if has_rmsf else 0.0
    rmsf_max = float(max(vals)) if has_rmsf else 0.0
    # 95th percentile → reddest, matching CanDo's HeatMapRange4RMSF (clamp above p95).
    rmsf_p95 = float(np.percentile(vals, 95)) if has_rmsf else 0.0

    return {
        "tube_radius_nm": TUBE_RADIUS_NM,
        "joint_radius_nm": JOINT_RADIUS_NM,
        "helices": helices,
        "joints": joints,
        "joint_rmsf": joint_rmsf,
        "has_rmsf": has_rmsf,
        "rmsf_min": rmsf_min,
        "rmsf_p95": rmsf_p95,
        "rmsf_max": rmsf_max,
        "n_helices": len(helices),
        "n_joints": len(joints),
    }
