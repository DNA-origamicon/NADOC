"""
Tests for single crossover placement via POST /design/crossovers/place.

The crossover flow is pure lookup-table driven:
  1. The sprite knows (helix_a, helix_b, bp, dirA, dirB, isScaffold).
  2. bowDir = bp % period in BOW_RIGHT_SET → +1, else -1.
  3. lowerBp = bp - 1 if bowDir == +1, else bp.
  4. nickBp_FWD = lowerBp, nickBp_REV = lowerBp + 1.
  5. Backend: nick → ligate → register crossover record.  Zero geometric reasoning.
     Strands are ligated into multi-domain oligos at crossover boundaries.

HC offset table reminder (cadnano2):
  Each bp mod 21 maps to a SPECIFIC neighbor cell.  Not all bp positions
  are valid between every helix pair — only those whose offset matches.

  Staple:  bp 6,7 → (0,±1) between col-adjacent cells
           bp 13,14 → (∓1,0) between row-adjacent cells
           bp 0,20 → (0,∓1) between col-adjacent cells (opposite direction to 6,7)
  Scaffold: bp 1,2,11,12 → (0,±1) col-adjacent
            bp 5,8,9,16  → via other neighbor directions
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.models import StrandType


client = TestClient(app)

# HC cadnano2 bow-right lookup — the ONLY constants driving nick computation.
HC_PERIOD = 21
HC_STAP_BOW_RIGHT = frozenset({0, 7, 14})
HC_SCAF_BOW_RIGHT = frozenset({2, 5, 9, 12, 16, 19})


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_bundle(cells, length_bp=42):
    r = client.post("/api/design/bundle", json={
        "cells": cells, "length_bp": length_bp, "plane": "XY",
    })
    assert r.status_code == 201
    return r.json()["design"]


def _hid_at(design, row, col):
    return next(h["id"] for h in design["helices"] if h["grid_pos"] == [row, col])


def _nick_positions(bp, dir_a, dir_b, is_scaffold=False):
    """Pure table lookup — same logic as frontend pathview.js."""
    bow_right = HC_SCAF_BOW_RIGHT if is_scaffold else HC_STAP_BOW_RIGHT
    bow_dir = +1 if (bp % HC_PERIOD) in bow_right else -1
    lower_bp = bp - 1 if bow_dir == +1 else bp
    nick_a = lower_bp if dir_a == "FORWARD" else lower_bp + 1
    nick_b = lower_bp if dir_b == "FORWARD" else lower_bp + 1
    return nick_a, nick_b


def _staple_dirs(row_a, col_a):
    """Return (dir_on_A, dir_on_B) for a staple crossover from cell (row_a, col_a).
    Even parity: scaffold=FWD → staple=REV.  Odd: scaffold=REV → staple=FWD."""
    even_a = (row_a + col_a) % 2 == 0
    return ("REVERSE" if even_a else "FORWARD",
            "FORWARD" if even_a else "REVERSE")


def _scaffold_dirs(row_a, col_a):
    even_a = (row_a + col_a) % 2 == 0
    return ("FORWARD" if even_a else "REVERSE",
            "REVERSE" if even_a else "FORWARD")


def _place(hid_a, hid_b, bp, dir_a, dir_b, is_scaffold=False):
    nick_a, nick_b = _nick_positions(bp, dir_a, dir_b, is_scaffold)
    return client.post("/api/design/crossovers/place", json={
        "half_a": {"helix_id": hid_a, "index": bp, "strand": dir_a},
        "half_b": {"helix_id": hid_b, "index": bp, "strand": dir_b},
        "nick_bp_a": nick_a,
        "nick_bp_b": nick_b,
    })


def _cross_helix_strands(design, hid_a, hid_b, strand_type=None):
    result = []
    for s in design["strands"]:
        if strand_type and s["strand_type"] != strand_type:
            continue
        hids = {d["helix_id"] for d in s["domains"]}
        if hid_a in hids and hid_b in hids:
            result.append(s)
    return result


# ── HC staple crossovers: col-adjacent cells (0,0)↔(0,1) ───────────────────
# Valid staple bps between these cells: 6, 7 (and +21n repeats: 27, 28)

class TestHCStapleColAdjacent:

    @pytest.mark.parametrize("bp", [6, 7, 27, 28])
    def test_crossover_registered(self, bp):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, bp, da, db)
        assert r.status_code == 201, f"bp={bp}: {r.json().get('detail')}"

        result = r.json()["design"]
        assert len(result["crossovers"]) == 1
        xo = result["crossovers"][0]
        assert xo["half_a"]["helix_id"] == ha
        assert xo["half_b"]["helix_id"] == hb
        assert xo["half_a"]["index"] == bp
        assert xo["half_b"]["index"] == bp

    @pytest.mark.parametrize("bp", [6, 7, 27, 28])
    def test_strands_become_multi_domain(self, bp):
        """Crossover ligates two single-helix strands into one multi-domain strand."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, bp, da, db)
        assert r.status_code == 201

        result = r.json()["design"]
        cross = _cross_helix_strands(result, ha, hb)
        assert len(cross) == 1, f"bp={bp}: expected one multi-domain strand spanning both helices"
        assert len(cross[0]["domains"]) == 2, f"bp={bp}: expected 2 domains in ligated strand"

    @pytest.mark.parametrize("bp", [6, 7, 27, 28])
    def test_scaffold_untouched_by_staple_xover(self, bp):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, bp, da, db)
        assert r.status_code == 201

        result = r.json()["design"]
        cross_scaf = _cross_helix_strands(result, ha, hb, "scaffold")
        assert len(cross_scaf) == 0, f"bp={bp}: scaffold spans both helices!"


# ── HC staple crossovers: row-adjacent cells ────────────────────────────────
# bp 13,14 from even cell → (-1,0).  Use cells (2,0) even and (1,0) odd.

class TestHCStapleRowAdjacent:

    @pytest.mark.parametrize("bp", [13, 14, 34, 35])
    def test_crossover_at_row_neighbor(self, bp):
        design = _make_bundle([[2, 0], [1, 0]])
        ha, hb = _hid_at(design, 2, 0), _hid_at(design, 1, 0)
        da, db = _staple_dirs(2, 0)

        r = _place(ha, hb, bp, da, db)
        assert r.status_code == 201, f"bp={bp}: {r.json().get('detail')}"

        result = r.json()["design"]
        assert len(result["crossovers"]) == 1


# ── HC staple: bp 0,20 (col-adjacent, opposite direction) ──────────────────
# Cell (1,0) is odd.  bp 0 → (0,+1) = (1,1).  Cell (1,1) is even.

class TestHCStapleBP0And20:

    @pytest.mark.parametrize("bp", [0, 20, 21, 41])
    def test_crossover_at_bp0_family(self, bp):
        design = _make_bundle([[1, 1], [1, 0]])
        ha, hb = _hid_at(design, 1, 1), _hid_at(design, 1, 0)
        da, db = _staple_dirs(1, 1)

        r = _place(ha, hb, bp, da, db)
        assert r.status_code == 201, f"bp={bp}: {r.json().get('detail')}"

        result = r.json()["design"]
        assert len(result["crossovers"]) == 1


# ── HC scaffold crossovers ──────────────────────────────────────────────────
# Between (0,0)↔(0,1): scaffold bps 1, 2, 11, 12

class TestHCScaffoldCrossovers:

    @pytest.mark.parametrize("bp", [1, 2, 11, 12])
    def test_scaffold_crossover(self, bp):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _scaffold_dirs(0, 0)

        r = _place(ha, hb, bp, da, db, is_scaffold=True)
        assert r.status_code == 201, f"bp={bp}: {r.json().get('detail')}"

        result = r.json()["design"]
        assert len(result["crossovers"]) == 1
        xo = result["crossovers"][0]
        assert xo["half_a"]["strand"] == da
        assert xo["half_b"]["strand"] == db

    @pytest.mark.parametrize("bp", [1, 2, 11, 12])
    def test_staples_untouched_by_scaffold_xover(self, bp):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _scaffold_dirs(0, 0)

        r = _place(ha, hb, bp, da, db, is_scaffold=True)
        assert r.status_code == 201

        result = r.json()["design"]
        cross_stap = _cross_helix_strands(result, ha, hb, "staple")
        assert len(cross_stap) == 0, f"bp={bp}: staple spans both helices!"


# ── Same-type enforcement ───────────────────────────────────────────────────

class TestSameTypeEnforcement:

    def test_reject_scaffold_to_staple(self):
        """Sending scaffold direction on one helix and staple direction on the
        other must be rejected — crossovers only connect same-type strands."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)

        # Even: scaffold=FORWARD, staple=REVERSE
        # Odd:  scaffold=REVERSE, staple=FORWARD
        # Send FORWARD on both → scaffold on even, staple on odd → cross-type
        r = client.post("/api/design/crossovers/place", json={
            "half_a": {"helix_id": ha, "index": 7, "strand": "FORWARD"},
            "half_b": {"helix_id": hb, "index": 7, "strand": "FORWARD"},
            "nick_bp_a": 6,
            "nick_bp_b": 6,
        })
        assert r.status_code == 400
        assert "same strand type" in r.json()["detail"].lower()


# ── Multiple crossovers ─────────────────────────────────────────────────────

class TestMultipleCrossovers:

    def test_two_staple_crossovers(self):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r1 = _place(ha, hb, 6, da, db)
        assert r1.status_code == 201
        r2 = _place(ha, hb, 7, da, db)
        assert r2.status_code == 201

        result = r2.json()["design"]
        assert len(result["crossovers"]) == 2

    def test_holliday_junction_preserves_coverage(self):
        """Adjacent crossovers (bp 6+7) form a Holliday junction.
        No nucleotides may be lost or created at any step."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        def _coverage(d):
            cov = set()
            for s in d["strands"]:
                for dom in s["domains"]:
                    lo = min(dom["start_bp"], dom["end_bp"])
                    hi = max(dom["start_bp"], dom["end_bp"])
                    for bp in range(lo, hi + 1):
                        cov.add((dom["helix_id"], bp, dom["direction"]))
            return cov

        cov_before = _coverage(design)

        r1 = _place(ha, hb, 6, da, db)
        assert r1.status_code == 201
        cov_after_1 = _coverage(r1.json()["design"])
        assert cov_before == cov_after_1, (
            f"Coverage changed after 1st crossover! "
            f"Lost: {cov_before - cov_after_1}, Gained: {cov_after_1 - cov_before}"
        )

        r2 = _place(ha, hb, 7, da, db)
        assert r2.status_code == 201
        cov_after_2 = _coverage(r2.json()["design"])
        assert cov_before == cov_after_2, (
            f"Coverage changed after 2nd crossover (Holliday junction)! "
            f"Lost: {cov_before - cov_after_2}, Gained: {cov_after_2 - cov_before}"
        )

    def test_holliday_junction_strand_structure(self):
        """After two adjacent crossovers (bp 6+7), exactly two multi-domain
        staple strands should exist, each spanning both helices."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r1 = _place(ha, hb, 6, da, db)
        assert r1.status_code == 201
        r2 = _place(ha, hb, 7, da, db)
        assert r2.status_code == 201

        result = r2.json()["design"]
        cross = _cross_helix_strands(result, ha, hb, "staple")
        assert len(cross) == 2, f"Expected 2 cross-helix staple strands, got {len(cross)}"
        for s in cross:
            assert len(s["domains"]) == 2, (
                f"Strand {s['id'][:8]} has {len(s['domains'])} domains, expected 2"
            )

    def test_6hb_multiple_holliday_junctions_preserve_coverage(self):
        """Manually placing several Holliday junctions across a 6HB must not
        lose any nucleotides at any step."""
        cells = [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2]]
        design = _make_bundle(cells)

        def _coverage(d):
            cov = set()
            for s in d["strands"]:
                for dom in s["domains"]:
                    lo = min(dom["start_bp"], dom["end_bp"])
                    hi = max(dom["start_bp"], dom["end_bp"])
                    for bp in range(lo, hi + 1):
                        cov.add((dom["helix_id"], bp, dom["direction"]))
            return cov

        cov_initial = _coverage(design)

        # Place crossovers one by one, checking coverage after each.
        # HC staple bp 6,7 valid between (0,0)↔(0,1).
        pairs = [
            ((0, 0), (0, 1), [6, 7]),       # first Holliday junction
            ((0, 0), (0, 1), [27, 28]),     # second Holliday junction, next period
        ]
        step = 0
        for (ra, ca), (rb, cb), bps in pairs:
            ha = _hid_at(design, ra, ca)
            hb = _hid_at(design, rb, cb)
            da, db = _staple_dirs(ra, ca)
            for bp in bps:
                step += 1
                r = _place(ha, hb, bp, da, db)
                assert r.status_code == 201, (
                    f"Step {step}: bp={bp} ({ra},{ca})↔({rb},{cb}) failed: "
                    f"{r.json().get('detail')}"
                )
                cov_now = _coverage(r.json()["design"])
                assert cov_initial == cov_now, (
                    f"Step {step}: coverage changed! "
                    f"Lost {len(cov_initial - cov_now)}, Gained {len(cov_now - cov_initial)}"
                )

    def test_duplicate_rejected(self):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r1 = _place(ha, hb, 7, da, db)
        assert r1.status_code == 201
        r2 = _place(ha, hb, 7, da, db)
        assert r2.status_code == 400
        assert "occupied" in r2.json()["detail"].lower()

    def test_staple_and_scaffold_coexist(self):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)

        r1 = _place(ha, hb, 7, *_staple_dirs(0, 0))
        assert r1.status_code == 201
        r2 = _place(ha, hb, 2, *_scaffold_dirs(0, 0), is_scaffold=True)
        assert r2.status_code == 201

        result = r2.json()["design"]
        assert len(result["crossovers"]) == 2


# ── Undo ────────────────────────────────────────────────────────────────────

class TestCrossoverUndo:

    def test_undo_reverts_crossover(self):
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)
        n_strands_before = len(design["strands"])

        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201

        r2 = client.post("/api/design/undo")
        assert r2.status_code == 200
        after = r2.json()["design"]
        assert len(after.get("crossovers", [])) == 0
        assert len(after["strands"]) == n_strands_before


# ── Crossover record correctness ─────────────────────────────────────────

class TestCrossoverRecordCorrectness:
    """Verify that crossover records are correct and strands are properly ligated."""

    def test_no_zero_length_domains(self):
        """Nicking must not produce empty or zero-length domains."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201
        result = r.json()["design"]

        for s in result["strands"]:
            for d in s["domains"]:
                lo = min(d["start_bp"], d["end_bp"])
                hi = max(d["start_bp"], d["end_bp"])
                assert hi >= lo, f"Zero-length domain in strand {s['id'][:8]}"

    def test_total_nucleotide_coverage_unchanged(self):
        """Crossover placement (nick + register) must not create or destroy
        nucleotide coverage — only rearrange which strand owns which bps."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        def _coverage(d):
            """Set of (helix_id, bp, direction) tuples."""
            cov = set()
            for s in d["strands"]:
                for dom in s["domains"]:
                    lo = min(dom["start_bp"], dom["end_bp"])
                    hi = max(dom["start_bp"], dom["end_bp"])
                    for bp in range(lo, hi + 1):
                        cov.add((dom["helix_id"], bp, dom["direction"]))
            return cov

        before = _coverage(design)
        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201
        after = _coverage(r.json()["design"])

        assert before == after, (
            f"Coverage changed! Lost: {before - after}, Gained: {after - before}"
        )

    def test_crossover_directions_match_parity(self):
        """Crossover half directions must match the expected strand type for
        each helix's parity."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201

        xo = r.json()["design"]["crossovers"][0]
        # Even cell (0,0): staple = REVERSE
        assert xo["half_a"]["strand"] == "REVERSE"
        # Odd cell (0,1): staple = FORWARD
        assert xo["half_b"]["strand"] == "FORWARD"

    def test_ligated_strand_spans_both_helices(self):
        """After placing a crossover, one staple strand should span both helices
        as a multi-domain oligo."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201
        result = r.json()["design"]

        cross = _cross_helix_strands(result, ha, hb, "staple")
        assert len(cross) == 1, "Expected exactly one ligated staple strand spanning both helices"


# ── Autocrossover after manual crossovers ─────────────────────────────────────

def _total_domain_count(design, strand_type="staple"):
    """Total number of domains across all strands of the given type."""
    return sum(
        len(s["domains"])
        for s in design["strands"]
        if s["strand_type"] == strand_type
    )


class TestAutocrossoverWithExistingManualCrossovers:
    """Autocrossover must not delete domains from already-ligated multi-domain
    strands that were created by manual place_crossover calls."""

    def test_domains_preserved_after_autocrossover(self):
        """Place a manual crossover, count domains, then run autocrossover.
        The total staple domain count must not decrease — it should only
        increase (new nicks create more fragments before ligation)."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        # Place a manual crossover at bp 6
        r = _place(ha, hb, 6, da, db)
        assert r.status_code == 201
        after_manual = r.json()["design"]
        manual_xover_count = len(after_manual["crossovers"])
        assert manual_xover_count == 1

        # The manual crossover created a multi-domain staple spanning both helices
        cross_before = _cross_helix_strands(after_manual, ha, hb, "staple")
        assert len(cross_before) >= 1, "Manual crossover should ligate a cross-helix staple"

        # Count total nucleotide coverage before autocrossover
        def _nt_coverage(d):
            total = 0
            for s in d["strands"]:
                if s["strand_type"] != "staple":
                    continue
                for dom in s["domains"]:
                    total += abs(dom["end_bp"] - dom["start_bp"]) + 1
            return total

        nt_before = _nt_coverage(after_manual)

        # Run autocrossover
        r2 = client.post("/api/design/crossovers/auto")
        assert r2.status_code == 200
        after_auto = r2.json()["design"]

        # More crossovers should have been placed
        assert len(after_auto["crossovers"]) >= manual_xover_count

        # Total nucleotide coverage must be preserved — no domains deleted
        nt_after = _nt_coverage(after_auto)
        assert nt_after == nt_before, (
            f"Nucleotide coverage changed: {nt_before} → {nt_after}. "
            f"Domains were {'deleted' if nt_after < nt_before else 'duplicated'}."
        )

    def test_manual_crossover_strand_survives(self):
        """The multi-domain strand from a manual crossover must still exist
        (or be extended) after autocrossover — it must not be split into
        single-domain orphans."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha, hb = _hid_at(design, 0, 0), _hid_at(design, 0, 1)
        da, db = _staple_dirs(0, 0)

        # Place manual crossover at bp 7 (bow-right position)
        r = _place(ha, hb, 7, da, db)
        assert r.status_code == 201

        # Run autocrossover
        r2 = client.post("/api/design/crossovers/auto")
        assert r2.status_code == 200
        after_auto = r2.json()["design"]

        # There should still be at least one cross-helix staple strand
        cross = _cross_helix_strands(after_auto, ha, hb, "staple")
        assert len(cross) >= 1, (
            "No cross-helix staple strand found after autocrossover — "
            "the manual crossover's multi-domain strand was destroyed"
        )
