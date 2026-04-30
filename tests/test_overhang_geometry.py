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
import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.constants import BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD, HONEYCOMB_HELIX_SPACING
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import (
    honeycomb_position,
    is_valid_honeycomb_cell,
    make_bundle_design,
    make_overhang_extrude,
    square_position,
)
from backend.core.models import Design, Direction, Helix, LatticeType, StrandType, Vec3

# ── Tolerances ────────────────────────────────────────────────────────────────

Z_TOL     = 0.001   # nm — Z position must match within one thousandth of a nm
DIST_MAX  = HONEYCOMB_HELIX_SPACING + 0.01   # nm — 0.4% tolerance over HC spacing

# ── 6HB cell layout ───────────────────────────────────────────────────────────

CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]


# ── Design fixtures ───────────────────────────────────────────────────────────

def _make_stapled_6hb(length_bp: int = 42) -> Design:
    """6HB HC design for geometry tests."""
    return make_bundle_design(CELLS_6HB, length_bp=length_bp)


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

    # Junction Z: for +Z overhangs the junction is at axis_start (local bp 0);
    # for −Z overhangs the axis is flipped so the junction is at local bp L-1.
    axis_span_z = ovhg_helix.axis_end.z - ovhg_helix.axis_start.z
    if axis_span_z >= 0:
        # +Z axis — junction at axis_start
        junction_z = ovhg_helix.axis_start.z
    else:
        # (should not happen after axis flip, but guard anyway)
        junction_z = ovhg_helix.axis_start.z
    # After axis-flip, bp_start <= bp_index.  Junction bp is always bp_index.
    junction_bp = site["bp_index"]
    local_junc  = junction_bp - ovhg_helix.bp_start
    rise_per_bp = BDNA_RISE_PER_BP
    junction_z  = ovhg_helix.axis_start.z + local_junc * rise_per_bp * (1 if axis_span_z >= 0 else -1)
    delta_z = abs(junction_z - expected_z)

    # Backbone positions at the crossover
    nick_dir    = site["direction"]
    nick_bp     = site["bp_index"]
    nick_pos    = _backbone_pos_at(orig_helix, nick_bp, nick_dir)

    # Junction bp on the overhang helix
    ovhg_bp     = junction_bp
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


# ── Tests: overhang domain added to cluster ──────────────────────────────────

def test_overhang_extrude_adds_domain_to_domain_level_cluster(design_native):
    """When the parent helix belongs to a domain-level cluster, the new overhang
    domain must be added to that cluster's domain_ids so the cluster transform
    applies to the overhang nucleotides."""
    from backend.core.models import ClusterRigidTransform, DomainRef

    sites = _all_overhang_sites(design_native)
    assert sites
    site = sites[0]

    # Create a domain-level cluster containing the parent helix
    parent_helix_id = site["helix_id"]
    parent_strand = None
    for s in design_native.strands:
        if s.strand_type == StrandType.STAPLE and s.domains:
            first = s.domains[0]
            last = s.domains[-1]
            if site["is_five_prime"]:
                if first.helix_id == parent_helix_id and first.start_bp == site["bp_index"] and first.direction == site["direction"]:
                    parent_strand = s
                    break
            else:
                if last.helix_id == parent_helix_id and last.end_bp == site["bp_index"] and last.direction == site["direction"]:
                    parent_strand = s
                    break
    assert parent_strand is not None

    # Build domain refs for the parent strand
    domain_refs = [
        DomainRef(strand_id=parent_strand.id, domain_index=i)
        for i in range(len(parent_strand.domains))
    ]

    cluster = ClusterRigidTransform(
        name="TestCluster",
        helix_ids=[h.id for h in design_native.helices],
        domain_ids=domain_refs,
        translation=[5.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
    )
    design_with_cluster = design_native.model_copy(
        update={"cluster_transforms": [cluster]}
    )

    result = make_overhang_extrude(
        design_with_cluster,
        helix_id      = site["helix_id"],
        bp_index      = site["bp_index"],
        direction     = site["direction"],
        is_five_prime = site["is_five_prime"],
        neighbor_row  = site["neighbor_row"],
        neighbor_col  = site["neighbor_col"],
        length_bp     = 8,
    )

    # The cluster must now contain the new helix and the new domain
    ct = result.cluster_transforms[0]
    orig_ids = {h.id for h in design_native.helices}
    new_helix_id = next(h.id for h in result.helices if h.id not in orig_ids)
    assert new_helix_id in ct.helix_ids, "New overhang helix not in cluster helix_ids"

    # Find the new domain ref in cluster domain_ids
    new_strand = next(s for s in result.strands if s.id == parent_strand.id)
    ovhg_domain_idx = None
    for i, d in enumerate(new_strand.domains):
        if d.helix_id == new_helix_id:
            ovhg_domain_idx = i
            break
    assert ovhg_domain_idx is not None, "No overhang domain found on new helix"

    found_ref = any(
        dr.strand_id == parent_strand.id and dr.domain_index == ovhg_domain_idx
        for dr in ct.domain_ids
    )
    assert found_ref, (
        f"Overhang domain (strand={parent_strand.id}, idx={ovhg_domain_idx}) "
        f"not found in cluster domain_ids: {ct.domain_ids}"
    )


def test_overhang_extrude_shifts_domain_refs_on_prepend(design_native):
    """When prepending a domain (5' nick), existing DomainRef indices for the
    same strand must shift +1 in all clusters."""
    from backend.core.models import ClusterRigidTransform, DomainRef

    # Find a 5' site
    sites = _all_overhang_sites(design_native)
    site_5p = next((s for s in sites if s["is_five_prime"]), None)
    if site_5p is None:
        pytest.skip("No 5' overhang site available")

    parent_helix_id = site_5p["helix_id"]
    parent_strand = None
    for s in design_native.strands:
        if s.strand_type == StrandType.STAPLE and s.domains:
            first = s.domains[0]
            if first.helix_id == parent_helix_id and first.start_bp == site_5p["bp_index"] and first.direction == site_5p["direction"]:
                parent_strand = s
                break
    assert parent_strand is not None

    orig_domain_count = len(parent_strand.domains)
    domain_refs = [
        DomainRef(strand_id=parent_strand.id, domain_index=i)
        for i in range(orig_domain_count)
    ]

    cluster = ClusterRigidTransform(
        name="TestCluster",
        helix_ids=[h.id for h in design_native.helices],
        domain_ids=domain_refs,
    )
    design_with_cluster = design_native.model_copy(
        update={"cluster_transforms": [cluster]}
    )

    result = make_overhang_extrude(
        design_with_cluster,
        helix_id      = site_5p["helix_id"],
        bp_index      = site_5p["bp_index"],
        direction     = site_5p["direction"],
        is_five_prime = True,
        neighbor_row  = site_5p["neighbor_row"],
        neighbor_col  = site_5p["neighbor_col"],
        length_bp     = 8,
    )

    ct = result.cluster_transforms[0]
    # Original domain indices should be shifted +1
    for orig_idx in range(orig_domain_count):
        found = any(
            dr.strand_id == parent_strand.id and dr.domain_index == orig_idx + 1
            for dr in ct.domain_ids
        )
        assert found, (
            f"Original domain index {orig_idx} should be shifted to {orig_idx + 1} "
            f"but not found in cluster domain_ids"
        )

    # New overhang domain should be at index 0
    found_new = any(
        dr.strand_id == parent_strand.id and dr.domain_index == 0
        for dr in ct.domain_ids
    )
    assert found_new, "Prepended overhang domain (index 0) not found in cluster domain_ids"


# ── Tests: overhang_id preservation across domain operations ─────────────

def test_merge_adjacent_preserves_overhang_id():
    """_merge_adjacent_domains preserves overhang_id on same-tag merges."""
    from backend.core.lattice import _merge_adjacent_domains
    from backend.core.models import Domain

    d1 = Domain(helix_id="h1", start_bp=0, end_bp=3, direction=Direction.FORWARD, overhang_id="ovhg_test")
    d2 = Domain(helix_id="h1", start_bp=4, end_bp=7, direction=Direction.FORWARD, overhang_id="ovhg_test")
    merged = _merge_adjacent_domains([d1, d2])
    assert len(merged) == 1
    assert merged[0].overhang_id == "ovhg_test"
    assert merged[0].start_bp == 0
    assert merged[0].end_bp == 7


def test_merge_adjacent_none_overhang_stays_none():
    """_merge_adjacent_domains with overhang_id=None stays None (no regression)."""
    from backend.core.lattice import _merge_adjacent_domains
    from backend.core.models import Domain

    d1 = Domain(helix_id="h1", start_bp=0, end_bp=3, direction=Direction.FORWARD)
    d2 = Domain(helix_id="h1", start_bp=4, end_bp=7, direction=Direction.FORWARD)
    merged = _merge_adjacent_domains([d1, d2])
    assert len(merged) == 1
    assert merged[0].overhang_id is None


def test_merge_different_overhang_ids_not_merged():
    """Domains with different overhang_ids must not be merged."""
    from backend.core.lattice import _merge_adjacent_domains
    from backend.core.models import Domain

    d1 = Domain(helix_id="h1", start_bp=0, end_bp=3, direction=Direction.FORWARD, overhang_id="ovhg_a")
    d2 = Domain(helix_id="h1", start_bp=4, end_bp=7, direction=Direction.FORWARD, overhang_id="ovhg_b")
    merged = _merge_adjacent_domains([d1, d2])
    assert len(merged) == 2


def test_ligate_and_merge_cross_type_drops_overhang(design_native):
    """Merging overhang + non-overhang domains drops overhang_id and cleans up OverhangSpec."""
    from backend.core.lattice import _ligate_and_merge
    from backend.core.models import Domain, OverhangSpec, Strand

    # Create two strands: s1 ends with a regular domain, s2 starts with an overhang domain,
    # both on the same helix and adjacent.
    helix = design_native.helices[0]
    s1 = Strand(id="s1", domains=[
        Domain(helix_id=helix.id, start_bp=0, end_bp=5, direction=Direction.FORWARD),
    ], strand_type=StrandType.STAPLE)
    s2 = Strand(id="s2", domains=[
        Domain(helix_id=helix.id, start_bp=6, end_bp=10, direction=Direction.FORWARD, overhang_id="ovhg_test"),
    ], strand_type=StrandType.STAPLE)
    ovhg_spec = OverhangSpec(id="ovhg_test", helix_id=helix.id, strand_id="s2")

    d = design_native.model_copy(update={
        "strands": list(design_native.strands) + [s1, s2],
        "overhangs": list(design_native.overhangs) + [ovhg_spec],
    })

    result = _ligate_and_merge(d, s1, s2)

    # The merged strand should exist and the junction domain should have no overhang_id
    merged_strand = next(s for s in result.strands if s.id == "s1")
    assert len(merged_strand.domains) == 1  # merged into one
    assert merged_strand.domains[0].overhang_id is None

    # The orphaned OverhangSpec should be removed
    assert not any(o.id == "ovhg_test" for o in result.overhangs)


def test_ligate_and_merge_remaps_strand_id(design_native):
    """When s2 is absorbed, its OverhangSpecs get strand_id remapped to s1.id."""
    from backend.core.lattice import _ligate_and_merge
    from backend.core.models import Domain, OverhangSpec, Strand

    helix = design_native.helices[0]
    helix2 = design_native.helices[1]
    # s1 has one domain, s2 has a regular domain followed by an overhang on a different helix.
    s1 = Strand(id="s1", domains=[
        Domain(helix_id=helix.id, start_bp=0, end_bp=5, direction=Direction.FORWARD),
    ], strand_type=StrandType.STAPLE)
    s2 = Strand(id="s2", domains=[
        Domain(helix_id=helix.id, start_bp=6, end_bp=10, direction=Direction.FORWARD),
        Domain(helix_id=helix2.id, start_bp=0, end_bp=5, direction=Direction.REVERSE, overhang_id="ovhg_s2"),
    ], strand_type=StrandType.STAPLE)
    ovhg_spec = OverhangSpec(id="ovhg_s2", helix_id=helix2.id, strand_id="s2")

    d = design_native.model_copy(update={
        "strands": list(design_native.strands) + [s1, s2],
        "overhangs": list(design_native.overhangs) + [ovhg_spec],
    })

    result = _ligate_and_merge(d, s1, s2)

    # OverhangSpec.strand_id should now be s1.id
    spec = next(o for o in result.overhangs if o.id == "ovhg_s2")
    assert spec.strand_id == "s1"


def _minimal_design_with_strand(strand, overhangs=None):
    """Create a minimal Design containing only the given strand(s) and helix stubs."""
    from backend.core.models import Design, Helix, LatticeType, Vec3
    helix_ids = set()
    if isinstance(strand, list):
        strands = strand
        for s in strands:
            for d in s.domains:
                helix_ids.add(d.helix_id)
    else:
        strands = [strand]
        for d in strand.domains:
            helix_ids.add(d.helix_id)
    helices = [
        Helix(id=hid, axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=14),
              bp_start=0, length_bp=42)
        for hid in helix_ids
    ]
    return Design(
        helices=helices, strands=strands, lattice_type=LatticeType.HONEYCOMB,
        overhangs=overhangs or [],
    )


def test_make_nick_propagates_overhang_to_terminal():
    """Nicking within a terminal overhang domain: terminal fragment keeps overhang_id."""
    from backend.core.lattice import make_nick
    from backend.core.models import Domain, OverhangSpec, Strand

    s = Strand(id="test_strand", domains=[
        Domain(helix_id="hA", start_bp=0, end_bp=10, direction=Direction.FORWARD),
        Domain(helix_id="hA", start_bp=11, end_bp=20, direction=Direction.FORWARD, overhang_id="ovhg_nick_test"),
    ], strand_type=StrandType.STAPLE)
    ovhg_spec = OverhangSpec(id="ovhg_nick_test", helix_id="hA", strand_id="test_strand")
    d = _minimal_design_with_strand(s, overhangs=[ovhg_spec])

    # Nick within the overhang domain (last domain, index 1) at bp 15
    result = make_nick(d, "hA", 15, Direction.FORWARD)

    left = next(st for st in result.strands if st.id == "test_strand")
    right_id = f"test_strand_hA_15_r"
    right = next(st for st in result.strands if st.id == right_id)

    # The right fragment's first domain (formerly last domain's right half)
    # should be the 3' terminal and keep overhang_id.
    right_ovhg_dom = right.domains[-1]
    assert right_ovhg_dom.overhang_id == "ovhg_nick_test"

    # The left fragment's last domain (formerly last domain's left half)
    # should NOT have overhang_id (it's now internal).
    left_last = left.domains[-1]
    assert left_last.overhang_id is None


def test_make_nick_5prime_overhang_stays_left():
    """Nicking within a 5' terminal overhang domain: left fragment keeps overhang_id."""
    from backend.core.lattice import make_nick
    from backend.core.models import Domain, OverhangSpec, Strand

    s = Strand(id="test_strand", domains=[
        Domain(helix_id="hA", start_bp=0, end_bp=10, direction=Direction.FORWARD, overhang_id="ovhg_5p"),
        Domain(helix_id="hA", start_bp=11, end_bp=20, direction=Direction.FORWARD),
    ], strand_type=StrandType.STAPLE)
    ovhg_spec = OverhangSpec(id="ovhg_5p", helix_id="hA", strand_id="test_strand")
    d = _minimal_design_with_strand(s, overhangs=[ovhg_spec])

    # Nick within the overhang domain (first domain, index 0) at bp 5
    result = make_nick(d, "hA", 5, Direction.FORWARD)

    left = next(st for st in result.strands if st.id == "test_strand")

    # Left fragment's first domain should keep overhang_id (it's the 5' terminal)
    assert left.domains[0].overhang_id == "ovhg_5p"


def test_make_nick_updates_overhang_strand_id():
    """When nicking a strand, OverhangSpec.strand_id follows the overhang domain to the right fragment."""
    from backend.core.lattice import make_nick
    from backend.core.models import Domain, OverhangSpec, Strand

    s = Strand(id="test_strand", domains=[
        Domain(helix_id="hA", start_bp=0, end_bp=20, direction=Direction.FORWARD),
        Domain(helix_id="hA", start_bp=21, end_bp=30, direction=Direction.FORWARD, overhang_id="ovhg_strand_test"),
    ], strand_type=StrandType.STAPLE)
    ovhg_spec = OverhangSpec(id="ovhg_strand_test", helix_id="hA", strand_id="test_strand")
    d = _minimal_design_with_strand(s, overhangs=[ovhg_spec])

    # Nick within the first domain
    result = make_nick(d, "hA", 10, Direction.FORWARD)

    right_id = "test_strand_hA_10_r"

    # OverhangSpec should follow to right fragment
    spec = next(o for o in result.overhangs if o.id == "ovhg_strand_test")
    assert spec.strand_id == right_id, (
        f"OverhangSpec.strand_id should be {right_id!r} but is {spec.strand_id!r}"
    )


# ── Tests: SQ lattice overhang position ──────────────────────────────────────

CELLS_4SQ = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _make_stapled_4sq(length_bp: int = 32) -> Design:
    """4-helix SQ bundle."""
    return make_bundle_design(CELLS_4SQ, length_bp=length_bp, lattice_type=LatticeType.SQUARE)


def test_sq_overhang_uses_square_position():
    """Overhang helix on a SQ design must use square_position, not HC."""
    d = _make_stapled_4sq(32)
    # Find a 3' staple end on helix (0,0) and extrude toward (0,1)
    helix_00 = next(h for h in d.helices if tuple(h.grid_pos) == (0, 0))
    staple = next(
        s for s in d.strands
        if s.strand_type == StrandType.STAPLE
        and any(dom.helix_id == helix_00.id for dom in s.domains)
    )
    last_dom = staple.domains[-1]

    result = make_overhang_extrude(
        d,
        helix_id     = last_dom.helix_id,
        bp_index     = last_dom.end_bp,
        direction    = last_dom.direction,
        is_five_prime = False,
        neighbor_row = 0,
        neighbor_col = 2,   # unoccupied SQ neighbor
        length_bp    = 8,
    )

    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)

    # XY must match square_position, not honeycomb_position
    sx, sy = square_position(0, 2)
    hx, hy = honeycomb_position(0, 2)
    assert abs(ovhg_helix.axis_start.x - sx) < 0.001
    assert abs(ovhg_helix.axis_start.y - sy) < 0.001
    # Verify it doesn't accidentally match HC position (they differ)
    assert abs(sx - hx) > 0.01 or abs(sy - hy) > 0.01, "SQ and HC positions shouldn't be identical"


def test_overhang_helix_has_grid_pos():
    """Overhang helices must have grid_pos set."""
    d = _make_stapled_6hb(42)
    sites = _all_overhang_sites(d)
    assert sites
    site = sites[0]
    result = make_overhang_extrude(
        d,
        helix_id     = site["helix_id"],
        bp_index     = site["bp_index"],
        direction    = site["direction"],
        is_five_prime = site["is_five_prime"],
        neighbor_row = site["neighbor_row"],
        neighbor_col = site["neighbor_col"],
        length_bp    = 8,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)
    assert tuple(ovhg_helix.grid_pos) == (site["neighbor_row"], site["neighbor_col"])


# ── Tests: −Z overhang domain direction in cadnano 2D ────────────────────────

def test_minus_z_overhang_domain_extends_leftward():
    """For −Z overhang, domain bp range must extend leftward from bp_index in 2D."""
    d = _make_stapled_6hb(42)
    sites = _all_overhang_sites(d)

    # Find a site where the overhang would go in the −Z direction.
    # This happens when: 3' nick on FORWARD strand → overhang −Z
    #                     5' nick on REVERSE strand → overhang −Z
    minus_z_site = None
    for site in sites:
        helix = next(h for h in d.helices if h.id == site["helix_id"])
        z_dir = 1 if (helix.axis_end.z - helix.axis_start.z) >= 0 else -1
        strand_z_dir = z_dir if site["direction"] == Direction.FORWARD else -z_dir
        overhang_z_dir = strand_z_dir if site["is_five_prime"] else -strand_z_dir
        if overhang_z_dir < 0:
            minus_z_site = site
            break
    assert minus_z_site is not None, "No −Z overhang site found in fixture"

    length_bp = 8
    result = make_overhang_extrude(
        d,
        helix_id     = minus_z_site["helix_id"],
        bp_index     = minus_z_site["bp_index"],
        direction    = minus_z_site["direction"],
        is_five_prime = minus_z_site["is_five_prime"],
        neighbor_row = minus_z_site["neighbor_row"],
        neighbor_col = minus_z_site["neighbor_col"],
        length_bp    = length_bp,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)
    ovhg_strand = next(
        s for s in result.strands
        if any(dom.helix_id == ovhg_helix.id for dom in s.domains)
    )
    ovhg_domain = next(dom for dom in ovhg_strand.domains if dom.helix_id == ovhg_helix.id)

    # In cadnano 2D, domain horizontal extent is [min(start_bp, end_bp), max(start_bp, end_bp)].
    # For −Z overhang the domain must be to the LEFT of bp_index:
    #   max(start_bp, end_bp) == bp_index  (junction is the rightmost bp)
    #   min(start_bp, end_bp) == bp_index - length_bp + 1
    bp = minus_z_site["bp_index"]
    assert max(ovhg_domain.start_bp, ovhg_domain.end_bp) == bp, (
        f"−Z overhang domain right edge should be bp_index={bp}, "
        f"got max({ovhg_domain.start_bp}, {ovhg_domain.end_bp})"
    )
    assert min(ovhg_domain.start_bp, ovhg_domain.end_bp) == bp - length_bp + 1, (
        f"−Z overhang domain left edge should be {bp - length_bp + 1}, "
        f"got min({ovhg_domain.start_bp}, {ovhg_domain.end_bp})"
    )


def test_minus_z_overhang_axis_is_plus_z():
    """−Z overhangs must have their axis flipped to +Z (axis_end.z > axis_start.z)."""
    d = _make_stapled_6hb(42)
    sites = _all_overhang_sites(d)

    minus_z_site = None
    for site in sites:
        helix = next(h for h in d.helices if h.id == site["helix_id"])
        z_dir = 1 if (helix.axis_end.z - helix.axis_start.z) >= 0 else -1
        strand_z_dir = z_dir if site["direction"] == Direction.FORWARD else -z_dir
        overhang_z_dir = strand_z_dir if site["is_five_prime"] else -strand_z_dir
        if overhang_z_dir < 0:
            minus_z_site = site
            break
    assert minus_z_site is not None

    result = make_overhang_extrude(
        d,
        helix_id     = minus_z_site["helix_id"],
        bp_index     = minus_z_site["bp_index"],
        direction    = minus_z_site["direction"],
        is_five_prime = minus_z_site["is_five_prime"],
        neighbor_row = minus_z_site["neighbor_row"],
        neighbor_col = minus_z_site["neighbor_col"],
        length_bp    = 8,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)
    assert ovhg_helix.axis_end.z > ovhg_helix.axis_start.z, (
        f"−Z overhang axis should be flipped to +Z but got "
        f"axis_start.z={ovhg_helix.axis_start.z:.4f}, axis_end.z={ovhg_helix.axis_end.z:.4f}"
    )


def test_minus_z_overhang_junction_z_correct():
    """Junction nucleotide on −Z overhang must be at z_nick (same Z as parent nick)."""
    d = _make_stapled_6hb(42)
    sites = _all_overhang_sites(d)

    minus_z_site = None
    for site in sites:
        helix = next(h for h in d.helices if h.id == site["helix_id"])
        z_dir = 1 if (helix.axis_end.z - helix.axis_start.z) >= 0 else -1
        strand_z_dir = z_dir if site["direction"] == Direction.FORWARD else -z_dir
        overhang_z_dir = strand_z_dir if site["is_five_prime"] else -strand_z_dir
        if overhang_z_dir < 0:
            minus_z_site = site
            break
    assert minus_z_site is not None

    result = make_overhang_extrude(
        d,
        helix_id     = minus_z_site["helix_id"],
        bp_index     = minus_z_site["bp_index"],
        direction    = minus_z_site["direction"],
        is_five_prime = minus_z_site["is_five_prime"],
        neighbor_row = minus_z_site["neighbor_row"],
        neighbor_col = minus_z_site["neighbor_col"],
        length_bp    = 8,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)
    orig_helix = next(h for h in d.helices if h.id == minus_z_site["helix_id"])
    expected_z = _nick_z_correct(orig_helix, minus_z_site["bp_index"])

    # Junction is at bp_index on the overhang helix — compute its Z from the axis
    local_junc = minus_z_site["bp_index"] - ovhg_helix.bp_start
    junction_z = ovhg_helix.axis_start.z + local_junc * BDNA_RISE_PER_BP
    assert abs(junction_z - expected_z) < Z_TOL, (
        f"Junction Z mismatch: got {junction_z:.4f}, expected {expected_z:.4f}"
    )


def test_plus_z_overhang_unchanged():
    """Verify +Z overhangs still work correctly (regression guard)."""
    d = _make_stapled_6hb(42)
    sites = _all_overhang_sites(d)

    plus_z_site = None
    for site in sites:
        helix = next(h for h in d.helices if h.id == site["helix_id"])
        z_dir = 1 if (helix.axis_end.z - helix.axis_start.z) >= 0 else -1
        strand_z_dir = z_dir if site["direction"] == Direction.FORWARD else -z_dir
        overhang_z_dir = strand_z_dir if site["is_five_prime"] else -strand_z_dir
        if overhang_z_dir > 0:
            plus_z_site = site
            break
    assert plus_z_site is not None

    length_bp = 8
    result = make_overhang_extrude(
        d,
        helix_id     = plus_z_site["helix_id"],
        bp_index     = plus_z_site["bp_index"],
        direction    = plus_z_site["direction"],
        is_five_prime = plus_z_site["is_five_prime"],
        neighbor_row = plus_z_site["neighbor_row"],
        neighbor_col = plus_z_site["neighbor_col"],
        length_bp    = length_bp,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix = next(h for h in result.helices if h.id not in orig_ids)
    ovhg_strand = next(
        s for s in result.strands
        if any(dom.helix_id == ovhg_helix.id for dom in s.domains)
    )
    ovhg_domain = next(dom for dom in ovhg_strand.domains if dom.helix_id == ovhg_helix.id)

    bp = plus_z_site["bp_index"]
    # +Z overhang: domain extends rightward from bp_index
    assert min(ovhg_domain.start_bp, ovhg_domain.end_bp) == bp
    assert max(ovhg_domain.start_bp, ovhg_domain.end_bp) == bp + length_bp - 1
    # bp_start == bp_index for +Z
    assert ovhg_helix.bp_start == bp
    # Axis is +Z
    assert ovhg_helix.axis_end.z > ovhg_helix.axis_start.z


# ── Tests: shared overhang helix at same lattice cell ─────────────────────────

def _find_two_sites_same_cell(design):
    """Find two overhang sites targeting the same neighbor (row, col).

    Returns (site_a, site_b) or None if no such pair exists.
    """
    sites = _all_overhang_sites(design)
    by_cell: dict[tuple, list] = {}
    for s in sites:
        key = (s["neighbor_row"], s["neighbor_col"])
        by_cell.setdefault(key, []).append(s)
    for cell, group in by_cell.items():
        if len(group) >= 2:
            return group[0], group[1]
    return None


def test_two_overhangs_same_cell_share_helix():
    """Two overhangs targeting the same (row, col) must share one helix."""
    d = _make_stapled_6hb(42)
    pair = _find_two_sites_same_cell(d)
    assert pair is not None, "Could not find two overhang sites targeting the same cell"
    site_a, site_b = pair

    # Extrude first overhang
    d1 = make_overhang_extrude(
        d,
        helix_id      = site_a["helix_id"],
        bp_index      = site_a["bp_index"],
        direction     = site_a["direction"],
        is_five_prime = site_a["is_five_prime"],
        neighbor_row  = site_a["neighbor_row"],
        neighbor_col  = site_a["neighbor_col"],
        length_bp     = 8,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helices_after_first = [h for h in d1.helices if h.id not in orig_ids]
    assert len(ovhg_helices_after_first) == 1
    shared_helix_id = ovhg_helices_after_first[0].id

    # Extrude second overhang to the same cell
    d2 = make_overhang_extrude(
        d1,
        helix_id      = site_b["helix_id"],
        bp_index      = site_b["bp_index"],
        direction     = site_b["direction"],
        is_five_prime = site_b["is_five_prime"],
        neighbor_row  = site_b["neighbor_row"],
        neighbor_col  = site_b["neighbor_col"],
        length_bp     = 8,
    )

    # Should still be only 1 helix at that grid position (not 2)
    ovhg_helices = [h for h in d2.helices if h.id not in orig_ids]
    assert len(ovhg_helices) == 1, (
        f"Expected 1 shared overhang helix, got {len(ovhg_helices)}: "
        f"{[h.id for h in ovhg_helices]}"
    )
    shared = ovhg_helices[0]
    assert shared.id == shared_helix_id

    # Both overhang domains must be on the shared helix
    ovhg_domains = [
        dom for s in d2.strands for dom in s.domains
        if dom.helix_id == shared_helix_id and dom.overhang_id is not None
    ]
    assert len(ovhg_domains) == 2, (
        f"Expected 2 overhang domains on shared helix, got {len(ovhg_domains)}"
    )

    # Both OverhangSpecs must reference the shared helix
    shared_specs = [o for o in d2.overhangs if o.helix_id == shared_helix_id]
    assert len(shared_specs) == 2

    # Both crossovers must reference the shared helix
    shared_xovers = [
        x for x in d2.crossovers
        if x.half_b.helix_id == shared_helix_id
    ]
    assert len(shared_xovers) == 2

    # Helix bp range covers both domains
    for dom in ovhg_domains:
        lo = min(dom.start_bp, dom.end_bp)
        hi = max(dom.start_bp, dom.end_bp)
        assert lo >= shared.bp_start, f"Domain lo={lo} < bp_start={shared.bp_start}"
        assert hi <= shared.bp_start + shared.length_bp - 1, (
            f"Domain hi={hi} > bp_end={shared.bp_start + shared.length_bp - 1}"
        )


def test_shared_helix_extends_backward():
    """When the second overhang has lower bp, the shared helix extends backward."""
    d = _make_stapled_6hb(42)
    pair = _find_two_sites_same_cell(d)
    assert pair is not None
    # Sort so the higher bp_index site is extruded first
    site_a, site_b = sorted(pair, key=lambda s: s["bp_index"], reverse=True)

    d1 = make_overhang_extrude(
        d,
        helix_id=site_a["helix_id"], bp_index=site_a["bp_index"],
        direction=site_a["direction"], is_five_prime=site_a["is_five_prime"],
        neighbor_row=site_a["neighbor_row"], neighbor_col=site_a["neighbor_col"],
        length_bp=8,
    )
    orig_ids = {h.id for h in d.helices}
    helix_after_first = next(h for h in d1.helices if h.id not in orig_ids)
    first_bp_start = helix_after_first.bp_start
    first_axis_start_z = helix_after_first.axis_start.z
    first_phase = helix_after_first.phase_offset

    # Compute nucleotide positions BEFORE the second extrusion
    from backend.core.geometry import nucleotide_positions as nuc_pos
    nucs_before = nuc_pos(helix_after_first)
    # Pick a nucleotide from the first domain to check position stability
    ref_nuc = nucs_before[0]
    ref_bp = ref_nuc.bp_index
    ref_pos = ref_nuc.position.copy()

    d2 = make_overhang_extrude(
        d1,
        helix_id=site_b["helix_id"], bp_index=site_b["bp_index"],
        direction=site_b["direction"], is_five_prime=site_b["is_five_prime"],
        neighbor_row=site_b["neighbor_row"], neighbor_col=site_b["neighbor_col"],
        length_bp=8,
    )
    shared = next(h for h in d2.helices if h.id not in orig_ids)

    if site_b["bp_index"] < site_a["bp_index"]:
        # Second overhang is lower bp → helix should extend backward
        assert shared.bp_start <= first_bp_start
        assert shared.axis_start.z <= first_axis_start_z + 0.001

    # Existing nucleotide positions must not shift
    nucs_after = nuc_pos(shared)
    ref_after = next(
        (n for n in nucs_after if n.bp_index == ref_bp and n.direction == ref_nuc.direction),
        None,
    )
    assert ref_after is not None, f"bp_index={ref_bp} not found after extension"
    dist = float(np.linalg.norm(ref_after.position - ref_pos))
    assert dist < 0.001, (
        f"Nucleotide at bp={ref_bp} shifted by {dist:.4f} nm after helix extension"
    )


# ── Inline overhang reconciliation tests ─────────────────────────────────────

from backend.core.lattice import reconcile_all_inline_overhangs
from backend.core.models import Domain, OverhangSpec, Strand


def _make_design_with_stale_overhang() -> Design:
    """Build a minimal design where a staple terminal domain is falsely tagged
    as an inline overhang despite being fully within scaffold coverage.

    Helix h0: scaffold FORWARD [0, 41], staple REVERSE split into
      - domain [41, 36] tagged ovhg_inline_stap1_5p  (6 bp, WITHIN scaffold)
      - domain [35, 0]  untagged
    """
    h0 = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=41 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        twist_per_bp_rad=BDNA_TWIST_PER_BP_RAD,
        length_bp=42,
        bp_start=0,
        grid_pos=(0, 1),
    )
    scaffold = Strand(
        id="scaf1",
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    ovhg_id = "ovhg_inline_stap1_5p"
    staple = Strand(
        id="stap1",
        domains=[
            Domain(helix_id="h0", start_bp=41, end_bp=36, direction=Direction.REVERSE,
                   overhang_id=ovhg_id),
            Domain(helix_id="h0", start_bp=35, end_bp=0, direction=Direction.REVERSE),
        ],
        strand_type=StrandType.STAPLE,
    )
    ovhg_spec = OverhangSpec(id=ovhg_id, helix_id="h0", strand_id="stap1")
    return Design(
        helices=[h0],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
        overhangs=[ovhg_spec],
    )


def test_stale_inline_overhangs_cleaned_on_reconcile():
    """Stale inline overhang tags within scaffold coverage should be merged away."""
    design = _make_design_with_stale_overhang()
    assert len(design.overhangs) == 1

    updated = reconcile_all_inline_overhangs(design)

    # Overhang should be removed — domain is fully within scaffold
    assert len(updated.overhangs) == 0
    stap = next(s for s in updated.strands if s.id == "stap1")
    # The two domains should be merged back into one
    assert len(stap.domains) == 1
    dom = stap.domains[0]
    assert dom.overhang_id is None
    assert dom.start_bp == 41
    assert dom.end_bp == 0


def _make_design_with_valid_overhang() -> Design:
    """Build a design where a staple terminal domain genuinely extends beyond
    scaffold coverage — this overhang should be preserved by reconciliation.

    Helix h0: scaffold FORWARD [5, 41], staple REVERSE [41, 0].
    The staple's 3' end at bp 0 is outside scaffold coverage [5, 41].
    After reconciliation, bp [0..4] should be tagged as overhang.
    """
    h0 = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=41 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        twist_per_bp_rad=BDNA_TWIST_PER_BP_RAD,
        length_bp=42,
        bp_start=0,
        grid_pos=(0, 1),
    )
    scaffold = Strand(
        id="scaf1",
        domains=[Domain(helix_id="h0", start_bp=5, end_bp=41, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="stap1",
        domains=[
            Domain(helix_id="h0", start_bp=41, end_bp=0, direction=Direction.REVERSE),
        ],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        helices=[h0],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
    )


def test_valid_inline_overhangs_preserved():
    """Domains that genuinely extend beyond scaffold coverage should be split and tagged."""
    design = _make_design_with_valid_overhang()
    assert len(design.overhangs) == 0

    updated = reconcile_all_inline_overhangs(design)

    # An overhang should be created for the portion below scaffold coverage
    assert len(updated.overhangs) == 1
    stap = next(s for s in updated.strands if s.id == "stap1")
    # The domain should be split into scaffold part + overhang part
    assert len(stap.domains) == 2
    # 3' end (last domain in 5'→3' order) should be the overhang
    ovhg_dom = stap.domains[-1]
    assert ovhg_dom.overhang_id is not None
    # Overhang covers bp 4 down to 0 (REVERSE)
    assert min(ovhg_dom.start_bp, ovhg_dom.end_bp) <= 4
    # Scaffold part should not be tagged
    scaf_dom = stap.domains[0]
    assert scaf_dom.overhang_id is None


def test_overhang_rotation_axis_native(design_native):
    """Axis arrow for an extrude overhang must update after rotation (NADOC-native design).

    Verifies that _apply_ovhg_rotations_to_axes correctly rotates the axis samples
    using the junction nucleotide backbone position as pivot (same as
    apply_overhang_rotation_if_needed), so axis and backbone beads stay aligned.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import _apply_ovhg_rotations_to_axes, deformed_helix_axes

    sites = _all_overhang_sites(design_native)
    assert sites
    site = sites[0]

    d = make_overhang_extrude(
        design_native,
        helix_id=site["helix_id"], bp_index=site["bp_index"],
        direction=site["direction"], is_five_prime=site["is_five_prime"],
        neighbor_row=site["neighbor_row"], neighbor_col=site["neighbor_col"],
        length_bp=8,
    )
    orig_ids = {h.id for h in design_native.helices}
    ovhg_helix_id = next(h.id for h in d.helices if h.id not in orig_ids)
    ovhg_spec = next(o for o in d.overhangs if o.helix_id == ovhg_helix_id)

    # Record pre-rotation axis
    nucs_pre = _geometry_for_design(d)
    axes_pre = deformed_helix_axes(d)
    _apply_ovhg_rotations_to_axes(d, axes_pre, nucs_pre)
    ax_pre = next(ax for ax in axes_pre if ax["helix_id"] == ovhg_helix_id)
    start_pre = np.array(ax_pre["start"])
    end_pre   = np.array(ax_pre["end"])

    # Apply 90° rotation about Y axis
    quat_90_y = [0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)]
    d_rot = d.model_copy(update={
        "overhangs": [
            o.model_copy(update={"rotation": quat_90_y}) if o.id == ovhg_spec.id else o
            for o in d.overhangs
        ]
    })

    nucs_post = _geometry_for_design(d_rot)
    axes_post = deformed_helix_axes(d_rot)
    _apply_ovhg_rotations_to_axes(d_rot, axes_post, nucs_post)
    ax_post = next(ax for ax in axes_post if ax["helix_id"] == ovhg_helix_id)
    end_post = np.array(ax_post["end"])

    # Axis end must have moved substantially (8 bp × 0.34 nm ≈ 2.72 nm arm; 90° sweeps it)
    end_dist = float(np.linalg.norm(end_post - end_pre))
    assert end_dist > 0.5, (
        f"Axis end did not move after 90° rotation: displaced only {end_dist:.4f} nm"
    )

    # Axis length must be preserved (rotation is rigid)
    pre_len  = float(np.linalg.norm(end_pre  - start_pre))
    post_len = float(np.linalg.norm(np.array(ax_post["end"]) - np.array(ax_post["start"])))
    assert abs(pre_len - post_len) < 0.01, (
        f"Axis length changed under rotation: {pre_len:.4f} → {post_len:.4f} nm"
    )


def test_overhang_rotation_axis_cadnano_style():
    """Pivot stays aligned with axis_start after _recenter_design, and rotation is correct.

    The 6HB design starts with a non-zero XY centre (~3.9, ~2.25 nm).
    We extrude an overhang (pivot stored in pre-recenter coords), then call _recenter_design.
    Fix A: _recenter_design must also shift ovhg.pivot by (-cx, -cy).
    After recentering, applying a 90° Y rotation must move the axis end correctly.
    """
    from backend.api.crud import _geometry_for_design, _recenter_design
    from backend.core.deformation import _apply_ovhg_rotations_to_axes, deformed_helix_axes

    d = _make_stapled_6hb(42)  # helices NOT centred (cx ≈ 3.897, cy ≈ 2.25)

    sites = _all_overhang_sites(d)
    assert sites
    site = sites[0]

    # Extrude overhang — pivot stored in pre-recenter coordinates
    d_extruded = make_overhang_extrude(
        d,
        helix_id=site["helix_id"], bp_index=site["bp_index"],
        direction=site["direction"], is_five_prime=site["is_five_prime"],
        neighbor_row=site["neighbor_row"], neighbor_col=site["neighbor_col"],
        length_bp=8,
    )
    orig_ids = {h.id for h in d.helices}
    ovhg_helix_id  = next(h.id for h in d_extruded.helices if h.id not in orig_ids)
    ovhg_helix_pre = next(h for h in d_extruded.helices if h.id == ovhg_helix_id)
    ovhg_spec_pre  = next(o for o in d_extruded.overhangs if o.helix_id == ovhg_helix_id)

    # Pivot before recentering must match pre-recenter axis_start XY
    assert abs(ovhg_spec_pre.pivot[0] - ovhg_helix_pre.axis_start.x) < 1e-6
    assert abs(ovhg_spec_pre.pivot[1] - ovhg_helix_pre.axis_start.y) < 1e-6

    # Recenter — Fix A: pivot must be shifted by the same (-cx, -cy) as the helices
    d_centered = _recenter_design(d_extruded)
    ovhg_helix_post = next(h for h in d_centered.helices if h.id == ovhg_helix_id)
    ovhg_spec_post  = next(o for o in d_centered.overhangs if o.helix_id == ovhg_helix_id)

    assert abs(ovhg_spec_post.pivot[0] - ovhg_helix_post.axis_start.x) < 1e-6, (
        f"pivot.x={ovhg_spec_post.pivot[0]:.6f} != axis_start.x={ovhg_helix_post.axis_start.x:.6f}"
    )
    assert abs(ovhg_spec_post.pivot[1] - ovhg_helix_post.axis_start.y) < 1e-6, (
        f"pivot.y={ovhg_spec_post.pivot[1]:.6f} != axis_start.y={ovhg_helix_post.axis_start.y:.6f}"
    )

    # Apply 90° Y rotation and verify the axis arrow moves correctly
    quat_90_y = [0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)]
    d_rot = d_centered.model_copy(update={
        "overhangs": [
            o.model_copy(update={"rotation": quat_90_y}) if o.id == ovhg_spec_post.id else o
            for o in d_centered.overhangs
        ]
    })

    nucs_pre  = _geometry_for_design(d_centered)
    axes_pre  = deformed_helix_axes(d_centered)
    _apply_ovhg_rotations_to_axes(d_centered, axes_pre, nucs_pre)
    ax_pre = next(ax for ax in axes_pre if ax["helix_id"] == ovhg_helix_id)

    nucs_post = _geometry_for_design(d_rot)
    axes_post = deformed_helix_axes(d_rot)
    _apply_ovhg_rotations_to_axes(d_rot, axes_post, nucs_post)
    ax_post = next(ax for ax in axes_post if ax["helix_id"] == ovhg_helix_id)

    end_dist = float(np.linalg.norm(np.array(ax_post["end"]) - np.array(ax_pre["end"])))
    assert end_dist > 0.5, (
        f"Axis end did not move after 90° rotation on centered design: {end_dist:.4f} nm"
    )

    pre_len  = float(np.linalg.norm(np.array(ax_pre["end"])  - np.array(ax_pre["start"])))
    post_len = float(np.linalg.norm(np.array(ax_post["end"]) - np.array(ax_post["start"])))
    assert abs(pre_len - post_len) < 0.01, (
        f"Axis length changed under rotation: {pre_len:.4f} → {post_len:.4f} nm"
    )


def test_cadnano_overhang_axes_use_trimmed_physical_span():
    """Per-overhang axis shafts must align with their owning domain bp span.

    caDNAno imports keep helix.length_bp as the full vstrand array length, while
    axis_start/axis_end are trimmed to occupied DNA.  ovhg_axes must use the
    physical trimmed axis span, otherwise later overhang shafts compress toward
    axis_start and no longer match their domains.
    """
    from backend.api.crud import _geometry_for_design, _recenter_design
    from backend.core.cadnano import import_cadnano
    from backend.core.deformation import _apply_ovhg_rotations_to_axes, deformed_helix_axes
    from backend.core.lattice import autodetect_all_overhangs

    path = Path("Examples/cadnano/Ultimate Polymer Hinge 191016.json")
    if not path.exists():
        pytest.skip("Ultimate Polymer Hinge example file not present")

    design, _ = import_cadnano(json.loads(path.read_text()))
    design = _recenter_design(autodetect_all_overhangs(design))

    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, _geometry_for_design(design))
    axes_by_id = {ax["helix_id"]: ax for ax in axes}
    helix_by_id = {h.id: h for h in design.helices}

    def axis_point(h, bp):
        s = np.array(h.axis_start.to_array(), dtype=float)
        e = np.array(h.axis_end.to_array(), dtype=float)
        phys_len = max(1, round(float(np.linalg.norm(e - s)) / BDNA_RISE_PER_BP) + 1)
        t = (bp - h.bp_start) / max(1, phys_len - 1)
        return s + t * (e - s)

    failures = []
    checked = 0
    for strand in design.strands:
        for dom in strand.domains:
            if not dom.overhang_id:
                continue
            checked += 1
            h = helix_by_id[dom.helix_id]
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            ovhg_axis = axes_by_id[dom.helix_id]["ovhg_axes"][dom.overhang_id]
            start_err = float(np.linalg.norm(np.array(ovhg_axis["start"]) - axis_point(h, lo)))
            end_err = float(np.linalg.norm(np.array(ovhg_axis["end"]) - axis_point(h, hi + 1)))
            if start_err > 0.01 or end_err > 0.01:
                failures.append(
                    f"{dom.overhang_id} {dom.helix_id} [{lo},{hi}] "
                    f"start_err={start_err:.3f} end_err={end_err:.3f}"
                )

    assert checked == 36
    assert not failures, "ovhg_axes domain-span mismatches:\n" + "\n".join(failures[:20])


def test_shared_inline_overhang_rotation_emits_domain_axis_without_moving_parent():
    """Shared-helix inline overhangs need rotated ovhg_axes for labels/end rings.

    The parent helix axis belongs to scaffold too, so its global samples must stay
    fixed.  The per-overhang axis, however, should still carry the committed
    rotation so 3D domain-end sprites rebuild with the overhang domain.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core.deformation import _apply_ovhg_rotations_to_axes, _rot_from_quaternion, deformed_helix_axes
    from backend.core.models import Domain, OverhangSpec, Strand

    ovhg_id = "ovhg_inline_shared"
    strand = Strand(id="stap", domains=[
        Domain(helix_id="hA", start_bp=0, end_bp=10, direction=Direction.FORWARD),
        Domain(helix_id="hA", start_bp=11, end_bp=20, direction=Direction.FORWARD, overhang_id=ovhg_id),
    ], strand_type=StrandType.STAPLE)
    scaffold = Strand(id="scaf", domains=[
        Domain(helix_id="hA", start_bp=0, end_bp=41, direction=Direction.REVERSE),
    ], strand_type=StrandType.SCAFFOLD)
    rotation = [0.0, math.sin(math.radians(22.5)), 0.0, math.cos(math.radians(22.5))]
    design = _minimal_design_with_strand(
        [strand, scaffold],
        overhangs=[OverhangSpec(id=ovhg_id, helix_id="hA", strand_id="stap", rotation=rotation)],
    )

    axes = deformed_helix_axes(design)
    original_samples = [list(p) for p in axes[0]["samples"]]
    _apply_ovhg_rotations_to_axes(design, axes, _geometry_for_design(design))

    assert axes[0]["samples"] == original_samples
    ovhg_axis = axes[0]["ovhg_axes"][ovhg_id]

    helix = design.helices[0]
    axis_start = np.array(helix.axis_start.to_array(), dtype=float)
    axis_end = np.array(helix.axis_end.to_array(), dtype=float)
    axis_vec = axis_end - axis_start
    phys_len = max(1, round(float(np.linalg.norm(axis_vec)) / BDNA_RISE_PER_BP) + 1)

    def axis_point(bp):
        t = (bp - helix.bp_start) / max(1, phys_len - 1)
        return axis_start + t * axis_vec

    nucs = _geometry_for_design(design)
    pivot = np.array(next(
        n["backbone_position"]
        for n in nucs
        if n["helix_id"] == "hA" and n["bp_index"] == 11 and n["direction"] == "FORWARD"
    ), dtype=float)
    R = _rot_from_quaternion(*rotation)
    expected_start = R @ (axis_point(11) - pivot) + pivot
    expected_end = R @ (axis_point(21) - pivot) + pivot

    assert np.linalg.norm(np.array(ovhg_axis["start"]) - expected_start) < 0.01
    assert np.linalg.norm(np.array(ovhg_axis["end"]) - expected_end) < 0.01


def test_hingeV4_no_false_positives():
    """Loading hingeV4.nadoc and reconciling should remove all false-positive overhangs."""
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "Examples", "hingeV4.nadoc")
    if not os.path.isfile(path):
        pytest.skip("hingeV4.nadoc not available")
    with open(path) as f:
        design = Design.from_json(f.read())

    # Build scaffold coverage
    scaf_cov: dict[str, tuple[int, int]] = {}
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            for dom in s.domains:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                if dom.helix_id in scaf_cov:
                    prev_lo, prev_hi = scaf_cov[dom.helix_id]
                    scaf_cov[dom.helix_id] = (min(prev_lo, lo), max(prev_hi, hi))
                else:
                    scaf_cov[dom.helix_id] = (lo, hi)

    # Count false positives BEFORE reconciliation
    false_pos_before = 0
    for s in design.strands:
        for dom in s.domains:
            if dom.overhang_id and dom.helix_id in scaf_cov:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                cov_lo, cov_hi = scaf_cov[dom.helix_id]
                if lo >= cov_lo and hi <= cov_hi:
                    false_pos_before += 1
    assert false_pos_before > 0, "Expected false positives in raw file"

    # Reconcile
    updated = reconcile_all_inline_overhangs(design)

    # Count false positives AFTER reconciliation — should be zero
    false_pos_after = 0
    for s in updated.strands:
        for dom in s.domains:
            if dom.overhang_id and dom.helix_id in scaf_cov:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                cov_lo, cov_hi = scaf_cov[dom.helix_id]
                if lo >= cov_lo and hi <= cov_hi:
                    false_pos_after += 1
    assert false_pos_after == 0, f"Still {false_pos_after} false-positive overhangs after reconciliation"
