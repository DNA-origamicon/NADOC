"""
Tests for forced ligation via POST /design/forced-ligation.

Forced ligation connects any 3' end to any 5' end, bypassing crossover
lookup tables.  This is a manual user feature only — NOT for autocrossover
or any automated pipeline.

No Crossover record is created.  The two strands are merged into a single
multi-domain strand via _ligate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


def _make_bundle(cells, length_bp=42):
    r = client.post("/api/design/bundle", json={
        "cells": cells, "length_bp": length_bp, "plane": "XY",
    })
    assert r.status_code == 201
    return r.json()["design"]


def _hid_at(design, row, col):
    return next(h["id"] for h in design["helices"] if h["grid_pos"] == [row, col])


def _nick(helix_id, bp_index, direction):
    r = client.post("/api/design/nick", json={
        "helix_id": helix_id, "bp_index": bp_index, "direction": direction,
    })
    assert r.status_code == 201
    return r.json()["design"]


def _find_strand_with_3prime(design, helix_id, end_bp, direction):
    """Find strand whose last domain ends at (helix_id, end_bp, direction)."""
    for s in design["strands"]:
        last = s["domains"][-1]
        if (last["helix_id"] == helix_id
                and last["end_bp"] == end_bp
                and last["direction"] == direction):
            return s
    return None


def _find_strand_with_5prime(design, helix_id, start_bp, direction):
    """Find strand whose first domain starts at (helix_id, start_bp, direction)."""
    for s in design["strands"]:
        first = s["domains"][0]
        if (first["helix_id"] == helix_id
                and first["start_bp"] == start_bp
                and first["direction"] == direction):
            return s
    return None


class TestForcedLigation:
    """Test forced ligation between strand ends."""

    def test_basic_ligation_same_helix(self):
        """Nick a strand, then forced-ligate the two fragments back together."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)

        # Nick the staple at bp 10 (REVERSE direction for even cell)
        design = _nick(hid, 10, "REVERSE")

        # Find the two fragment strands
        strand_a = _find_strand_with_3prime(design, hid, 10, "REVERSE")
        strand_b = _find_strand_with_5prime(design, hid, 9, "REVERSE")
        assert strand_a is not None, "3' fragment not found after nick"
        assert strand_b is not None, "5' fragment not found after nick"
        assert strand_a["id"] != strand_b["id"]

        # Forced-ligate them
        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": strand_a["id"],
            "five_prime_strand_id": strand_b["id"],
        })
        assert r.status_code == 201
        result = r.json()["design"]

        # Should have one fewer strand now (two merged into one)
        staples_on_hid = [
            s for s in result["strands"]
            if s["strand_type"] == "staple"
            and any(d["helix_id"] == hid for d in s["domains"])
        ]
        assert len(staples_on_hid) == 1, "Expected one merged staple strand"

    def test_ligation_across_helices(self):
        """Forced-ligate strands on different helices (no crossover record)."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)

        # Even cell (0,0): staple is REVERSE, 3' at end_bp=0
        # Odd cell (0,1): staple is FORWARD, 5' at start_bp=0
        staple_a = _find_strand_with_3prime(design, ha, 0, "REVERSE")
        staple_b = _find_strand_with_5prime(design, hb, 0, "FORWARD")
        assert staple_a is not None, "3' staple on helix A not found"
        assert staple_b is not None, "5' staple on helix B not found"

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": staple_a["id"],
            "five_prime_strand_id": staple_b["id"],
        })
        assert r.status_code == 201
        result = r.json()["design"]

        # The merged strand should span both helices
        merged = None
        for s in result["strands"]:
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids and hb in hids:
                merged = s
                break
        assert merged is not None, "Expected one strand spanning both helices"

        # No crossover record should be created
        assert len(result["crossovers"]) == 0, "Forced ligation must not create crossover records"

    def test_self_ligation_rejected(self):
        """Cannot ligate a strand to itself."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)
        # Even cell: staple is REVERSE with end_bp=0 (3') and start_bp=41 (5')
        staple = _find_strand_with_3prime(design, hid, 0, "REVERSE")
        assert staple is not None

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": staple["id"],
            "five_prime_strand_id": staple["id"],
        })
        assert r.status_code == 409

    def test_missing_strand_404(self):
        """Nonexistent strand ID returns 404."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)
        staple = _find_strand_with_3prime(design, hid, 0, "REVERSE")

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": staple["id"],
            "five_prime_strand_id": "nonexistent-id",
        })
        assert r.status_code == 404

    def test_undo_after_forced_ligation(self):
        """Forced ligation should be undoable."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)
        design = _nick(hid, 10, "REVERSE")

        strand_a = _find_strand_with_3prime(design, hid, 10, "REVERSE")
        strand_b = _find_strand_with_5prime(design, hid, 9, "REVERSE")
        strand_count_before = len(design["strands"])

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": strand_a["id"],
            "five_prime_strand_id": strand_b["id"],
        })
        assert r.status_code == 201
        ligated_count = len(r.json()["design"]["strands"])
        assert ligated_count == strand_count_before - 1

        # Undo
        r = client.post("/api/design/undo")
        assert r.status_code == 200
        assert len(r.json()["design"]["strands"]) == strand_count_before

    def test_ligation_different_bp_indices(self):
        """Forced ligation works between ends at different bp positions.

        This is the key difference from regular crossovers which require
        matching bp indices.  Nick at different positions on two helices,
        then ligate the fragments that have mismatched end bps.
        """
        design = _make_bundle([[0, 0], [0, 1]])
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)

        # Nick staple on helix A at bp 10 (REVERSE), creating 3' end at bp 10
        design = _nick(ha, 10, "REVERSE")
        # Nick staple on helix B at bp 20 (FORWARD), creating 5' end at bp 21
        design = _nick(hb, 20, "FORWARD")

        strand_3p = _find_strand_with_3prime(design, ha, 10, "REVERSE")
        strand_5p = _find_strand_with_5prime(design, hb, 21, "FORWARD")
        assert strand_3p is not None, "3' fragment on helix A not found"
        assert strand_5p is not None, "5' fragment on helix B not found"
        assert strand_3p["id"] != strand_5p["id"]

        # The 3' end is at bp 10 on helix A, the 5' end is at bp 21 on helix B
        # — different bp indices.  Regular crossovers would reject this.
        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": strand_3p["id"],
            "five_prime_strand_id": strand_5p["id"],
        })
        assert r.status_code == 201
        result = r.json()["design"]

        # Merged strand should span both helices
        merged = None
        for s in result["strands"]:
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids and hb in hids:
                merged = s
                break
        assert merged is not None, "Expected one strand spanning both helices at different bp indices"
        assert len(result["crossovers"]) == 0, "No crossover record for forced ligation"


class TestForcedLigationAutoscaffold:
    """Auto-scaffold must detect forced ligations and leave those scaffold strands alone."""

    def test_autoscaffold_preserves_forced_ligation(self):
        """Force-ligate two scaffold strands, then run auto-scaffold.

        The forced-ligated scaffold strand (and its helices) should be
        preserved; only the remaining helices get re-routed.
        """
        # 4 helices: HC row 0, cols 0-3  (even count required by auto-scaffold)
        design = _make_bundle([[0, 0], [0, 1], [0, 2], [0, 3]], length_bp=42)
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)

        # Find the two scaffold strands on helices A and B
        scaf_a = None
        scaf_b = None
        for s in design["strands"]:
            if s["strand_type"] != "scaffold":
                continue
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids:
                scaf_a = s
            if hb in hids:
                scaf_b = s
        assert scaf_a is not None and scaf_b is not None

        # Force-ligate scaffold A (3') → scaffold B (5')
        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": scaf_a["id"],
            "five_prime_strand_id": scaf_b["id"],
        })
        assert r.status_code == 201
        design = r.json()["design"]

        # Verify forced_ligations recorded
        assert len(design["forced_ligations"]) == 1

        # Find the merged scaffold strand spanning ha + hb
        merged_scaf = None
        for s in design["strands"]:
            if s["strand_type"] != "scaffold":
                continue
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids and hb in hids:
                merged_scaf = s
                break
        assert merged_scaf is not None, "Forced-ligated scaffold strand not found"
        merged_id = merged_scaf["id"]
        merged_domains_before = merged_scaf["domains"]

        # Run auto-scaffold — should preserve the forced-ligated strand
        r = client.post("/api/design/auto-scaffold")
        assert r.status_code == 200
        result = r.json()["design"]

        # The merged scaffold strand must still exist with same id and domains
        preserved = None
        for s in result["strands"]:
            if s["id"] == merged_id:
                preserved = s
                break
        assert preserved is not None, "Forced-ligated scaffold strand was removed by auto-scaffold"
        assert preserved["domains"] == merged_domains_before, (
            "Auto-scaffold modified the domains of a forced-ligated scaffold strand"
        )

    def test_forced_ligation_record_stored(self):
        """forced_ligation endpoint stores a ForcedLigation record on the design."""
        design = _make_bundle([[0, 0], [0, 1]])
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)

        scaf_a = scaf_b = None
        for s in design["strands"]:
            if s["strand_type"] != "scaffold":
                continue
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids:
                scaf_a = s
            if hb in hids:
                scaf_b = s

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": scaf_a["id"],
            "five_prime_strand_id": scaf_b["id"],
        })
        assert r.status_code == 201
        fl_list = r.json()["design"]["forced_ligations"]
        assert len(fl_list) == 1
        fl = fl_list[0]
        # 3' end should be on helix A, 5' start on helix B
        assert fl["three_prime_helix_id"] == ha
        assert fl["five_prime_helix_id"] == hb


class TestDeleteForcedLigation:
    """Tests for DELETE /design/forced-ligations/{fl_id} and batch-delete."""

    def _create_forced_ligation(self):
        """Create a two-helix bundle and forced-ligate the scaffold strands.
        Returns (design, fl_record, helix_a_id, helix_b_id).
        """
        design = _make_bundle([[0, 0], [0, 1]])
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)

        scaf_a = scaf_b = None
        for s in design["strands"]:
            if s["strand_type"] != "scaffold":
                continue
            hids = {d["helix_id"] for d in s["domains"]}
            if ha in hids:
                scaf_a = s
            if hb in hids:
                scaf_b = s

        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": scaf_a["id"],
            "five_prime_strand_id": scaf_b["id"],
        })
        assert r.status_code == 201
        design = r.json()["design"]
        fl = design["forced_ligations"][0]
        return design, fl, ha, hb

    def test_delete_splits_strand(self):
        """Deleting a forced ligation splits the merged strand back into two."""
        design, fl, ha, hb = self._create_forced_ligation()
        strand_count_before = len(design["strands"])

        r = client.delete(f"/api/design/forced-ligations/{fl['id']}")
        assert r.status_code == 200
        result = r.json()["design"]

        # One more strand (split back into two)
        assert len(result["strands"]) == strand_count_before + 1
        # FL record removed
        assert len(result["forced_ligations"]) == 0

    def test_delete_is_undoable(self):
        """Deleting a forced ligation should be undoable."""
        design, fl, ha, hb = self._create_forced_ligation()
        strand_count_merged = len(design["strands"])

        r = client.delete(f"/api/design/forced-ligations/{fl['id']}")
        assert r.status_code == 200
        assert len(r.json()["design"]["strands"]) == strand_count_merged + 1

        r = client.post("/api/design/undo")
        assert r.status_code == 200
        undone = r.json()["design"]
        assert len(undone["strands"]) == strand_count_merged
        assert len(undone["forced_ligations"]) == 1

    def test_delete_nonexistent_returns_404(self):
        """Deleting a nonexistent forced ligation returns 404."""
        _make_bundle([[0, 0]])
        r = client.delete("/api/design/forced-ligations/nonexistent-id")
        assert r.status_code == 404

    def test_batch_delete(self):
        """Batch-delete multiple forced ligations atomically."""
        # Create a 4-helix bundle, force-ligate two separate pairs
        design = _make_bundle([[0, 0], [0, 1], [0, 2], [0, 3]])
        ha = _hid_at(design, 0, 0)
        hb = _hid_at(design, 0, 1)
        hc = _hid_at(design, 0, 2)
        hd = _hid_at(design, 0, 3)

        def _scaf_on(d, hid):
            for s in d["strands"]:
                if s["strand_type"] != "scaffold":
                    continue
                if any(dom["helix_id"] == hid for dom in s["domains"]):
                    return s
            return None

        # First forced ligation: A → B
        scaf_a = _scaf_on(design, ha)
        scaf_b = _scaf_on(design, hb)
        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": scaf_a["id"],
            "five_prime_strand_id": scaf_b["id"],
        })
        assert r.status_code == 201
        design = r.json()["design"]

        # Second forced ligation: C → D
        scaf_c = _scaf_on(design, hc)
        scaf_d = _scaf_on(design, hd)
        r = client.post("/api/design/forced-ligation", json={
            "three_prime_strand_id": scaf_c["id"],
            "five_prime_strand_id": scaf_d["id"],
        })
        assert r.status_code == 201
        design = r.json()["design"]
        assert len(design["forced_ligations"]) == 2
        strand_count_before = len(design["strands"])

        fl_ids = [fl["id"] for fl in design["forced_ligations"]]
        r = client.post("/api/design/forced-ligations/batch-delete", json={
            "forced_ligation_ids": fl_ids,
        })
        assert r.status_code == 200
        result = r.json()["design"]
        # Both FLs removed, each split adds one strand
        assert len(result["forced_ligations"]) == 0
        assert len(result["strands"]) == strand_count_before + 2

    def test_batch_delete_missing_id_returns_404(self):
        """Batch-delete with a nonexistent ID returns 404."""
        design, fl, _, _ = self._create_forced_ligation()
        r = client.post("/api/design/forced-ligations/batch-delete", json={
            "forced_ligation_ids": [fl["id"], "nonexistent-id"],
        })
        assert r.status_code == 404


class TestLigateSameStrandDomainMerge:
    """POST /design/ligate should merge adjacent domains within the same strand.

    A multi-domain strand can have an internal domain boundary on the same helix
    (e.g. from forced ligation with suppressed merge, or imported designs).
    Shift+nick (ligate) at these boundaries should collapse the two adjacent
    domains into one — the inverse of a nick.
    """

    @staticmethod
    def _inject_multi_domain_strand(helix_id, direction="REVERSE"):
        """Create a strand with two consecutive same-helix domains by directly
        manipulating the design state. Returns (strand_id, domain_count, bp_index)
        where bp_index is the 3′-end convention for the ligate call.
        """
        from backend.core.models import Strand, Domain, Direction
        design = design_state.get_or_404()
        dir_enum = Direction(direction)

        # Pick an existing staple on this helix to replace
        target = None
        for s in design.strands:
            if s.strand_type.value == "staple" and any(
                d.helix_id == helix_id and d.direction == dir_enum for d in s.domains
            ):
                target = s
                break
        assert target is not None

        # Split its first domain into two consecutive domains
        orig = target.domains[0]
        lo = min(orig.start_bp, orig.end_bp)
        hi = max(orig.start_bp, orig.end_bp)
        mid = (lo + hi) // 2
        if dir_enum == Direction.FORWARD:
            d1 = Domain(helix_id=helix_id, start_bp=lo, end_bp=mid, direction=dir_enum)
            d2 = Domain(helix_id=helix_id, start_bp=mid + 1, end_bp=hi, direction=dir_enum)
            bp_index = mid  # 3′ end of d1
        else:
            d1 = Domain(helix_id=helix_id, start_bp=hi, end_bp=mid, direction=dir_enum)
            d2 = Domain(helix_id=helix_id, start_bp=mid - 1, end_bp=lo, direction=dir_enum)
            bp_index = mid  # 3′ end of d1

        new_domains = [d1, d2] + list(target.domains[1:])
        patched = target.model_copy(update={"domains": new_domains})
        new_strands = [patched if s.id == target.id else s for s in design.strands]
        design_state.set_design_silent(
            design.model_copy(update={"strands": new_strands})
        )
        return target.id, len(new_domains), bp_index

    def test_ligate_merges_internal_domain_boundary(self):
        """Ligate at an internal domain boundary merges the two domains."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)
        strand_id, dom_count, bp_index = self._inject_multi_domain_strand(hid)

        r = client.post("/api/design/ligate", json={
            "helix_id": hid, "bp_index": bp_index, "direction": "REVERSE",
        })
        assert r.status_code == 200
        updated = next(s for s in r.json()["design"]["strands"] if s["id"] == strand_id)
        assert len(updated["domains"]) == dom_count - 1

    def test_ligate_same_strand_is_undoable(self):
        """Same-strand domain merge via ligate should be undoable."""
        design = _make_bundle([[0, 0]])
        hid = _hid_at(design, 0, 0)
        strand_id, dom_count, bp_index = self._inject_multi_domain_strand(hid)

        r = client.post("/api/design/ligate", json={
            "helix_id": hid, "bp_index": bp_index, "direction": "REVERSE",
        })
        assert r.status_code == 200
        updated = next(s for s in r.json()["design"]["strands"] if s["id"] == strand_id)
        assert len(updated["domains"]) == dom_count - 1

        r = client.post("/api/design/undo")
        assert r.status_code == 200
        reverted = next(s for s in r.json()["design"]["strands"] if s["id"] == strand_id)
        assert len(reverted["domains"]) == dom_count
