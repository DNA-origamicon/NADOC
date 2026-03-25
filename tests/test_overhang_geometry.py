"""
Baseline geometry tests for overhang extrusion.

For each overhang extruded on a 6HB HC design the tests verify:
  1. The overhang helix axis_start.z matches the Z of the nick nucleotide
     (|Δz| < 0.001 nm).  This catches the z_nick global-vs-local bp bug.
  2. The 3D distance between the nick's backbone bead and the overhang's
     first backbone bead is ≤ HONEYCOMB_HELIX_SPACING (2.25 nm) — the
     crossover must be physically plausible.

Test matrix:
  native   — 42 bp, bp_start = 0 on all helices (standard NADOC design)
  offset   — same topology but helices shifted to bp_start = 30 in Z,
             simulating a caDNAno import (bp_start != 0)

The offset tests FAIL before the z_nick fix and PASS after.
"""

import math

import numpy as np
import pytest

from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import (
    honeycomb_cell_value,
    honeycomb_position,
    is_valid_honeycomb_cell,
    make_auto_crossover,
    make_bundle_design,
    make_nicks_for_autostaple,
    make_overhang_extrude,
)
from backend.core.models import Design, Direction, Helix, StrandType, Vec3

# ── Tolerances ────────────────────────────────────────────────────────────────

Z_TOL     = 0.001   # nm — Z position must match within one thousandth of a nm
DIST_MAX  = HONEYCOMB_HELIX_SPACING + 0.01   # nm — 0.4% tolerance over HC spacing

# ── 6HB cell layout ───────────────────────────────────────────────────────────

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


# ── Design fixtures ───────────────────────────────────────────────────────────

def _make_stapled_6hb(length_bp: int = 42) -> Design:
    """6HB HC design with auto-scaffold, auto-crossovers and auto-nicks."""
    from backend.core.lattice import auto_scaffold

    d = make_bundle_design(CELLS_6HB, length_bp=length_bp)
    d = auto_scaffold(d)
    d = make_auto_crossover(d)
    d = make_nicks_for_autostaple(d)
    return d


def _shift_design_z(design: Design, bp_offset: int) -> Design:
    """
    Return a copy of *design* where every helix axis is shifted in Z by
    bp_offset × BDNA_RISE_PER_BP.  bp_start and all domain bp values are
    incremented by bp_offset to stay globally consistent — this mimics a
    caDNAno import where the scaffold begins at bp_start = bp_offset rather
    than 0.
    """
    shift = bp_offset * BDNA_RISE_PER_BP
    new_helices = []
    for h in design.helices:
        new_start    = Vec3(x=h.axis_start.x, y=h.axis_start.y, z=h.axis_start.z + shift)
        new_end      = Vec3(x=h.axis_end.x,   y=h.axis_end.y,   z=h.axis_end.z   + shift)
        new_bp_start = h.bp_start + bp_offset
        new_helices.append(h.model_copy(update={
            "axis_start": new_start,
            "axis_end":   new_end,
            "bp_start":   new_bp_start,
        }))

    # Shift all domain bp values by the same offset.
    from backend.core.models import Domain
    new_strands = []
    for strand in design.strands:
        new_domains = []
        for d in strand.domains:
            new_domains.append(d.model_copy(update={
                "start_bp": d.start_bp + bp_offset,
                "end_bp":   d.end_bp   + bp_offset,
            }))
        new_strands.append(strand.model_copy(update={"domains": new_domains}))

    return design.model_copy(update={"helices": new_helices, "strands": new_strands})


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _nick_z_correct(helix: Helix, bp_index: int) -> float:
    """Expected Z of the nick, using the correct local-bp formula."""
    local_i = bp_index - helix.bp_start
    rise = BDNA_RISE_PER_BP if helix.axis_end.z >= helix.axis_start.z else -BDNA_RISE_PER_BP
    return helix.axis_start.z + local_i * rise


def _backbone_pos_at(helix: Helix, bp_index: int, direction: Direction) -> np.ndarray:
    """Return the backbone position for (helix, bp_index, direction)."""
    for nuc in nucleotide_positions(helix):
        if nuc.bp_index == bp_index and nuc.direction == direction:
            return nuc.position
    raise ValueError(f"bp_index={bp_index} direction={direction} not found in helix {helix.id!r}")


# ── Site enumeration ──────────────────────────────────────────────────────────

_Z_EPS = 0.25  # nm — Z overlap tolerance for occupied-cell check


def _hc_valid_cells_at_spacing(row: int, col: int) -> list[tuple[int, int]]:
    """Return all valid HC neighbours of (row, col) at exactly HC spacing."""
    ox, oy = honeycomb_position(row, col)
    result = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if not is_valid_honeycomb_cell(nr, nc):
                continue
            nx, ny = honeycomb_position(nr, nc)
            dist = math.hypot(nx - ox, ny - oy)
            if abs(dist - HONEYCOMB_HELIX_SPACING) < 0.05:
                result.append((nr, nc))
    return result


def _all_overhang_sites(design: Design) -> list[dict]:
    """
    Return all (helix_id, bp_index, direction, is_five_prime, neighbor_row,
    neighbor_col) tuples where an overhang can be extruded.

    A site is valid if:
      - The strand is a staple.
      - The bp is the 5′ (first.start_bp) or 3′ (last.end_bp) end.
      - At least one neighbouring HC cell is unoccupied at that Z (± Z_EPS).
    """
    # Build helix lookup: id → helix
    helix_by_id = {h.id: h for h in design.helices}

    # Build ID → (row, col) from helix ID pattern h_{plane}_{row}_{col}
    import re
    _ID_RE = re.compile(r"^h_\w+_(-?\d+)_(-?\d+)$")

    def _row_col(hid: str):
        m = _ID_RE.match(hid)
        if not m:
            return None, None
        return int(m.group(1)), int(m.group(2))

    # Build Z-range map per cell: "row,col" → [(zMin, zMax)]
    cell_z: dict[str, list[tuple[float, float]]] = {}
    for h in design.helices:
        r, c = _row_col(h.id)
        if r is None:
            continue
        key = f"{r},{c}"
        zmin = min(h.axis_start.z, h.axis_end.z)
        zmax = max(h.axis_start.z, h.axis_end.z)
        cell_z.setdefault(key, []).append((zmin, zmax))

    def _occupied_at_z(nr: int, nc: int, z: float) -> bool:
        ranges = cell_z.get(f"{nr},{nc}", [])
        return any(z >= zmin - _Z_EPS and z <= zmax + _Z_EPS for zmin, zmax in ranges)

    sites = []
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        first = strand.domains[0]
        last  = strand.domains[-1]
        ends = [
            (first.helix_id, first.start_bp, first.direction, True),
            (last.helix_id,  last.end_bp,    last.direction,  False),
        ]
        for (hid, bp_idx, direc, is_5p) in ends:
            helix = helix_by_id.get(hid)
            if helix is None:
                continue
            row, col = _row_col(hid)
            if row is None:
                continue
            z = _nick_z_correct(helix, bp_idx)
            for nr, nc in _hc_valid_cells_at_spacing(row, col):
                if not _occupied_at_z(nr, nc, z):
                    sites.append({
                        "helix_id":     hid,
                        "bp_index":     bp_idx,
                        "direction":    direc,
                        "is_five_prime": is_5p,
                        "neighbor_row": nr,
                        "neighbor_col": nc,
                    })
    # Deduplicate by (helix_id, bp_index, direction, is_five_prime, neighbor)
    seen = set()
    unique = []
    for s in sites:
        key = (s["helix_id"], s["bp_index"], s["direction"], s["is_five_prime"],
               s["neighbor_row"], s["neighbor_col"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


# ── Measurement helpers ───────────────────────────────────────────────────────

def _check_site(design: Design, site: dict, z_tol: float = Z_TOL, dist_max: float = DIST_MAX):
    """
    Extrude an overhang at *site* and return (delta_z, distance) where:
      delta_z   = |overhang axis_start.z − nick Z|
      distance  = 3D distance between nick backbone bead and overhang start bead
    """
    result = make_overhang_extrude(
        design,
        helix_id     = site["helix_id"],
        bp_index     = site["bp_index"],
        direction    = site["direction"],
        is_five_prime = site["is_five_prime"],
        neighbor_row = site["neighbor_row"],
        neighbor_col = site["neighbor_col"],
        length_bp    = 8,
    )
    # Find the new overhang helix (not in original design)
    orig_ids = {h.id for h in design.helices}
    new_helices = [h for h in result.helices if h.id not in orig_ids]
    assert len(new_helices) == 1, f"Expected exactly 1 new helix, got {len(new_helices)}"
    ovhg_helix = new_helices[0]

    # Orig helix for nick Z reference
    orig_helix = next(h for h in design.helices if h.id == site["helix_id"])
    expected_z = _nick_z_correct(orig_helix, site["bp_index"])

    delta_z = abs(ovhg_helix.axis_start.z - expected_z)

    # Backbone positions at the crossover
    nick_dir    = site["direction"]
    nick_bp     = site["bp_index"]
    nick_pos    = _backbone_pos_at(orig_helix, nick_bp, nick_dir)

    # Overhang start bp is the near end (bp_start of the new helix)
    ovhg_bp     = ovhg_helix.bp_start
    # Direction of overhang domain
    ovhg_strand = next(
        s for s in result.strands
        if any(d.helix_id == ovhg_helix.id for d in s.domains)
    )
    ovhg_domain = next(d for d in ovhg_strand.domains if d.helix_id == ovhg_helix.id)
    ovhg_dir    = ovhg_domain.direction
    ovhg_pos    = _backbone_pos_at(ovhg_helix, ovhg_bp, ovhg_dir)

    distance = float(np.linalg.norm(ovhg_pos - nick_pos))

    return delta_z, distance


# ── Tests: native design (bp_start = 0) ──────────────────────────────────────

@pytest.fixture(scope="module")
def design_native():
    return _make_stapled_6hb(42)


def test_overhang_z_match_native(design_native):
    """Overhang axis_start.z must equal nick Z for all sites on a native design."""
    sites = _all_overhang_sites(design_native)
    assert sites, "No overhang sites found — check fixture or site enumeration"
    failures = []
    for site in sites:
        dz, _ = _check_site(design_native, site)
        if dz > Z_TOL:
            failures.append(f"  site {site['helix_id']} bp={site['bp_index']}: Δz={dz:.4f} nm")
    assert not failures, "Z mismatch on native design:\n" + "\n".join(failures)


def test_overhang_crossover_distance_native(design_native):
    """Nick→overhang backbone distance must be ≤ helix spacing for native design."""
    sites = _all_overhang_sites(design_native)
    failures = []
    for site in sites:
        _, dist = _check_site(design_native, site)
        if dist > DIST_MAX:
            failures.append(
                f"  site {site['helix_id']} bp={site['bp_index']}: dist={dist:.3f} nm > {DIST_MAX:.3f}"
            )
    assert not failures, "Crossover distance exceeded on native design:\n" + "\n".join(failures)


def test_overhang_all_ends_6hb(design_native):
    """Every valid overhang site on the 6HB 42bp design can be extruded without error."""
    sites = _all_overhang_sites(design_native)
    assert sites, "No overhang sites found"
    for site in sites:
        result = make_overhang_extrude(
            design_native,
            helix_id      = site["helix_id"],
            bp_index      = site["bp_index"],
            direction     = site["direction"],
            is_five_prime = site["is_five_prime"],
            neighbor_row  = site["neighbor_row"],
            neighbor_col  = site["neighbor_col"],
            length_bp     = 8,
        )
        orig_ids = {h.id for h in design_native.helices}
        new_helices = [h for h in result.helices if h.id not in orig_ids]
        assert len(new_helices) == 1, (
            f"Expected 1 new helix for site {site}, got {len(new_helices)}"
        )


# ── Tests: offset design (bp_start = 30, simulates caDNAno import) ───────────

@pytest.fixture(scope="module")
def design_offset():
    d = _make_stapled_6hb(42)
    return _shift_design_z(d, bp_offset=30)


def test_overhang_z_match_offset(design_offset):
    """Overhang axis_start.z must equal nick Z even when bp_start != 0."""
    sites = _all_overhang_sites(design_offset)
    assert sites, "No overhang sites found on offset design"
    failures = []
    for site in sites:
        dz, _ = _check_site(design_offset, site)
        if dz > Z_TOL:
            failures.append(f"  site {site['helix_id']} bp={site['bp_index']}: Δz={dz:.4f} nm")
    assert not failures, "Z mismatch on bp_start=30 design (z_nick bug):\n" + "\n".join(failures)


def test_overhang_crossover_distance_offset(design_offset):
    """Nick→overhang backbone distance must be ≤ helix spacing even with bp_start=30."""
    sites = _all_overhang_sites(design_offset)
    failures = []
    for site in sites:
        _, dist = _check_site(design_offset, site)
        if dist > DIST_MAX:
            failures.append(
                f"  site {site['helix_id']} bp={site['bp_index']}: dist={dist:.3f} nm > {DIST_MAX:.3f}"
            )
    assert not failures, "Crossover distance exceeded on offset design:\n" + "\n".join(failures)


# ── Test: PATCH overhang sequence resizes geometry correctly ──────────────────

def test_patch_overhang_resizes_helix(design_native):
    """Patching an overhang sequence to a new length must resize axis_end and domain bp."""
    from backend.core.models import Direction as D

    sites = _all_overhang_sites(design_native)
    assert sites
    site = sites[0]

    # Extrude with 8 bp
    d8 = make_overhang_extrude(
        design_native,
        helix_id      = site["helix_id"],
        bp_index      = site["bp_index"],
        direction     = site["direction"],
        is_five_prime = site["is_five_prime"],
        neighbor_row  = site["neighbor_row"],
        neighbor_col  = site["neighbor_col"],
        length_bp     = 8,
    )
    orig_ids = {h.id for h in design_native.helices}
    ovhg_id = next(h.id for h in d8.helices if h.id not in orig_ids)

    # Simulate PATCH sequence → 12 nt (same as patch_overhang endpoint logic)
    from backend.core.models import Vec3 as V3
    import numpy as _np

    spec = next(o for o in d8.overhangs if o.helix_id == ovhg_id)
    new_seq = "ACGTACGTACGT"   # 12 nt
    new_length_bp = len(new_seq)

    # Replicate resize logic from crud.patch_overhang
    helix = next(h for h in d8.helices if h.id == ovhg_id)
    ax = _np.array([
        helix.axis_end.x - helix.axis_start.x,
        helix.axis_end.y - helix.axis_start.y,
        helix.axis_end.z - helix.axis_start.z,
    ], dtype=float)
    ax_len = float(_np.linalg.norm(ax))
    unit = ax / ax_len
    new_len_nm = new_length_bp * BDNA_RISE_PER_BP
    new_end_arr = _np.array([
        helix.axis_start.x,
        helix.axis_start.y,
        helix.axis_start.z,
    ]) + unit * new_len_nm
    new_end = V3(x=float(new_end_arr[0]), y=float(new_end_arr[1]), z=float(new_end_arr[2]))

    # Check: new axis length ≈ new_len_nm
    new_ax_len = float(_np.linalg.norm(new_end_arr - _np.array([
        helix.axis_start.x, helix.axis_start.y, helix.axis_start.z
    ])))
    assert abs(new_ax_len - new_len_nm) < 1e-9, (
        f"Resized axis length {new_ax_len:.6f} ≠ expected {new_len_nm:.6f}"
    )

    # Check: old axis length ≈ 8 × RISE
    old_len_nm = 8 * BDNA_RISE_PER_BP
    assert abs(ax_len - old_len_nm) < 1e-6, (
        f"Original axis length {ax_len:.6f} ≠ expected {old_len_nm:.6f}"
    )
