"""Regression: PATCH /design/overhang/{id} must always resize the FREE TIP of an
extruded overhang, not the crossover-connecting junction end.

Bug 1 (refactor_prompts/06): when an overhang is created by ``make_overhang_extrude``
on a parent helix end where the strand exits in −Z (the typical 3' nick on a
FORWARD strand of a +Z helix), the overhang helix is built with axis flipped to
+Z but the junction at the helix's *high* bp end (local bp L−1, global bp =
``bp_index``).  The patch resize logic in ``crud.patch_overhang`` assumes the
junction is always at the *low* bp end (``start_bp`` for FORWARD, ``end_bp`` for
REVERSE), so for −Z overhangs it grows the junction-side bp instead of the tip,
ate into the parent helix's adjacent strand, and produced a doubled crossover
in the user's screenshot.

These tests build a 6HB HC design, extrude an overhang on every staple-end
site, then PATCH the sequence to a longer (and shorter) length.  The post-patch
domain MUST keep the junction bp fixed; only the tip bp may move.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING
from backend.core.lattice import (
    honeycomb_position,
    is_valid_honeycomb_cell,
    make_bundle_design,
    make_overhang_extrude,
)
from backend.core.models import Design, StrandType


client = TestClient(app)


# ── Helpers (mirrored from test_overhang_geometry.py) ────────────────────────

CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]


def _make_stapled_6hb(length_bp: int = 42) -> Design:
    return make_bundle_design(CELLS_6HB, length_bp=length_bp)


def _hc_valid_cells_at_spacing(row: int, col: int) -> list[tuple[int, int]]:
    ox, oy = honeycomb_position(row, col)
    out: list[tuple[int, int]] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if not is_valid_honeycomb_cell(nr, nc):
                continue
            nx, ny = honeycomb_position(nr, nc)
            if abs(math.hypot(nx - ox, ny - oy) - HONEYCOMB_HELIX_SPACING) < 0.05:
                out.append((nr, nc))
    return out


def _row_col(hid: str) -> tuple[int | None, int | None]:
    import re
    m = re.match(r"^h_\w+_(-?\d+)_(-?\d+)$", hid)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _all_overhang_sites(design: Design):
    """Every (helix_id, bp_index, direction, is_five_prime, neighbor_row, neighbor_col)
    where an overhang can be extruded."""
    helix_by_id = {h.id: h for h in design.helices}
    cell_z: dict[str, list[tuple[float, float]]] = {}
    for h in design.helices:
        r, c = _row_col(h.id)
        if r is None:
            continue
        zmin = min(h.axis_start.z, h.axis_end.z)
        zmax = max(h.axis_start.z, h.axis_end.z)
        cell_z.setdefault(f"{r},{c}", []).append((zmin, zmax))

    def _occupied(nr: int, nc: int, z: float) -> bool:
        return any(zmin - 0.25 <= z <= zmax + 0.25 for zmin, zmax in cell_z.get(f"{nr},{nc}", []))

    sites: list[dict] = []
    seen: set[tuple] = set()
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        first, last = strand.domains[0], strand.domains[-1]
        ends = [
            (first.helix_id, first.start_bp, first.direction, True),
            (last.helix_id,  last.end_bp,    last.direction,  False),
        ]
        for hid, bp_idx, direc, is_5p in ends:
            helix = helix_by_id.get(hid)
            row, col = _row_col(hid)
            if helix is None or row is None:
                continue
            local = bp_idx - helix.bp_start
            rise = BDNA_RISE_PER_BP if helix.axis_end.z >= helix.axis_start.z else -BDNA_RISE_PER_BP
            z = helix.axis_start.z + local * rise
            for nr, nc in _hc_valid_cells_at_spacing(row, col):
                if _occupied(nr, nc, z):
                    continue
                key = (hid, bp_idx, direc, is_5p, nr, nc)
                if key in seen:
                    continue
                seen.add(key)
                sites.append(dict(
                    helix_id=hid, bp_index=bp_idx, direction=direc,
                    is_five_prime=is_5p, neighbor_row=nr, neighbor_col=nc,
                ))
    return sites


def _junction_and_tip_bp(domain, helix) -> tuple[int, int]:
    """For an extrude overhang domain, return (junction_bp, tip_bp).

    The junction bp is where the overhang helix meets the parent (the bp that
    appears in the registered Crossover record for this helix).  The tip bp is
    the other endpoint of the domain.  We identify the junction mechanically:
    it is the domain endpoint whose bp is at the parent-facing end of the helix
    (the helix's bp_start side for +Z extrudes; bp_start + length_bp − 1 for
    −Z extrudes, where the axis was flipped).

    We avoid reasoning about polarity: simply pick whichever of (start_bp,
    end_bp) matches the helix's far-from-axis-start bp range bound — that's
    the junction in −Z extrudes.  For +Z extrudes the junction is at the
    helix's near (axis_start) bp end.
    """
    helix_lo = helix.bp_start
    helix_hi = helix.bp_start + helix.length_bp - 1
    # +Z helix axis: bp_start at axis_start (low Z); −Z extrudes have axis flipped to +Z
    # but the junction is at the high bp end (z_nick = axis_start.z + (L−1)*RISE).
    # Detect via the make_overhang_extrude convention: −Z extrudes have
    # axis_end.z − axis_start.z == helix.length_bp * RISE BUT bp_start != bp_index
    # used originally. Simpler: the junction bp matches where the registered
    # crossover places it. For tests it's easiest to check both endpoints of
    # the domain against helix_lo and helix_hi.
    bp_a, bp_b = domain.start_bp, domain.end_bp
    # The endpoints must be exactly the helix's bp_lo and bp_hi (extrude
    # domains span the full helix).
    assert {bp_a, bp_b} == {helix_lo, helix_hi}
    # Use Z to discriminate which is the junction. Junction Z equals the
    # parent's nick Z. For an extrude where bp_start = bp_index (the +Z case),
    # the junction is at helix_lo. For bp_start = bp_index − L + 1 (−Z), the
    # junction is at helix_hi.
    return None, None  # filled in by caller using axis info; placeholder


def _extrude_junction_bp(orig_design: Design, orig_helix_id: str, bp_index: int,
                         new_helix) -> int:
    """The junction bp on the overhang helix is just bp_index (by construction
    in make_overhang_extrude). Both +Z and −Z cases match parent's bp_index."""
    return bp_index


# ── Bug 1 reproduction ────────────────────────────────────────────────────────


def _load_design(d: Design):
    """Replace the active design held by design_state with d."""
    design_state.set_design(d)


def _post_patch(overhang_id: str, sequence: str | None):
    body = {"sequence": sequence}
    return client.patch(f"/api/design/overhang/{overhang_id}", json=body)


@pytest.fixture(scope="module")
def design_native():
    return _make_stapled_6hb(42)


def _extrude(design: Design, site: dict, length_bp: int) -> tuple[Design, str, str]:
    """Returns (new_design, overhang_id, ovhg_helix_id)."""
    out = make_overhang_extrude(
        design,
        helix_id=site["helix_id"],
        bp_index=site["bp_index"],
        direction=site["direction"],
        is_five_prime=site["is_five_prime"],
        neighbor_row=site["neighbor_row"],
        neighbor_col=site["neighbor_col"],
        length_bp=length_bp,
    )
    orig_ids = {h.id for h in design.helices}
    new_helix = next(h for h in out.helices if h.id not in orig_ids)
    new_overhang = next(o for o in out.overhangs if o.helix_id == new_helix.id)
    return out, new_overhang.id, new_helix.id


def _ovhg_domain(design: Design, overhang_id: str):
    for s in design.strands:
        for d in s.domains:
            if d.overhang_id == overhang_id:
                return s, d
    raise AssertionError(f"overhang {overhang_id} domain not found")


@pytest.mark.parametrize("init_len,new_len", [(8, 12), (8, 5)])
def test_patch_overhang_extrude_resizes_tip_not_junction(
    design_native, init_len, new_len
):
    """For every extrude site on a 6HB, PATCHing a new sequence longer or
    shorter than the initial length must move the FREE TIP only.  The junction
    bp (where the crossover connects to the parent helix) must not move."""

    sites = _all_overhang_sites(design_native)
    assert sites

    failures: list[str] = []
    for site in sites:
        d8, ovhg_id, ovhg_helix_id = _extrude(design_native, site, init_len)
        # Junction bp on the overhang helix == site["bp_index"] (by construction).
        junction_bp = site["bp_index"]

        # Pre-state
        _pre_strand, pre_dom = _ovhg_domain(d8, ovhg_id)
        # Tip bp = whichever of (start_bp, end_bp) is NOT the junction
        pre_endpoints = {pre_dom.start_bp, pre_dom.end_bp}
        assert junction_bp in pre_endpoints, (
            f"site {site['helix_id']} bp={site['bp_index']}: junction bp "
            f"{junction_bp} not in domain endpoints {pre_endpoints}"
        )
        pre_tip_bp = next(bp for bp in pre_endpoints if bp != junction_bp)

        # Patch via the API
        _load_design(d8)
        seq = "ACGT" * 4  # 16
        seq = ("ACGTACGTACGTACGT")[:new_len]
        resp = _post_patch(ovhg_id, seq)
        assert resp.status_code == 200, (
            f"PATCH failed for site {site}: {resp.status_code} {resp.text}"
        )

        # Re-fetch active design
        post_design = design_state.get_or_404()
        _post_strand, post_dom = _ovhg_domain(post_design, ovhg_id)

        post_endpoints = {post_dom.start_bp, post_dom.end_bp}

        # Junction must still be in the domain endpoints AND at the same bp.
        if junction_bp not in post_endpoints:
            failures.append(
                f"site {site['helix_id']} bp={site['bp_index']} "
                f"5p={site['is_five_prime']} dir={site['direction'].value}: "
                f"junction bp {junction_bp} LOST from domain endpoints "
                f"(pre={pre_endpoints}, post={post_endpoints})"
            )
            continue

        # The tip bp should change by (new_len − init_len) bp away from junction.
        post_tip_bp = next(bp for bp in post_endpoints if bp != junction_bp)
        delta = new_len - init_len
        # tip moved AWAY from junction: |post_tip - junction| = |pre_tip - junction| + delta
        old_dist = abs(pre_tip_bp - junction_bp)
        new_dist = abs(post_tip_bp - junction_bp)
        if new_dist != old_dist + delta:
            failures.append(
                f"site {site['helix_id']} bp={site['bp_index']} "
                f"5p={site['is_five_prime']} dir={site['direction'].value}: "
                f"tip distance from junction changed by {new_dist - old_dist} "
                f"bp; expected {delta} (pre={pre_endpoints}, post={post_endpoints})"
            )

    assert not failures, (
        "patch_overhang resized the wrong end:\n  " + "\n  ".join(failures)
    )


def test_patch_overhang_extrude_helix_length_grows(design_native):
    """The overhang helix's length_bp must equal the new sequence length after
    a sequence-set patch, and bp_start must be consistent so the junction bp
    remains in the helix's bp range."""
    sites = _all_overhang_sites(design_native)
    assert sites

    failures: list[str] = []
    for site in sites:
        d8, ovhg_id, ovhg_helix_id = _extrude(design_native, site, 8)
        _load_design(d8)
        seq = "A" * 12
        resp = _post_patch(ovhg_id, seq)
        assert resp.status_code == 200, resp.text
        post_design = design_state.get_or_404()
        post_helix = next(h for h in post_design.helices if h.id == ovhg_helix_id)

        if post_helix.length_bp != 12:
            failures.append(
                f"site {site['helix_id']} bp={site['bp_index']}: helix length "
                f"is {post_helix.length_bp}, expected 12"
            )
            continue
        # Junction must still fall within the helix's bp range
        lo = post_helix.bp_start
        hi = post_helix.bp_start + post_helix.length_bp - 1
        if not (lo <= site["bp_index"] <= hi):
            failures.append(
                f"site {site['helix_id']} bp={site['bp_index']}: junction bp "
                f"{site['bp_index']} fell outside resized helix bp range [{lo}, {hi}]"
            )

    assert not failures, "helix resize broke junction containment:\n  " + "\n  ".join(failures)
