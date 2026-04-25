"""Tests for blunt-end position correctness.

A blunt end is expected at:
  • Every free physical helix endpoint (no other helix within TOL).
  • Every strand 5′/3′ terminus that falls strictly inside a helix's physical bp range.

The helper functions in scripts/blunt_ends_report.py implement the canonical computation.
These tests verify:
  1. No duplicate (helix_id, bp) entries in the result.
  2. Every entry's bp lies within [h.bp_start, phys_end_bp].
  3. Every entry's 3-D coordinate lies on the helix axis (within 0.01 nm).
  4. Free-endpoint entries correspond exactly to helix endpoints with no neighbour.
  5. Interior entries correspond exactly to strand termini strictly inside the helix.
  6. No interior entry duplicates a free-endpoint entry.
  7. Known snapshot counts for specific designs (hinge, 6HB HC, Voltron).
"""
from __future__ import annotations

import json, math, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest

from scripts.blunt_ends_report import (
    compute_blunt_ends,
    compute_occupied_intervals,
    phys_end_bp,
    phys_len,
    axis_point,
    dist3,
    TOL,
    RISE,
)

# ── Design loading ─────────────────────────────────────────────────────────────

EXAMPLES = pathlib.Path(__file__).parent.parent / "Examples"
CADNANO  = EXAMPLES / "cadnano"

def _load(path: pathlib.Path):
    from backend.core.lattice    import autodetect_all_overhangs
    from backend.api.crud        import _recenter_design
    if str(path).endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        d, _ = import_scadnano(json.loads(path.read_text()))
    else:
        from backend.core.cadnano import import_cadnano
        d, _ = import_cadnano(json.loads(path.read_text()))
    d = autodetect_all_overhangs(d)
    d = _recenter_design(d)
    return d


DESIGNS = {
    '6hb':   CADNANO / 'Honeycomb_6hb_test1.json',
    'hinge': CADNANO / 'Ultimate Polymer Hinge 191016.json',
    'voltron': EXAMPLES / 'Voltron_Core_Arm_V6.sc',
}


@pytest.fixture(scope='module', params=list(DESIGNS.keys()))
def design_and_blunt_ends(request):
    path   = DESIGNS[request.param]
    design = _load(path)
    be     = compute_blunt_ends(design)
    return design, be, request.param


# ── Structural invariants (all designs) ───────────────────────────────────────

class TestStructuralInvariants:
    """Invariants that must hold for every design."""

    def test_no_duplicate_helix_bp(self, design_and_blunt_ends):
        _, be, name = design_and_blunt_ends
        seen = set()
        for e in be:
            key = (e['helix_id'], e['bp'])
            assert key not in seen, \
                f"{name}: duplicate blunt end at helix {e['label']} bp {e['bp']}"
            seen.add(key)

    def test_bp_within_physical_range(self, design_and_blunt_ends):
        design, be, name = design_and_blunt_ends
        hmap = {h.id: h for h in design.helices}
        for e in be:
            h  = hmap[e['helix_id']]
            pe = phys_end_bp(h)
            assert h.bp_start <= e['bp'] <= pe, \
                (f"{name}: blunt end at helix {e['label']} bp {e['bp']} "
                 f"outside physical range [{h.bp_start}, {pe}]")

    def test_xyz_on_axis(self, design_and_blunt_ends):
        """Each (x,y,z) must lie on the linear interpolation of the helix axis."""
        design, be, name = design_and_blunt_ends
        hmap = {h.id: h for h in design.helices}
        for e in be:
            h   = hmap[e['helix_id']]
            exp = axis_point(h, e['bp'])
            d   = dist3((e['x'], e['y'], e['z']), exp)
            assert d < 0.01, \
                (f"{name}: blunt end at helix {e['label']} bp {e['bp']} "
                 f"has 3-D position ({e['x']:.3f},{e['y']:.3f},{e['z']:.3f}) "
                 f"but axis gives ({exp[0]:.3f},{exp[1]:.3f},{exp[2]:.3f}), dist={d:.4f}")

    def test_type_values(self, design_and_blunt_ends):
        _, be, name = design_and_blunt_ends
        valid = {'free_start', 'free_end', 'interior', 'overhang_xover'}
        for e in be:
            assert e['type'] in valid, \
                f"{name}: unknown type {e['type']!r} at helix {e['label']} bp {e['bp']}"

    def test_no_interior_at_physical_endpoint(self, design_and_blunt_ends):
        """Interior entries must be strictly inside the physical bp range."""
        design, be, name = design_and_blunt_ends
        hmap = {h.id: h for h in design.helices}
        for e in be:
            if e['type'] != 'interior':
                continue
            h  = hmap[e['helix_id']]
            pe = phys_end_bp(h)
            assert e['bp'] > h.bp_start, \
                f"{name}: interior at helix {e['label']} bp == bp_start"
            assert e['bp'] < pe, \
                f"{name}: interior at helix {e['label']} bp == phys_end_bp"


# ── Semantic invariants: free endpoints ───────────────────────────────────────

class TestFreeEndpoints:

    def test_all_free_endpoints_present(self, design_and_blunt_ends):
        """Every free physical helix endpoint must appear in the blunt-end list."""
        design, be, name = design_and_blunt_ends
        helices = design.helices
        ep = {h.id: {
            'start': (h.axis_start.x, h.axis_start.y, h.axis_start.z),
            'end':   (h.axis_end.x,   h.axis_end.y,   h.axis_end.z),
        } for h in helices}

        def is_free(hid, which):
            pos = ep[hid][which]
            for other in helices:
                if other.id == hid:
                    continue
                if dist3(pos, ep[other.id]['start']) < TOL: return False
                if dist3(pos, ep[other.id]['end'])   < TOL: return False
            return True

        be_set = {(e['helix_id'], e['bp']) for e in be}
        for h in helices:
            if is_free(h.id, 'start'):
                assert (h.id, h.bp_start) in be_set, \
                    f"{name}: missing free_start at helix {h.label or h.id} bp {h.bp_start}"
            if is_free(h.id, 'end'):
                pe = phys_end_bp(h)
                assert (h.id, pe) in be_set, \
                    f"{name}: missing free_end at helix {h.label or h.id} bp {pe}"

    def test_no_blocked_endpoint_listed(self, design_and_blunt_ends):
        """No free_start/free_end entry for a BLOCKED endpoint (coincides with another)."""
        design, be, name = design_and_blunt_ends
        helices = design.helices
        ep = {h.id: {
            'start': (h.axis_start.x, h.axis_start.y, h.axis_start.z),
            'end':   (h.axis_end.x,   h.axis_end.y,   h.axis_end.z),
        } for h in helices}

        def is_free(hid, which):
            pos = ep[hid][which]
            for other in helices:
                if other.id == hid:
                    continue
                if dist3(pos, ep[other.id]['start']) < TOL: return False
                if dist3(pos, ep[other.id]['end'])   < TOL: return False
            return True

        hmap = {h.id: h for h in helices}
        for e in be:
            if e['type'] not in ('free_start', 'free_end'):
                continue
            h     = hmap[e['helix_id']]
            which = 'start' if e['type'] == 'free_start' else 'end'
            assert is_free(e['helix_id'], which), \
                (f"{name}: {e['type']} listed for BLOCKED endpoint "
                 f"at helix {e['label']} bp {e['bp']}")


# ── Semantic invariants: interior strand termini ───────────────────────────────

class TestInteriorTermini:

    def test_all_interior_termini_present(self, design_and_blunt_ends):
        """Every strand terminus strictly inside a helix must appear as an interior entry."""
        design, be, name = design_and_blunt_ends
        hmap   = {h.id: h for h in design.helices}
        be_set = {(e['helix_id'], e['bp']) for e in be}

        for strand in design.strands:
            checks = [
                (strand.domains[0].helix_id,   strand.domains[0].start_bp),
                (strand.domains[-1].helix_id,  strand.domains[-1].end_bp),
            ]
            for hid, bp in checks:
                if hid is None or bp is None:
                    continue
                h  = hmap.get(hid)
                if h is None:
                    continue
                pe = phys_end_bp(h)
                if h.bp_start < bp < pe:
                    assert (hid, bp) in be_set, \
                        (f"{name}: interior strand terminus at helix "
                         f"{h.label or hid} bp {bp} missing from blunt-end list")

    def test_interior_entries_are_strand_termini(self, design_and_blunt_ends):
        """Every interior entry must correspond to an actual strand 5′/3′ terminus."""
        design, be, name = design_and_blunt_ends
        hmap = {h.id: h for h in design.helices}

        # Build set of actual strand termini per helix
        termini: dict[tuple[str, int], bool] = {}
        for strand in design.strands:
            checks = [
                (strand.domains[0].helix_id,   strand.domains[0].start_bp),
                (strand.domains[-1].helix_id,  strand.domains[-1].end_bp),
            ]
            for hid, bp in checks:
                if hid is not None and bp is not None:
                    termini[(hid, bp)] = True

        for e in be:
            if e['type'] != 'interior':
                continue
            assert (e['helix_id'], e['bp']) in termini, \
                (f"{name}: interior entry at helix {e['label']} bp {e['bp']} "
                 f"is not a strand 5′/3′ terminus")


# ── Semantic invariants: overhang crossovers ──────────────────────────────────

class TestOverhangCrossovers:

    def test_all_overhang_xovers_present(self, design_and_blunt_ends):
        """Every regular↔overhang crossover position on main helices must appear."""
        design, be, name = design_and_blunt_ends
        hmap   = {h.id: h for h in design.helices}
        be_set = {(e['helix_id'], e['bp']) for e in be}

        for strand in design.strands:
            doms = strand.domains
            for i in range(len(doms) - 1):
                d0, d1 = doms[i], doms[i + 1]
                if d0.helix_id == d1.helix_id:
                    continue
                # regular → overhang: main helix is d0
                if getattr(d0, 'overhang_id', None) is None and \
                   getattr(d1, 'overhang_id', None) is not None:
                    hid, bp = d0.helix_id, d0.end_bp
                    if hid is not None and bp is not None:
                        h = hmap.get(hid)
                        if h is not None and h.bp_start <= bp <= phys_end_bp(h):
                            assert (hid, bp) in be_set, \
                                (f"{name}: missing overhang_xover for regular→OH "
                                 f"at helix {h.label or hid} bp {bp}")
                # overhang → regular: main helix is d1
                if getattr(d0, 'overhang_id', None) is not None and \
                   getattr(d1, 'overhang_id', None) is None:
                    hid, bp = d1.helix_id, d1.start_bp
                    if hid is not None and bp is not None:
                        h = hmap.get(hid)
                        if h is not None and h.bp_start <= bp <= phys_end_bp(h):
                            assert (hid, bp) in be_set, \
                                (f"{name}: missing overhang_xover for OH→regular "
                                 f"at helix {h.label or hid} bp {bp}")

    def test_overhang_xover_entries_are_valid(self, design_and_blunt_ends):
        """Every overhang_xover entry must actually be a regular↔overhang crossover."""
        design, be, name = design_and_blunt_ends
        hmap = {h.id: h for h in design.helices}

        # Build set of valid crossover positions
        valid_xovers: set[tuple[str, int]] = set()
        for strand in design.strands:
            doms = strand.domains
            for i in range(len(doms) - 1):
                d0, d1 = doms[i], doms[i + 1]
                if d0.helix_id == d1.helix_id:
                    continue
                if getattr(d0, 'overhang_id', None) is None and \
                   getattr(d1, 'overhang_id', None) is not None:
                    if d0.helix_id is not None and d0.end_bp is not None:
                        valid_xovers.add((d0.helix_id, d0.end_bp))
                if getattr(d0, 'overhang_id', None) is not None and \
                   getattr(d1, 'overhang_id', None) is None:
                    if d1.helix_id is not None and d1.start_bp is not None:
                        valid_xovers.add((d1.helix_id, d1.start_bp))

        for e in be:
            if e['type'] != 'overhang_xover':
                continue
            assert (e['helix_id'], e['bp']) in valid_xovers, \
                (f"{name}: overhang_xover entry at helix {e['label']} bp {e['bp']} "
                 f"is not a regular↔overhang crossover")


# ── Snapshot counts for specific designs ──────────────────────────────────────

class TestSnapshotCounts:
    """Concrete expected counts derived from the blunt_ends_report.py tables.

    These pin the known-correct output.  If a count changes, something in the
    import pipeline or the helper logic has changed and needs review.
    """

    def _counts(self, design):
        be = compute_blunt_ends(design)
        return dict(
            total          = len(be),
            free_start     = sum(1 for e in be if e['type'] == 'free_start'),
            free_end       = sum(1 for e in be if e['type'] == 'free_end'),
            interior       = sum(1 for e in be if e['type'] == 'interior'),
            overhang_xover = sum(1 for e in be if e['type'] == 'overhang_xover'),
        )

    def test_6hb(self):
        """Simple 6-helix honeycomb: 6 free starts + 6 free ends, no interior."""
        d = _load(DESIGNS['6hb'])
        c = self._counts(d)
        assert c == dict(total=12, free_start=6, free_end=6, interior=0,
                         overhang_xover=0), \
            f"6HB counts wrong: {c}"

    def test_hinge(self):
        """Polymer hinge: all 74 helix endpoints are free; many interior termini; 36 overhang crossovers."""
        d = _load(DESIGNS['hinge'])
        c = self._counts(d)
        assert c['free_start']     == 74,  f"hinge free_start={c['free_start']}, expected 74"
        assert c['free_end']       == 74,  f"hinge free_end={c['free_end']}, expected 74"
        assert c['interior']       == 417, f"hinge interior={c['interior']}, expected 417"
        assert c['overhang_xover'] == 36,  f"hinge overhang_xover={c['overhang_xover']}, expected 36"
        assert c['total']          == 601, f"hinge total={c['total']}, expected 601"

    def test_voltron(self):
        """Voltron (multi-scaffold scadnano): all 65 endpoints free; 18 overhang crossovers."""
        d = _load(DESIGNS['voltron'])
        c = self._counts(d)
        assert c['free_start']     == 65,  f"voltron free_start={c['free_start']}, expected 65"
        assert c['free_end']       == 65,  f"voltron free_end={c['free_end']}, expected 65"
        assert c['interior']       == 692, f"voltron interior={c['interior']}, expected 692"
        assert c['overhang_xover'] == 18,  f"voltron overhang_xover={c['overhang_xover']}, expected 18"
        assert c['total']          == 840, f"voltron total={c['total']}, expected 840"


# ── Occupied-interval cross-check ─────────────────────────────────────────────

class TestOccupiedIntervals:

    def test_gap_boundary_blunt_ends_present(self, design_and_blunt_ends):
        """For every occupied-interval gap, the strand-terminus boundaries have blunt ends.

        Not all gap boundaries are strand termini (some are crossover entries).  This test
        only checks that gap boundaries which ARE strand termini have a blunt end.
        """
        design, be, name = design_and_blunt_ends
        hmap     = {h.id: h for h in design.helices}
        intervals = compute_occupied_intervals(design)
        be_set   = {(e['helix_id'], e['bp']) for e in be}

        # Build set of actual strand termini
        termini: set[tuple[str, int]] = set()
        for strand in design.strands:
            checks = [
                (strand.domains[0].helix_id,   strand.domains[0].start_bp),
                (strand.domains[-1].helix_id,  strand.domains[-1].end_bp),
            ]
            for hid, bp in checks:
                if hid is not None and bp is not None:
                    termini.add((hid, bp))

        for hid, ivs in intervals.items():
            h  = hmap[hid]
            pe = phys_end_bp(h)
            for i in range(len(ivs) - 1):
                gap_pre  = ivs[i][1]    # last bp before gap
                gap_post = ivs[i+1][0]  # first bp after gap
                for bp in (gap_pre, gap_post):
                    if h.bp_start < bp < pe and (hid, bp) in termini:
                        assert (hid, bp) in be_set, \
                            (f"{name}: gap-boundary strand terminus at helix "
                             f"{h.label or hid} bp {bp} has no blunt end")
