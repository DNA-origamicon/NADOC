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
from backend.core.constants import BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_DEG, BDNA_TWIST_PER_BP_RAD, SQUARE_TWIST_PER_BP_RAD
from backend.core.lattice import honeycomb_position, square_position
from backend.core.models import LatticeType, StrandType, Direction


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

    def test_hc_twist_is_bdna(self, client):
        """HC helix gets B-DNA twist per bp (34.3°/bp)."""
        _make_hc_design(client)
        r = client.post('/api/design/helix-at-cell', json={'row': 0, 'col': 0})
        h = r.json()['design']['helices'][0]
        assert abs(h['twist_per_bp_rad'] - BDNA_TWIST_PER_BP_RAD) < 1e-8

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
