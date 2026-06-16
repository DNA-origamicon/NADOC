"""Route-for-polymerization core: connector staples + periodic-seam bridging.

The strong correctness oracle here is geometric: after routing a straight
bundle, ``derive_periodic_delta`` must come out as a PURE AXIAL TRANSLATION (no
rotation, det +1, magnitude ≈ part length). That only holds if the bridging
ligation lands on the terminal faces (caps) — an inner-edge ligation would yield
a far-too-short period. So this oracle pins the whole construction, not just a
strand count.
"""
import math

import numpy as np

from backend.core.lattice import _opposite_direction, _scaffold_coverage_by_helix
from backend.core.models import Design, Direction, Domain, Strand, StrandType
from backend.core.periodic_polymer import derive_periodic_delta
from backend.core.polymer_router import (
    _has_autoscaffold,
    _scaffold_dir_by_helix,
    route_for_polymerization,
    unpaired_bead_keys,
)
from tests.conftest import make_6hb_design


# ── fixtures ─────────────────────────────────────────────────────────────────


def _bundle_with_bare_ends(length_bp: int = 42, toehold: int = 10) -> Design:
    """6hb bundle with scaffold left single-stranded at both terminal faces.

    Keeps the scaffold strands; replaces every staple with a single interior
    staple per helix covering ``[lo+toehold, hi-toehold]`` so each helix has an
    unpaired scaffold run at its low cap and high cap.
    """
    d = make_6hb_design(length_bp=length_bp)
    cov = _scaffold_coverage_by_helix(d)
    sdir = _scaffold_dir_by_helix(d)
    staples: list[Strand] = []
    for hid, (lo, hi) in cov.items():
        cdir = _opposite_direction(sdir[hid])
        ilo, ihi = lo + toehold, hi - toehold
        start, end = (ilo, ihi) if cdir == Direction.FORWARD else (ihi, ilo)
        staples.append(Strand(
            domains=[Domain(helix_id=hid, start_bp=start, end_bp=end, direction=cdir)],
            strand_type=StrandType.STAPLE,
        ))
    new = [s for s in d.strands if s.strand_type == StrandType.SCAFFOLD] + staples
    return d.model_copy(update={"strands": new})


def _fully_stapled_bundle(length_bp: int = 42) -> Design:
    """6hb with every scaffold bp duplexed (no bare ends)."""
    d = make_6hb_design(length_bp=length_bp)
    cov = _scaffold_coverage_by_helix(d)
    sdir = _scaffold_dir_by_helix(d)
    staples: list[Strand] = []
    for hid, (lo, hi) in cov.items():
        cdir = _opposite_direction(sdir[hid])
        start, end = (lo, hi) if cdir == Direction.FORWARD else (hi, lo)
        staples.append(Strand(
            domains=[Domain(helix_id=hid, start_bp=start, end_bp=end, direction=cdir)],
            strand_type=StrandType.STAPLE,
        ))
    new = [s for s in d.strands if s.strand_type == StrandType.SCAFFOLD] + staples
    return d.model_copy(update={"strands": new})


# ── connector generation ─────────────────────────────────────────────────────


def test_creates_connector_per_bare_end():
    d = _bundle_with_bare_ends()
    cov = _scaffold_coverage_by_helix(d)
    routed, res = route_for_polymerization(d)
    assert res.valid
    # one near + one far connector per covered helix
    assert len(res.new_connector_strand_ids) == 2 * len(cov)


def test_ends_fully_duplexed_after_routing():
    """No unpaired SCAFFOLD bead remains once the connectors are placed."""
    d = _bundle_with_bare_ends()
    sdir = _scaffold_dir_by_helix(d)
    routed, _ = route_for_polymerization(d)
    leftover = {
        (h, bp) for (h, bp, dr) in unpaired_bead_keys(routed)
        if sdir.get(h) == dr      # an unpaired bead on the scaffold's own slot
    }
    assert leftover == set()


def test_every_bridge_is_a_periodic_seam():
    """Each face-helix's bridging staple wraps through the boundary, so EVERY
    bridge is flagged is_periodic_seam (not just one). principal_seam_id is the
    first, for reporting + the single-connector assembly mate."""
    d = _bundle_with_bare_ends()
    n_helices = len(_scaffold_coverage_by_helix(d))
    routed, res = route_for_polymerization(d)
    seams = [fl for fl in routed.forced_ligations if fl.is_periodic_seam]
    assert len(seams) == n_helices                       # one per face-helix
    assert len(res.seam_ligation_ids) == n_helices
    assert res.principal_seam_id in {fl.id for fl in seams}


def test_seam_endpoints_land_on_terminal_faces():
    """The principal seam must connect the low cap to the high cap, not interiors."""
    d = _bundle_with_bare_ends()
    cov = _scaffold_coverage_by_helix(d)
    routed, res = route_for_polymerization(d)
    seam = next(fl for fl in routed.forced_ligations if fl.is_periodic_seam)
    lo, hi = cov[seam.three_prime_helix_id]
    caps = {seam.three_prime_bp, seam.five_prime_bp}
    assert caps == {lo, hi}


# ── geometric oracle ─────────────────────────────────────────────────────────


def test_derived_period_is_pure_axial_translation():
    length_bp = 42
    d = _bundle_with_bare_ends(length_bp=length_bp)
    routed, _ = route_for_polymerization(d)

    delta = derive_periodic_delta(routed)
    R = delta[:3, :3]
    t = delta[:3, 3]

    # rotation ≈ 0, no reflection
    cos_t = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    angle_deg = math.degrees(math.acos(cos_t))
    assert angle_deg < 2.0, f"expected straight repeat, got {angle_deg:.2f}° rotation"
    assert float(np.linalg.det(R)) > 0.9

    # translation ≈ whole part length (period spans cap→cap+1 bp ≈ length_bp bp)
    trans = float(np.linalg.norm(t))
    assert length_bp * 0.30 < trans < length_bp * 0.40, trans


# ── warnings / guards ────────────────────────────────────────────────────────


def test_warns_when_no_autoscaffold():
    d = _bundle_with_bare_ends()
    assert not _has_autoscaffold(d)
    _, res = route_for_polymerization(d)
    assert any("Autoscaffold" in w for w in res.warnings)


def test_errors_when_nothing_to_route():
    d = _fully_stapled_bundle()
    routed, res = route_for_polymerization(d)
    assert not res.valid
    assert res.errors
    # design unchanged (no connectors added)
    assert routed is d or len(routed.strands) == len(d.strands)
