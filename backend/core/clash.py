"""
Design-layer steric-clash detector (geometric, pure, importable).

Flags backbone beads that collide in the *posed* geometry — the geometry
produced by ``deformed_nucleotide_positions`` with all cluster poses and
bend/twist deformations applied — but that are NOT close to each other in the
un-posed (straight) design.  This is the criterion that separates a real steric
clash from designed packing:

  * Designed proximity — Watson–Crick partners, covalently adjacent nucleotides,
    placed-crossover / forced-ligation partners, and tight lattice packing of
    neighbouring helices in one bundle — is already close (≤ a couple of nm) in
    the STRAIGHT geometry, so it is close in the posed geometry too.  It is not a
    clash; it is the structure.
  * A folding collision — e.g. two arms brought together at a mitred corner by a
    cluster fold — is far apart (tens of nm) in the straight geometry and only
    collides once the pose is applied.  That is the clash.

So a posed bead pair is reported iff:

    posed_distance   <  threshold_nm            (they overlap now)  AND
    straight_distance >  designed_margin_nm     (they were NOT designed close)

This is topology-free: no lattice-neighbour enumeration, no crossover lookup —
the straight geometry itself encodes every "expected proximity" class.

Calibration (see ``tests/test_clash.py``):
  * clean bundles (6hb / 18hb / 26hb_platform_v3) report 0 clashes;
  * ``corner_miter_test`` reports its A↔B corner-seam clashes (backbone pairs
    < 0.65 nm whose straight separation is ~20 nm).

This is the design-layer counterpart to the MD-time NAMD soft-minimisation
declash (``backend/core/md_protocols.py``): it detects clashes on a Design with
no simulation, and it is a pure function so downstream validators (e.g. the
headless corner primitive) can import it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from backend.core.deformation import deformed_nucleotide_positions

if TYPE_CHECKING:
    from backend.core.models import Design


# ── Calibrated defaults ───────────────────────────────────────────────────────
# Backbone beads sit at HELIX_RADIUS (1.0 nm) from the axis.  Adjacent-helix
# lattice packing legitimately brings them to ~0.25–0.3 nm, so a bare nearest-
# bead test would flag every clean bundle — the straight-geometry exclusion is
# what makes the threshold usable.
DEFAULT_CLASH_THRESHOLD_NM: float = 0.65
# Two beads within this distance in the STRAIGHT design are treated as a designed
# contact, never a clash.  Designed-close pairs measure ≤ ~0.5 nm straight; the
# smallest genuine folding clash in the reference corner is ~20 nm straight, so
# any margin in [1, 10] separates them — 2.0 nm (≈ one helix diameter) is used.
DEFAULT_DESIGNED_MARGIN_NM: float = 2.0


@dataclass
class ClashSide:
    """One nucleotide involved in a clash."""

    helix_id: str
    bp_index: int
    direction: str  # "FORWARD" | "REVERSE"
    position: tuple[float, float, float]  # posed backbone-bead position (nm)

    def to_dict(self) -> dict:
        return {
            "helix_id": self.helix_id,
            "bp_index": self.bp_index,
            "direction": self.direction,
            "position": list(self.position),
        }


@dataclass
class ClashPair:
    """A pair of nucleotide backbone beads that clash in the posed geometry."""

    a: ClashSide
    b: ClashSide
    distance_nm: float

    def to_dict(self) -> dict:
        return {
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
            "distance_nm": self.distance_nm,
        }


@dataclass
class ClashReport:
    """Result of ``clash_report`` — the clashing pairs (nearest first) + a count."""

    pairs: list[ClashPair] = field(default_factory=list)
    threshold_nm: float = DEFAULT_CLASH_THRESHOLD_NM
    designed_margin_nm: float = DEFAULT_DESIGNED_MARGIN_NM

    @property
    def count(self) -> int:
        return len(self.pairs)

    def to_dict(self) -> dict:
        return {
            "clashes": [p.to_dict() for p in self.pairs],
            "count": self.count,
            "threshold_nm": self.threshold_nm,
            "designed_margin_nm": self.designed_margin_nm,
        }


def _bead_arrays(design: "Design") -> tuple[list[tuple[str, int, str]], np.ndarray]:
    """Posed backbone-bead keys + positions for every nucleotide in *design*.

    Key = (helix_id, bp_index, direction-name).  Positions run through
    ``deformed_nucleotide_positions`` so cluster poses + deformations are applied
    (and the effective-helix / loop-skip handling matches ``GET /design/geometry``).
    """
    keys: list[tuple[str, int, str]] = []
    pts: list[np.ndarray] = []
    for helix in design.helices:
        for nuc in deformed_nucleotide_positions(helix, design):
            keys.append((nuc.helix_id, int(nuc.bp_index), nuc.direction.name))
            pts.append(np.asarray(nuc.position, dtype=float))
    arr = np.asarray(pts, dtype=float) if pts else np.empty((0, 3), dtype=float)
    return keys, arr


def clash_report(
    design: "Design",
    *,
    threshold_nm: float = DEFAULT_CLASH_THRESHOLD_NM,
    designed_margin_nm: float = DEFAULT_DESIGNED_MARGIN_NM,
) -> ClashReport:
    """Return the steric-clash report for *design*.

    A posed backbone-bead pair is a clash iff its posed separation is
    ``< threshold_nm`` AND its straight (un-posed) separation is
    ``> designed_margin_nm`` — i.e. the collision was introduced by the pose /
    deformation and is not designed packing.  Pairs are returned nearest-first.
    """
    keys, posed = _bead_arrays(design)
    if len(posed) < 2:
        return ClashReport(
            pairs=[], threshold_nm=threshold_nm, designed_margin_nm=designed_margin_nm
        )

    # Straight reference: strip only the pose (deformations + cluster transforms),
    # keeping loop/skips, extensions, overhangs etc. so the two geometries share
    # the same bead set — mirrors get_geometry's straight-embed strip.
    straight_design = design.model_copy(
        update={"deformations": [], "cluster_transforms": []}
    )
    skeys, straight = _bead_arrays(straight_design)
    straight_by_key = {k: straight[i] for i, k in enumerate(skeys)}

    tree = cKDTree(posed)
    raw = tree.query_pairs(threshold_nm, output_type="ndarray")

    pairs: list[ClashPair] = []
    for i, j in raw:
        sa = straight_by_key.get(keys[i])
        sb = straight_by_key.get(keys[j])
        # A bead with no straight counterpart can't be proven designed-close;
        # skip it (conservative — avoids false clashes from pose-only beads).
        if sa is None or sb is None:
            continue
        if float(np.linalg.norm(sa - sb)) <= designed_margin_nm:
            continue  # designed proximity — not a clash
        dist = float(np.linalg.norm(posed[i] - posed[j]))
        pairs.append(
            ClashPair(
                a=ClashSide(keys[i][0], keys[i][1], keys[i][2], tuple(posed[i])),
                b=ClashSide(keys[j][0], keys[j][1], keys[j][2], tuple(posed[j])),
                distance_nm=dist,
            )
        )

    pairs.sort(key=lambda p: p.distance_nm)
    return ClashReport(
        pairs=pairs, threshold_nm=threshold_nm, designed_margin_nm=designed_margin_nm
    )
