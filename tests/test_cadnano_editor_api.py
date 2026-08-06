"""
Tests for the two new cadnano 2D editor API endpoints:
  POST /design/helix-at-cell
  POST /design/scaffold-domain-paint

These form the backbone of the Phase 1 2D editor's interaction with the backend.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_DEG,
    HONEYCOMB_TWIST_PER_BP_RAD,
    SQUARE_TWIST_PER_BP_RAD,
)
from backend.core.lattice import honeycomb_position, square_position


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    """Start each test with a fresh HC demo design (no helices, no strands)."""
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


def _make_hc_design(client):
    """POST a new HC design, return it."""
    r = client.post('/api/design', json={'name': 'test', 'lattice_type': 'HONEYCOMB'})
    assert r.status_code == 201
    return r.json()


def _make_sq_design(client):
    """POST a new SQ design, return it."""
    r = client.post('/api/design', json={'name': 'test', 'lattice_type': 'SQUARE'})
    assert r.status_code == 201
    return r.json()


# ── POST /design/helix-at-cell ────────────────────────────────────────────────

class TestHelixAtCell:

    def test_hc_valid_cell_creates_helix(self, client):
        """A click on a valid HC cell adds a helix at the correct nm position."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        assert r.status_code == 201
        body = r.json()
        assert 'design' in body
        helices = body['design']['helices']
        assert len(helices) == 1
        h = helices[0]

        # Physical position matches honeycomb_position(0, 0)
        x_exp, y_exp = honeycomb_position(0, 0)
        assert abs(h['axis_start']['x'] - x_exp) < 1e-6
        assert abs(h['axis_start']['y'] - y_exp) < 1e-6
        assert abs(h['axis_start']['z']) < 1e-6

        # Default 42 bp length
        assert h['length_bp'] == 42
        length_nm = 42 * BDNA_RISE_PER_BP
        assert abs(h['axis_end']['z'] - length_nm) < 1e-6

        # grid_pos recorded
        assert h['grid_pos'] == [0, 0]

    def test_hc_phase_offset_forward_cell(self, client):
        """HC FORWARD cell (even parity) gets phase_offset=90°+17.15° (cadnano base + ½-bp HJ correction)."""
        _make_hc_design(client)
        # Cell (0,0): (0+0)%2 == 0 → even parity → FORWARD
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        h = r.json()['design']['helices'][0]
        assert abs(h['phase_offset'] - math.radians(90.0 + BDNA_TWIST_PER_BP_DEG / 2)) < 1e-5

    def test_hc_phase_offset_reverse_cell(self, client):
        """HC REVERSE cell (odd parity) gets phase_offset=60°+17.15° (cadnano base + ½-bp HJ correction)."""
        _make_hc_design(client)
        # Cell (1,0): (1+0)%2 == 1 → odd parity → REVERSE
        r = client.post('/api/design/helix-at-cell', json={'row': 1, 'col': 0})
        h = r.json()['design']['helices'][0]
        assert abs(h['phase_offset'] - math.radians(60.0 + BDNA_TWIST_PER_BP_DEG / 2)) < 1e-5

    def test_hc_twist_is_commensurate_with_the_21bp_repeat(self, client):
        """An HC helix gets the LATTICE twist (720/21 = 34.2857 deg/bp), not the rounded
        physical B-DNA constant (34.3).

        The lattice value has to close exactly over the 21-bp crossover period or the
        geometry does not repeat: at 34.3 the period came out 720.3 deg and crossover
        strain ramped +0.657 oxDNA units per 1000 bp, so two designs on the same lattice
        disagreed purely because one was longer (TD-29).
        """
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        h = r.json()['design']['helices'][0]
        assert abs(h['twist_per_bp_rad'] - HONEYCOMB_TWIST_PER_BP_RAD) < 1e-12
        assert abs(21 * h['twist_per_bp_rad'] - 4 * math.pi) < 1e-12, "21 bp must be 2 turns"

    def test_hc_custom_length_bp(self, client):
        """length_bp parameter is respected."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0, 'length_bp': 84})
        assert r.status_code == 201
        h = r.json()['design']['helices'][0]
        assert h['length_bp'] == 84

    def test_sq_valid_cell_creates_helix(self, client):
        """A click on a valid SQ cell adds a helix at the correct nm position."""
        _make_sq_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 2, 'col': 3})
        assert r.status_code == 201
        h = r.json()['design']['helices'][0]
        x_exp, y_exp = square_position(2, 3)
        assert abs(h['axis_start']['x'] - x_exp) < 1e-6
        assert abs(h['axis_start']['y'] - y_exp) < 1e-6
        assert h['grid_pos'] == [2, 3]

    def test_sq_twist_is_square(self, client):
        """SQ helix gets square-lattice twist per bp (33.75°/bp)."""
        _make_sq_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        h = r.json()['design']['helices'][0]
        assert abs(h['twist_per_bp_rad'] - SQUARE_TWIST_PER_BP_RAD) < 1e-8

    def test_response_includes_nucleotides(self, client):
        """Response embeds nucleotide geometry."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        body = r.json()
        assert 'nucleotides' in body
        # 42 bp × 2 strands = 84 nucleotides
        assert len(body['nucleotides']) == 84

    def test_default_no_strands(self, client):
        """Without populate_strands, the new helix has no strands (back-compat)."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        assert r.status_code == 201
        assert r.json()['design']['strands'] == []

    def test_populate_strands_forward_cell(self, client):
        """populate_strands=True on a FORWARD cell adds a 42bp scaffold + 42bp staple."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell',
                        json={'row': 0, 'col': 0, 'populate_strands': True})
        assert r.status_code == 201
        design = r.json()['design']
        helix_id = design['helices'][0]['id']
        strands  = design['strands']
        assert len(strands) == 2
        scaf = next(s for s in strands if s['strand_type'] == 'scaffold')
        stpl = next(s for s in strands if s['strand_type'] == 'staple')
        # Scaffold runs FORWARD (cell 0,0 is even-parity), full length
        scaf_dom = scaf['domains'][0]
        assert scaf_dom['helix_id'] == helix_id
        assert scaf_dom['direction'] == 'FORWARD'
        assert (scaf_dom['start_bp'], scaf_dom['end_bp']) == (0, 41)
        # Staple runs opposite (REVERSE), full length
        stpl_dom = stpl['domains'][0]
        assert stpl_dom['helix_id'] == helix_id
        assert stpl_dom['direction'] == 'REVERSE'
        assert (stpl_dom['start_bp'], stpl_dom['end_bp']) == (41, 0)

    def test_populate_strands_reverse_cell(self, client):
        """populate_strands on a REVERSE cell flips scaffold/staple directions."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell',
                        json={'row': 1, 'col': 0, 'populate_strands': True, 'length_bp': 21})
        assert r.status_code == 201
        strands = r.json()['design']['strands']
        scaf = next(s for s in strands if s['strand_type'] == 'scaffold')
        stpl = next(s for s in strands if s['strand_type'] == 'staple')
        assert scaf['domains'][0]['direction'] == 'REVERSE'
        assert (scaf['domains'][0]['start_bp'], scaf['domains'][0]['end_bp']) == (20, 0)
        assert stpl['domains'][0]['direction'] == 'FORWARD'
        assert (stpl['domains'][0]['start_bp'], stpl['domains'][0]['end_bp']) == (0, 20)

    def test_populate_strands_visible_in_geometry(self, client):
        """Auto-populated strands show up in /design/geometry with correct strand_id —
        this is what the 3D view consumes to render scaffold + staple bead chains."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell',
                        json={'row': 0, 'col': 0, 'populate_strands': True})
        assert r.status_code == 201
        design = r.json()['design']
        scaf_id = next(s['id'] for s in design['strands'] if s['strand_type'] == 'scaffold')
        stpl_id = next(s['id'] for s in design['strands'] if s['strand_type'] == 'staple')

        g = client.get('/api/design/geometry')
        assert g.status_code == 200
        nucs = g.json()['nucleotides']
        # 42 bp × 2 directions = 84 nucleotides, every one tagged with a strand_id
        assert len(nucs) == 84
        scaf_nucs = [n for n in nucs if n['strand_id'] == scaf_id]
        stpl_nucs = [n for n in nucs if n['strand_id'] == stpl_id]
        assert len(scaf_nucs) == 42
        assert len(stpl_nucs) == 42
        assert all(n['strand_id'] is not None for n in nucs)
        # Scaffold strand is FORWARD on cell (0,0); staple is REVERSE
        assert all(n['direction'] == 'FORWARD' for n in scaf_nucs)
        assert all(n['direction'] == 'REVERSE' for n in stpl_nucs)

    def test_adjacent_helix_no_offset_matches_lattice(self, client):
        """On a fresh (un-shifted) design, a second helix added next to the first
        still lands at the raw lattice position — adjacency logic is a no-op when
        the existing helices already sit at _lattice_position. And it's empty."""
        _make_hc_design(client)
        client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        r = client.post('/api/design/helix-at-cell', json={'row': 1, 'col': 0})
        assert r.status_code == 201
        design = r.json()['design']
        new = design['helices'][-1]
        x_exp, y_exp = honeycomb_position(1, 0)
        assert abs(new['axis_start']['x'] - x_exp) < 1e-6
        assert abs(new['axis_start']['y'] - y_exp) < 1e-6
        assert abs(new['axis_start']['z']) < 1e-6
        assert new['length_bp'] == 42
        assert new['bp_start'] == 0
        assert design['strands'] == []           # empty — no auto scaffold/staple

    def test_adjacent_to_offset_neighbor(self, client):
        """A cell-click on a re-centered/imported design (helices NOT at the raw
        lattice position, nonzero bp_start, custom length) places the new helix
        adjacent to its nearest neighbour: XY offset from that neighbour's real
        axis, and co-extensive in Z + bp_start + length so the tracks line up."""
        from backend.core.models import Vec3
        _make_hc_design(client)
        r0 = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        ref_id = r0.json()['design']['helices'][0]['id']

        # Simulate an imported / re-centered design: shift the reference helix off
        # the lattice formula, with a nonzero bp_start and a non-default length.
        DX, DY, Z0, RISE = 5.0, 7.0, 3.0, BDNA_RISE_PER_BP
        d = design_state.get_or_404()
        ref = d.find_helix(ref_id)
        ref.axis_start = Vec3(x=ref.axis_start.x + DX, y=ref.axis_start.y + DY, z=Z0)
        ref.axis_end   = Vec3(x=ref.axis_end.x   + DX, y=ref.axis_end.y   + DY, z=Z0 + 29 * RISE)
        ref.bp_start   = 16
        ref.length_bp  = 30
        rx0, ry0 = ref.axis_start.x, ref.axis_start.y   # capture before the call

        r = client.post('/api/design/helix-at-cell', json={'row': 1, 'col': 0})
        assert r.status_code == 201
        design = r.json()['design']
        new = design['helices'][-1]

        fx0, fy0 = honeycomb_position(0, 0)
        fx1, fy1 = honeycomb_position(1, 0)
        # XY offset measured from the reference's REAL axis, not the raw formula.
        assert abs(new['axis_start']['x'] - (rx0 + (fx1 - fx0))) < 1e-6
        assert abs(new['axis_start']['y'] - (ry0 + (fy1 - fy0))) < 1e-6
        # Co-extensive in Z, and inherits bp window + length.
        assert abs(new['axis_start']['z'] - Z0) < 1e-6
        assert abs(new['axis_end']['z'] - (Z0 + 29 * RISE)) < 1e-6
        assert new['bp_start'] == 16
        assert new['length_bp'] == 30
        assert design['strands'] == []


# ── POST /design/scaffold-domain-paint ───────────────────────────────────────

class TestScaffoldDomainPaint:

    def _add_cell(self, client, row, col, length_bp=42):
        r = client.post('/api/design/helix-at-cell', json={'row': row, 'col': col, 'length_bp': length_bp})
        assert r.status_code == 201
        return r.json()['design']['helices'][-1]

    def test_paint_forward_domain(self, client):
        """Painting on a FORWARD helix creates a FORWARD scaffold domain."""
        _make_hc_design(client)
        h = self._add_cell(client, 0, 0)   # cell (0,0) → FORWARD
        helix_id = h['id']

        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': helix_id, 'lo_bp': 0, 'hi_bp': 20})
        assert r.status_code == 201
        design = r.json()['design']

        scaffolds = [s for s in design['strands'] if s['strand_type'] == 'scaffold']
        assert len(scaffolds) == 1
        dom = scaffolds[0]['domains'][0]
        assert dom['helix_id'] == helix_id
        assert dom['direction'] == 'FORWARD'
        # FORWARD: start_bp=lo, end_bp=hi (5'→3' left-to-right)
        assert dom['start_bp'] == 0
        assert dom['end_bp']   == 20

    def test_paint_reverse_domain(self, client):
        """Painting on a REVERSE helix creates a REVERSE scaffold domain with correct polarity."""
        _make_hc_design(client)
        h = self._add_cell(client, 1, 0)   # cell (1,0) → REVERSE
        helix_id = h['id']

        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': helix_id, 'lo_bp': 5, 'hi_bp': 30})
        assert r.status_code == 201
        design = r.json()['design']

        scaffolds = [s for s in design['strands'] if s['strand_type'] == 'scaffold']
        assert len(scaffolds) == 1
        dom = scaffolds[0]['domains'][0]
        assert dom['direction'] == 'REVERSE'
        # REVERSE: start_bp=hi (5' end is at higher index), end_bp=lo
        assert dom['start_bp'] == 30
        assert dom['end_bp']   == 5

    def test_domain_nt_count(self, client):
        """Painted domain has the correct nucleotide count (hi-lo+1)."""
        _make_hc_design(client)
        h = self._add_cell(client, 0, 0)
        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': h['id'], 'lo_bp': 10, 'hi_bp': 19})
        assert r.status_code == 201
        dom = r.json()['design']['strands'][0]['domains'][0]
        assert abs(dom['end_bp'] - dom['start_bp']) + 1 == 10

    def test_overlap_rejected(self, client):
        """Painting over an existing scaffold domain returns 409."""
        _make_hc_design(client)
        h = self._add_cell(client, 0, 0)
        hid = h['id']
        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': hid, 'lo_bp': 0, 'hi_bp': 20})
        assert r.status_code == 201
        # Same range → conflict
        r2 = client.post('/api/design/scaffold-domain-paint',
                         json={'helix_id': hid, 'lo_bp': 10, 'hi_bp': 30})
        assert r2.status_code == 409

    def test_non_overlapping_paint_allowed(self, client):
        """Two non-overlapping segments on the same helix are both accepted."""
        _make_hc_design(client)
        h = self._add_cell(client, 0, 0)
        hid = h['id']
        r1 = client.post('/api/design/scaffold-domain-paint',
                         json={'helix_id': hid, 'lo_bp': 0, 'hi_bp': 10})
        assert r1.status_code == 201
        r2 = client.post('/api/design/scaffold-domain-paint',
                         json={'helix_id': hid, 'lo_bp': 15, 'hi_bp': 25})
        assert r2.status_code == 201
        design = r2.json()['design']
        scaffolds = [s for s in design['strands'] if s['strand_type'] == 'scaffold']
        assert len(scaffolds) == 2

    def test_out_of_bounds_clamped(self, client):
        """bp range that extends beyond helix bounds is silently clamped."""
        _make_hc_design(client)
        h = self._add_cell(client, 0, 0, length_bp=42)   # bp 0..41
        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': h['id'], 'lo_bp': -5, 'hi_bp': 50})
        assert r.status_code == 201
        dom = r.json()['design']['strands'][0]['domains'][0]
        lo = min(dom['start_bp'], dom['end_bp'])
        hi = max(dom['start_bp'], dom['end_bp'])
        assert lo == 0
        assert hi == 41

    def test_unknown_helix_returns_404(self, client):
        """Painting on a non-existent helix ID returns 404."""
        _make_hc_design(client)
        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': 'does-not-exist', 'lo_bp': 0, 'hi_bp': 10})
        assert r.status_code == 404

    def test_sq_paint(self, client):
        """Painting on a SQ design cell creates the correct strand."""
        _make_sq_design(client)
        h = self._add_cell(client, 0, 0)   # (0,0) → FORWARD in SQ
        r = client.post('/api/design/scaffold-domain-paint',
                        json={'helix_id': h['id'], 'lo_bp': 0, 'hi_bp': 31})
        assert r.status_code == 201
        dom = r.json()['design']['strands'][0]['domains'][0]
        assert dom['direction'] == 'FORWARD'
        assert dom['start_bp'] == 0
        assert dom['end_bp']   == 31


# ── X-NADOC-Skip-Geometry header ────────────────────────────────────────────
# The 2D editor draws from topology and never reads embedded 3D geometry, so it
# sends X-NADOC-Skip-Geometry to drop the full-design geometry recompute + the
# multi-MB nucleotide payload it would discard. Routes that build responses via
# _design_response_with_geometry must omit geometry when the header is present,
# and ship it (as before) when it's absent.

class TestSkipGeometryHeader:

    _GEOM_KEYS = ('nucleotides', 'nucleotides_compact', 'helix_axes',
                  'partial_geometry', 'changed_helix_ids')

    def _setup_nickable_helix(self, client):
        _make_hc_design(client)
        # populate_strands so the helix carries a full-length scaffold to nick.
        r = client.post('/api/design/helix-at-cell',
                        json={'row': 0, 'col': 0, 'populate_strands': True})
        assert r.status_code == 201
        return r.json()['design']['helices'][-1]['id']

    def test_no_header_ships_geometry(self, client):
        """A mutation through _design_response_with_geometry embeds geometry by default."""
        hid = self._setup_nickable_helix(client)
        r = client.post('/api/design/nick',
                        json={'helix_id': hid, 'bp_index': 20, 'direction': 'FORWARD'})
        assert r.status_code == 201
        js = r.json()
        assert any(k in js for k in self._GEOM_KEYS), js.keys()

    def test_header_omits_geometry_but_keeps_design(self, client):
        """With X-NADOC-Skip-Geometry the same mutation returns the design + validation
        only — no embedded geometry payload."""
        hid = self._setup_nickable_helix(client)
        r = client.post('/api/design/nick',
                        json={'helix_id': hid, 'bp_index': 20, 'direction': 'FORWARD'},
                        headers={'X-NADOC-Skip-Geometry': '1'})
        assert r.status_code == 201
        js = r.json()
        assert not any(k in js for k in self._GEOM_KEYS), js.keys()
        assert js.get('design') and js['design']['helices']    # topology preserved
        assert 'validation' in js

    def test_falsey_header_value_still_ships_geometry(self, client):
        """A '0' / 'false' header value is treated as not-set (geometry shipped)."""
        hid = self._setup_nickable_helix(client)
        r = client.post('/api/design/nick',
                        json={'helix_id': hid, 'bp_index': 20, 'direction': 'FORWARD'},
                        headers={'X-NADOC-Skip-Geometry': '0'})
        assert r.status_code == 201
        assert any(k in r.json() for k in self._GEOM_KEYS)
