"""Per-nucleotide deviation of the CanDo-FEM-predicted shape from the design's
intended (displayed) geometry — the Phase-5 Item-3 deviation map + global RMSD.

The FEM display positions (``display.json``) are already rigid-body aligned (Kabsch)
onto the design's DISPLAYED geometry — ``deformed_nucleotide_positions`` = geometry
layer + the design's DeformationOps + cluster transforms — by
``fem_solver.deformed_positions``.  So the per-bead residual *after* that alignment is
the intrinsic shape mismatch: how far the loop/skip-realised FEM prediction lands from
where the design intends each base to sit.

  small deviation (green) → the realised loop/skips reproduce the drawn shape
  large deviation (red)   → they don't (e.g. a bend the loop/skips under-realise)

Global scalar RMSD = sqrt(mean(deviation²)) over the matched nucleotides.  This is the
oracle the Item-4 autorefine loop minimises by adjusting loop/skip placement.

Native target = the DISPLAYED geometry (not the straight ``nucleotide_positions``),
because the FEM positions were aligned to it; diffing against the straight layer would
just re-report the DeformationOp bend itself.  Everything here is Physical/display-layer
only — topology is never mutated (Three-Layer Law).
"""
from __future__ import annotations

import math
from typing import List, Optional

from backend.core.models import Design


def compute_deviation(design: Design, display_positions: List[dict]) -> dict:
    """Per-nucleotide deviation of ``display_positions`` (a cached CanDo display list:
    ``{helix_id, bp_index, direction, backbone_position}``) from the design's displayed
    geometry.

    Returns::

        {"positions": [{helix_id, bp_index, direction, backbone_position, deviation}, …],
         "rmsd_nm": float,            # sqrt(mean(dev²)) over matched nucleotides
         "min_deviation": float, "max_deviation": float, "mean_deviation": float,
         "n": int}                    # matched nucleotide count

    A display position with no matching (helix, bp, direction) in the design geometry
    (should not happen — the display list is built from the same nucleotides) gets
    deviation 0 and is excluded from the statistics.
    """
    from collections import Counter

    from backend.core.deformation import deformed_nucleotide_positions

    # Native (intended) positions keyed by (helix, bp, direction, COPY) so a loop
    # insertion's extra bases each match their own inserted base rather than collapsing
    # onto the last copy.  The copy index = appearance order within the key, the same
    # convention fem_solver.deformed_positions stamps onto the display positions.
    native: dict[tuple, tuple] = {}
    seen: Counter = Counter()
    for helix in design.helices:
        for nuc in deformed_nucleotide_positions(helix, design):
            # deformed_nucleotide_positions yields positions as a length-3 array-like
            # (np.ndarray), unlike the geometry layer's Vec3 — index rather than .x/.y/.z.
            pos = nuc.position
            k = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
            native[(*k, seen[k])] = (float(pos[0]), float(pos[1]), float(pos[2]))
            seen[k] += 1

    out: List[dict] = []
    sq_sum = 0.0
    matched = 0
    dev_min: Optional[float] = None
    dev_max: Optional[float] = None
    for p in display_positions:
        copy = p.get("copy", 0)
        key = (p["helix_id"], p["bp_index"], p["direction"], copy)
        nat = native.get(key)
        bb = p["backbone_position"]
        if nat is None:
            dev = 0.0
        else:
            dx, dy, dz = bb[0] - nat[0], bb[1] - nat[1], bb[2] - nat[2]
            dev = math.sqrt(dx * dx + dy * dy + dz * dz)
            sq_sum += dev * dev
            matched += 1
            dev_min = dev if dev_min is None else min(dev_min, dev)
            dev_max = dev if dev_max is None else max(dev_max, dev)
        entry = {
            "helix_id":          p["helix_id"],
            "bp_index":          p["bp_index"],
            "direction":         p["direction"],
            "copy":              copy,
            "backbone_position": bb,
            "deviation":         dev,
        }
        # Forward the wound slab normal/tangent (present on newer display caches) so the
        # deviation-map slabs follow the wound backbones like the deform/flex modes.
        for f in ("nx", "ny", "nz", "tx", "ty", "tz"):
            if f in p:
                entry[f] = p[f]
        out.append(entry)

    rmsd = math.sqrt(sq_sum / matched) if matched else 0.0
    mean_dev = (sum(o["deviation"] for o in out) / len(out)) if out else 0.0
    return {
        "positions":      out,
        "rmsd_nm":        rmsd,
        "min_deviation":  dev_min if dev_min is not None else 0.0,
        "max_deviation":  dev_max if dev_max is not None else 0.0,
        "mean_deviation": mean_dev,
        "n":              matched,
    }
