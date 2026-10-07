"""Chemical landmark sites derived exclusively from the measured atomistic template.

FULL_REP is the sole native Full landmark definition: O5′ backbone and base-ring
centroids. MEASURED is the C3′ chemical landmark used by simulation tooling; it
is not a viewer placement mode. Missing or corrupt template data is fatal. There
are no frozen values, legacy projections, or optional groove overrides here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from backend.core.nucleotide_landmarks import (
    FULL_REP_BACKBONE_ATOM,
    PYRIMIDINE_RING,
    PURINE_RING,
)


@dataclass(frozen=True)
class Site:
    """One landmark's cylindrical place in the base-pair frame: (radius, azimuth, rise)."""

    radius_nm: float
    azimuth_deg: float
    axial_nm: float
    """Offset along the helix axis from the base pair's own plane.  Small but real
    (landmark-dependent), and dropping it would flatten the two strands into one plane."""

    def azimuth_rad(self) -> float:
        return math.radians(self.azimuth_deg)


@dataclass(frozen=True)
class MeasuredPositioning:
    """Where the CG beads go, all measured about the local helix axis.

    Every field is DERIVED from the all-atom template in ``measured_atomistic.py`` (see
    :func:`_from_atomistic_template`) rather than measured separately.  That is the point:
    the backbone bead is meant to BE a named sugar landmark and the base bead its base-ring
    centroid, so reading them off the same atoms the atomistic layer stamps is the only
    way the two representations can be guaranteed to agree.  A bead placed from an
    independent fit lands near the atom, not on it — the previous parameter set targeted
    the phosphorus and still missed it by 0.13 nm.
    """

    backbone_fwd: Site
    backbone_rev: Site
    """The configured sugar landmark of each strand.  The legacy measured/seed
    placement uses C3'; the full representation uses O5' via ``FULL_REP``."""

    # Historical C3' values retained on MEASURED for non-display consumers:
    # r = 0.804 nm at +24.5 deg on FORWARD and +154.7 deg on REVERSE.

    base_fwd: Site
    base_rev: Site
    """Base-ring centroid.  MD r = 0.314 nm; the legacy CG base bead is at 0.714 nm,
    more than twice too far out — the single largest placement error found."""

    slab_extent_nm: float
    """Long extent of the base slab, along the bead->base axis (NOT the cross-strand
    direction).  Sized to run from the nucleotide's own backbone bead inward to just
    past its Watson-Crick atom, so the slab visibly joins the base to its own sugar."""


def _site(vals: "list[tuple[float, float, float]]") -> Site:
    """Sequence-average a landmark: mean radius/rise, CIRCULAR mean azimuth."""
    r = float(np.mean([v[0] for v in vals]))
    z = float(np.mean([v[2] for v in vals]))
    ang = np.radians([v[1] for v in vals])
    az = math.degrees(math.atan2(float(np.sin(ang).mean()), float(np.cos(ang).mean())))
    return Site(radius_nm=round(r, 4), azimuth_deg=round(az, 2), axial_nm=round(z, 4))


def _from_atomistic_template(backbone_atom: str = "C3'") -> MeasuredPositioning:
    """Read chemical landmark sites; unavailable source data must fail loudly."""
    from backend.core import measured_atomistic as _ma

    tmpl = _ma.measured_templates()

    def landmark(role: str, which: str) -> Site:
        vals = []
        for residue in ("DA", "DT", "DG", "DC"):
            sugar, base = tmpl[(role, residue)]
            pos = {n: np.array([x, y, z]) for n, _e, x, y, z in (*sugar, *base)}
            if which == "BACKBONE":
                v = pos[backbone_atom]
            elif which == "RING":
                ring = PURINE_RING if residue in ("DA", "DG") else PYRIMIDINE_RING
                v = np.mean([pos[a] for a in ring], axis=0)
            else:  # the Watson-Crick donor/acceptor
                v = pos["N1"] if residue in ("DA", "DG") else pos["N3"]
            vals.append(
                (
                    float(math.hypot(v[0], v[1])),
                    math.degrees(math.atan2(v[1], v[0])),
                    float(v[2]),
                )
            )
        return _site(vals)

    bb_f = landmark("FORWARD", "BACKBONE")
    bb_r = landmark("REVERSE", "BACKBONE")
    ba_f, ba_r = landmark("FORWARD", "RING"), landmark("REVERSE", "RING")
    wc_f = landmark("FORWARD", "WC")

    # Slab length = bead -> own Watson-Crick atom, so the plate spans the whole base and
    # its OUTER end lands on the bead.  Measured straight-line, not a radial difference:
    # the bead sits 0.29 nm off the base's cross-strand line, so a slab merely lengthened
    # radially reaches the right radius and still misses the bead entirely.
    def xyz(s: Site) -> np.ndarray:
        return np.array(
            [
                s.radius_nm * math.cos(s.azimuth_rad()),
                s.radius_nm * math.sin(s.azimuth_rad()),
                s.axial_nm,
            ]
        )

    extent = float(np.linalg.norm(xyz(wc_f) - xyz(bb_f)))
    return MeasuredPositioning(
        backbone_fwd=bb_f,
        backbone_rev=bb_r,
        base_fwd=ba_f,
        base_rev=ba_r,
        slab_extent_nm=round(extent, 4),
    )


# These are different named chemical landmarks, not interchangeable display modes.
# Derivation failure intentionally propagates; there is no alternative placement.
MEASURED = _from_atomistic_template()
FULL_REP = _from_atomistic_template(FULL_REP_BACKBONE_ATOM)
