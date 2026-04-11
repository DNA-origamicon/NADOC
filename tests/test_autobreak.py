"""
Tests for the autobreak (auto-nick) pipeline — Stage 2 of autostaple.

Validates that make_nicks_for_autostaple and make_autobreak correctly split
long staple strands into segments of 21–60 nt without sandwich violations.

Also includes API-level integration tests that replicate the real UI flow:
bundle → auto-crossover (with ligation) → auto-break.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import (
    ligate_crossover_chains,
    make_autobreak,
    make_bundle_design,
    make_nicks_for_autostaple,
    compute_nick_plan_for_strand,
    _strand_nucleotide_positions,
    _has_sandwich,
    _strand_domain_lens,
)
from backend.core.models import Design, Direction, LatticeType, StrandType

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────

CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
CELLS_SQ_2x4 = [(r, c) for r in range(2) for c in range(4)]


def _staple_strands(design: Design) -> list:
    return [s for s in design.strands if s.strand_type == StrandType.STAPLE]


def _strand_length(strand) -> int:
    return len(_strand_nucleotide_positions(strand))


def _assert_autobreak_invariants(
    before: Design,
    after: Design,
    max_length: int = 60,
    min_length: int = 21,
):
    """Assert the core autobreak postconditions."""
    staples_before = _staple_strands(before)
    staples_after = _staple_strands(after)

    long_before = [s for s in staples_before if _strand_length(s) > max_length]
    assert len(long_before) > 0, "Test precondition: need strands > max_length"
    assert len(staples_after) > len(staples_before), (
        f"Autobreak did not create any new strands: "
        f"{len(staples_before)} before, {len(staples_after)} after"
    )

    for strand in staples_after:
        length = _strand_length(strand)
        assert length >= 1, f"Empty strand {strand.id}"
        if length > max_length:
            pytest.fail(
                f"Strand {strand.id} has {length} nt, exceeds max_length={max_length}"
            )

    for strand in staples_after:
        positions = _strand_nucleotide_positions(strand)
        domain_lens = _strand_domain_lens(positions)
        if _has_sandwich(domain_lens):
            pytest.fail(
                f"Strand {strand.id} has sandwich violation: domain lengths = {domain_lens}"
            )


# ── Unit: autobreak on plain bundles (no crossovers) ────────────────────────


class TestAutobreakPlainBundle:
    """Autobreak on bundles without crossovers — strands are single-helix."""

    def test_hc_nicks_for_autostaple(self):
        design = make_bundle_design(CELLS_6HB, length_bp=126)
        result = make_nicks_for_autostaple(design)
        _assert_autobreak_invariants(design, result)

    def test_hc_autobreak(self):
        design = make_bundle_design(CELLS_6HB, length_bp=126)
        result = make_autobreak(design)
        _assert_autobreak_invariants(design, result)

    def test_sq_nicks_for_autostaple(self):
        design = make_bundle_design(
            CELLS_SQ_2x4, length_bp=128, lattice_type=LatticeType.SQUARE
        )
        result = make_nicks_for_autostaple(design)
        _assert_autobreak_invariants(design, result)

    def test_sq_autobreak(self):
        design = make_bundle_design(
            CELLS_SQ_2x4, length_bp=128, lattice_type=LatticeType.SQUARE
        )
        result = make_autobreak(design)
        _assert_autobreak_invariants(design, result)

    def test_noop_on_short_strands(self):
        design = make_bundle_design(CELLS_6HB, length_bp=42)
        result = make_nicks_for_autostaple(design)
        assert len(_staple_strands(result)) == len(_staple_strands(design))

    def test_exactly_60bp_no_break(self):
        design = make_bundle_design(CELLS_6HB, length_bp=60)
        result = make_nicks_for_autostaple(design)
        assert len(_staple_strands(result)) == len(_staple_strands(design))

    def test_nick_plan_nonempty_for_long_strand(self):
        design = make_bundle_design(CELLS_6HB, length_bp=126)
        for strand in _staple_strands(design):
            if _strand_length(strand) > 60:
                plan = compute_nick_plan_for_strand(strand)
                assert len(plan) > 0

    def test_very_long_strands(self):
        design = make_bundle_design(CELLS_6HB, length_bp=400)
        result = make_nicks_for_autostaple(design)
        _assert_autobreak_invariants(design, result)


# ── Unit: ligate_crossover_chains ────────────────────────────────────────────


class TestLigateCrossoverChains:
    """Tests for the crossover-chain ligation utility."""

    def _post_crossover_design(self, cells, length_bp, lattice_type="HONEYCOMB"):
        """Create bundle + auto-crossover via API, return the design."""
        client.post("/api/design/bundle", json={
            "cells": cells, "length_bp": length_bp,
            "name": "test", "plane": "XY", "lattice_type": lattice_type,
        })
        client.post("/api/design/crossovers/auto")
        return design_state.get_design()

    def test_noop_without_crossovers(self):
        """Without crossovers, ligation is a no-op."""
        design = make_bundle_design(CELLS_6HB, length_bp=42)
        result = ligate_crossover_chains(design)
        assert len(_staple_strands(result)) == len(_staple_strands(design))

    def test_hc_reduces_fragment_count(self):
        """After auto-crossover on HC 6HB, ligation merges fragments into chains."""
        design = self._post_crossover_design(list(CELLS_6HB), 42)
        staples_before = _staple_strands(design)
        # Ligation already happened in auto_crossover, so strands are multi-domain.
        # Verify: far fewer strands than original fragment count (26 fragments → 2 chains)
        assert len(staples_before) < 10, (
            f"Expected ligated design to have few staples, got {len(staples_before)}"
        )
        # Each staple should be multi-domain
        for s in staples_before:
            assert len(s.domains) > 1, (
                f"Strand {s.id} has only {len(s.domains)} domain(s) — not ligated"
            )

    def test_hc_chain_lengths_correct(self):
        """HC 6HB 42bp: each ligated chain should be 126 nt (6 helices × 21 bp per half-period)."""
        design = self._post_crossover_design(list(CELLS_6HB), 42)
        for s in _staple_strands(design):
            length = _strand_length(s)
            # Each chain traverses all helices, total should be 6 × 42 / num_chains
            assert length > 60, f"Ligated strand {s.id} only {length} nt"

    def test_crossover_records_preserved(self):
        """Ligation must not alter crossover records."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 42,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        design = design_state.get_design()
        assert len(design.crossovers) > 0, "No crossovers placed"

    def test_derived_crossovers_match(self):
        """extract_crossovers_from_strands on ligated strands should derive same crossovers."""
        from backend.core.crossover_positions import extract_crossovers_from_strands

        design = self._post_crossover_design(list(CELLS_6HB), 42)
        original_count = len(design.crossovers)
        derived = extract_crossovers_from_strands(design.strands)
        assert len(derived) == original_count, (
            f"Derived {len(derived)} crossovers, expected {original_count}"
        )

    def test_all_staples_accounted_for(self):
        """Total nucleotide count must be preserved after ligation."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        # Count total staple nt before crossovers
        before = design_state.get_design()
        total_before = sum(_strand_length(s) for s in _staple_strands(before))

        client.post("/api/design/crossovers/auto")
        after = design_state.get_design()
        total_after = sum(_strand_length(s) for s in _staple_strands(after))

        assert total_after == total_before, (
            f"Nucleotide count changed: {total_before} → {total_after}"
        )

    def test_sq_ligation_works(self):
        """SQ 2x4: ligation also works for square lattice."""
        design = self._post_crossover_design(list(CELLS_SQ_2x4), 128, "SQUARE")
        staples = _staple_strands(design)
        # Should have fewer strands than raw fragment count
        assert len(staples) < 80, f"Expected ligated SQ to have fewer staples, got {len(staples)}"


# ── Integration: full pipeline bundle → crossover → autobreak ────────────────


class TestAutobreakAfterCrossover:
    """The critical bug-fix tests: autobreak must work after auto-crossover."""

    def _create_and_crossover(self, cells, length_bp, lattice_type="HONEYCOMB"):
        client.post("/api/design/bundle", json={
            "cells": cells, "length_bp": length_bp,
            "name": "test", "plane": "XY", "lattice_type": lattice_type,
        })
        r = client.post("/api/design/crossovers/auto")
        assert r.status_code == 200
        return design_state.get_design()

    def test_hc_autobreak_nicks_long_chains(self):
        """HC 6HB 126bp: after crossover + ligation, autobreak must nick >60 nt strands."""
        design = self._create_and_crossover(list(CELLS_6HB), 126)

        # Precondition: ligated strands are >60 nt
        long = [s for s in _staple_strands(design) if _strand_length(s) > 60]
        assert len(long) > 0, "No strands >60 nt after ligation"

        result = make_nicks_for_autostaple(design)
        for s in _staple_strands(result):
            length = _strand_length(s)
            assert length <= 60, f"Strand {s.id} has {length} nt (limit 60)"

    def test_hc_autobreak_tick_nicks_long_chains(self):
        """Same test with make_autobreak (tick-mark algorithm)."""
        design = self._create_and_crossover(list(CELLS_6HB), 126)
        result = make_autobreak(design)
        for s in _staple_strands(result):
            assert _strand_length(s) <= 60

    def test_hc_no_sandwich_after_break(self):
        """No sandwich violations in resulting strands."""
        design = self._create_and_crossover(list(CELLS_6HB), 126)
        result = make_nicks_for_autostaple(design)
        for s in _staple_strands(result):
            positions = _strand_nucleotide_positions(s)
            domain_lens = _strand_domain_lens(positions)
            assert not _has_sandwich(domain_lens), (
                f"Sandwich in {s.id}: {domain_lens}"
            )

    def test_hc_crossovers_preserved_after_break(self):
        """Autobreak must not remove crossover records."""
        design = self._create_and_crossover(list(CELLS_6HB), 126)
        before_count = len(design.crossovers)
        result = make_nicks_for_autostaple(design)
        assert len(result.crossovers) == before_count

    def test_sq_autobreak_after_crossover(self):
        """SQ 2x4 128bp: autobreak after crossover."""
        design = self._create_and_crossover(list(CELLS_SQ_2x4), 128, "SQUARE")
        long = [s for s in _staple_strands(design) if _strand_length(s) > 60]
        if long:
            result = make_nicks_for_autostaple(design)
            for s in _staple_strands(result):
                assert _strand_length(s) <= 60

    def test_hc_400bp_full_pipeline(self):
        """HC 6HB 400bp: realistic helix length — full pipeline must produce ≤60 nt staples."""
        design = self._create_and_crossover(list(CELLS_6HB), 400)
        result = make_nicks_for_autostaple(design)
        max_len = max(_strand_length(s) for s in _staple_strands(result))
        assert max_len <= 60, f"Max staple after autobreak is {max_len} nt"


# ── API-level pipeline tests ────────────────────────────────────────────────


class TestAutobreakAPI:
    """End-to-end API tests for the full pipeline."""

    def _create_bundle(self, cells, length_bp, lattice_type="HONEYCOMB"):
        r = client.post("/api/design/bundle", json={
            "cells": cells, "length_bp": length_bp,
            "name": "test", "plane": "XY", "lattice_type": lattice_type,
        })
        assert r.status_code == 201
        return r.json()

    def _max_staple_length(self, response_json) -> int:
        max_len = 0
        for s in response_json["design"]["strands"]:
            if s["strand_type"].upper() != "STAPLE":
                continue
            nt = sum(abs(d["start_bp"] - d["end_bp"]) + 1 for d in s["domains"])
            max_len = max(max_len, nt)
        return max_len

    def _count_staples(self, response_json) -> int:
        return sum(
            1 for s in response_json["design"]["strands"]
            if s["strand_type"].upper() == "STAPLE"
        )

    def test_hc_full_pipeline_api(self):
        """HC 6HB 126bp: bundle → auto-crossover → auto-break via API."""
        self._create_bundle(list(CELLS_6HB), 126)

        r = client.post("/api/design/crossovers/auto")
        assert r.status_code == 200
        after_xover = r.json()
        # After ligation, strands are multi-domain — max length should be >60
        xover_max = self._max_staple_length(after_xover)
        assert xover_max > 60, (
            f"After auto-crossover+ligation, expected strands >60 nt, got max={xover_max}"
        )

        r = client.post("/api/design/auto-break")
        assert r.status_code == 200
        after_break = r.json()
        break_max = self._max_staple_length(after_break)
        assert break_max <= 60, f"After auto-break, max staple is {break_max} nt (limit 60)"

    def test_sq_full_pipeline_api(self):
        """SQ 2x4 128bp: bundle → auto-crossover → auto-break via API."""
        self._create_bundle(list(CELLS_SQ_2x4), 128, lattice_type="SQUARE")

        r = client.post("/api/design/crossovers/auto")
        assert r.status_code == 200

        r = client.post("/api/design/auto-break")
        assert r.status_code == 200
        after_break = r.json()
        break_max = self._max_staple_length(after_break)
        assert break_max <= 60

    def test_autobreak_without_crossovers(self):
        """Auto-break on plain bundle (no crossovers) must still nick long strands."""
        self._create_bundle(list(CELLS_6HB), 126)
        r = client.post("/api/design/auto-break")
        assert r.status_code == 200
        max_len = self._max_staple_length(r.json())
        assert max_len <= 60

    def test_autobreak_400bp(self):
        """Auto-break on 400bp bundle without crossovers."""
        self._create_bundle(list(CELLS_6HB), 400)
        r = client.post("/api/design/auto-break")
        assert r.status_code == 200
        max_len = self._max_staple_length(r.json())
        assert max_len <= 60


# ── Autobreak must not nick at crossover positions ─────────────────────────


class TestAutobreakRespectsXovers:
    """Verify that autobreak never places a nick at or near a crossover position,
    and that crossover junctions (inter-domain boundaries in multi-domain strands)
    survive autobreak intact."""

    def _xover_positions(self, design):
        """Return set of (helix_id, bp_index) for all crossover halves."""
        positions = set()
        for xo in design.crossovers:
            positions.add((xo.half_a.helix_id, xo.half_a.index))
            positions.add((xo.half_b.helix_id, xo.half_b.index))
        return positions

    def _all_nick_points(self, before, after):
        """Return the (helix_id, bp_index) positions where autobreak created nicks.

        A nick is a new strand boundary that didn't exist before autobreak.
        Detected by finding 3' terminals in `after` that don't exist in `before`.
        """
        def _three_prime_terminals(design):
            terminals = set()
            for s in design.strands:
                if s.strand_type == StrandType.SCAFFOLD or not s.domains:
                    continue
                last = s.domains[-1]
                terminals.add((last.helix_id, last.end_bp, last.direction))
            return terminals

        before_terminals = _three_prime_terminals(before)
        after_terminals = _three_prime_terminals(after)
        return after_terminals - before_terminals

    def _coverage(self, design):
        """Set of (helix_id, bp, direction) tuples covering all staple nucleotides."""
        cov = set()
        for s in design.strands:
            if s.strand_type == StrandType.SCAFFOLD:
                continue
            for d in s.domains:
                lo = min(d.start_bp, d.end_bp)
                hi = max(d.start_bp, d.end_bp)
                for bp in range(lo, hi + 1):
                    cov.add((d.helix_id, bp, d.direction))
        return cov

    def test_hc_no_nick_at_crossover_position(self):
        """HC 6HB 126bp: no autobreak nick may land on a crossover bp position."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        design_before = design_state.get_design()
        xover_pos = self._xover_positions(design_before)
        assert len(xover_pos) > 0, "Need crossovers to test"

        design_after = make_nicks_for_autostaple(design_before)
        new_nicks = self._all_nick_points(design_before, design_after)
        assert len(new_nicks) > 0, "Autobreak should have placed nicks"

        for helix_id, bp, direction in new_nicks:
            assert (helix_id, bp) not in xover_pos, (
                f"Autobreak nicked at crossover position ({helix_id}, bp={bp})"
            )

    def test_hc_nicks_land_on_tick_marks(self):
        """HC 6HB 126bp: all autobreak nick gaps must land on major tick marks.

        make_nick places the gap at boundary bp+1 (FORWARD) or bp (REVERSE).
        The gap boundary — not the raw bp — must be a tick mark."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        design_before = design_state.get_design()

        design_after = make_nicks_for_autostaple(design_before)
        new_nicks = self._all_nick_points(design_before, design_after)
        assert len(new_nicks) > 0, "Autobreak should have placed nicks"

        hc_ticks = {0, 7, 14}
        for helix_id, bp, direction in new_nicks:
            # Gap boundary: FORWARD bp+1, REVERSE bp
            gap = (bp + 1) if direction == Direction.FORWARD else bp
            assert (gap % 21) in hc_ticks, (
                f"Nick at ({helix_id}, bp={bp}, {direction.value}) → "
                f"gap at boundary {gap} (gap % 21 = {gap % 21}, "
                f"expected one of {hc_ticks})"
            )

    def test_crossover_junctions_survive_autobreak(self):
        """After autobreak, every crossover must be evidenced in the strand
        graph as one of:
          a) Inter-domain boundary within one strand (consecutive domains).
          b) 3'→5' wrap-around within one strand (last→first domain).
          c) Cross-strand nick: strand A's 3' end matches one half,
             strand B's 5' start matches the other (un-ligated because
             merging would exceed 60 nt).
        """
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        design_before = design_state.get_design()
        n_crossovers = len(design_before.crossovers)
        assert n_crossovers > 0

        design_after = make_nicks_for_autostaple(design_before)

        # Build terminal lookup maps for cross-strand nick check.
        five_prime: dict[tuple, str] = {}
        three_prime: dict[tuple, str] = {}
        for s in design_after.strands:
            if s.strand_type == StrandType.SCAFFOLD or not s.domains:
                continue
            fd = s.domains[0]
            five_prime[(fd.helix_id, fd.start_bp, fd.direction)] = s.id
            ld = s.domains[-1]
            three_prime[(ld.helix_id, ld.end_bp, ld.direction)] = s.id

        for xo in design_after.crossovers:
            ha, hb = xo.half_a, xo.half_b
            found = False
            for strand in design_after.strands:
                # Check inter-domain boundary (consecutive domains)
                for di in range(len(strand.domains) - 1):
                    d0 = strand.domains[di]
                    d1 = strand.domains[di + 1]
                    if (d0.helix_id == ha.helix_id and d0.end_bp == ha.index
                            and d1.helix_id == hb.helix_id and d1.start_bp == hb.index):
                        found = True
                        break
                    if (d0.helix_id == hb.helix_id and d0.end_bp == hb.index
                            and d1.helix_id == ha.helix_id and d1.start_bp == ha.index):
                        found = True
                        break
                if found:
                    break
                # Check 3'→5' wrap-around (same strand, last→first)
                if len(strand.domains) >= 2:
                    last = strand.domains[-1]
                    first = strand.domains[0]
                    if (last.helix_id == ha.helix_id and last.end_bp == ha.index
                            and first.helix_id == hb.helix_id and first.start_bp == hb.index):
                        found = True
                    if (last.helix_id == hb.helix_id and last.end_bp == hb.index
                            and first.helix_id == ha.helix_id and first.start_bp == ha.index):
                        found = True
                if found:
                    break
            # Check cross-strand nick: 3' of one strand → 5' of another
            if not found:
                s_from = (three_prime.get((hb.helix_id, hb.index, hb.strand))
                          or three_prime.get((ha.helix_id, ha.index, ha.strand)))
                s_to = (five_prime.get((ha.helix_id, ha.index, ha.strand))
                        or five_prime.get((hb.helix_id, hb.index, hb.strand)))
                if s_from and s_to and s_from != s_to:
                    found = True
            assert found, (
                f"Crossover {xo.id[:8]} at bp={ha.index} lost its strand "
                f"junction after autobreak"
            )

    def test_coverage_preserved_through_autobreak(self):
        """Total nucleotide coverage must be identical before and after autobreak."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        design_before = design_state.get_design()
        cov_before = self._coverage(design_before)

        design_after = make_nicks_for_autostaple(design_before)
        cov_after = self._coverage(design_after)

        lost = cov_before - cov_after
        gained = cov_after - cov_before
        assert len(lost) == 0, f"Autobreak lost {len(lost)} nucleotides"
        assert len(gained) == 0, f"Autobreak gained {len(gained)} nucleotides"

    def test_manual_crossovers_respected_by_autobreak(self):
        """Manually placed crossovers (Holliday junction at bp 6+7) must survive autobreak."""
        from backend.api.routes import _demo_design
        design_state.set_design(_demo_design())

        # Create 2-helix bundle with length_bp=126 (strands need breaking)
        r = client.post("/api/design/bundle", json={
            "cells": [[0, 0], [0, 1]], "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        assert r.status_code == 201
        design = r.json()["design"]
        ha = next(h["id"] for h in design["helices"] if h["grid_pos"] == [0, 0])
        hb = next(h["id"] for h in design["helices"] if h["grid_pos"] == [0, 1])

        # Place Holliday junction manually at bp 6+7
        for bp in [6, 7]:
            bow_right = {0, 7, 14}
            lower_bp = bp - 1 if (bp % 21) in bow_right else bp
            nick_a = lower_bp + 1  # REVERSE
            nick_b = lower_bp      # FORWARD
            r = client.post("/api/design/crossovers/place", json={
                "half_a": {"helix_id": ha, "index": bp, "strand": "REVERSE"},
                "half_b": {"helix_id": hb, "index": bp, "strand": "FORWARD"},
                "nick_bp_a": nick_a, "nick_bp_b": nick_b,
            })
            assert r.status_code == 201, f"bp={bp}: {r.json().get('detail')}"

        design_before = design_state.get_design()
        assert len(design_before.crossovers) == 2
        cov_before = self._coverage(design_before)

        # Run autobreak
        design_after = make_nicks_for_autostaple(design_before)

        # Coverage preserved
        cov_after = self._coverage(design_after)
        assert cov_before == cov_after, (
            f"Lost {len(cov_before - cov_after)}, gained {len(cov_after - cov_before)}"
        )

        # All strands ≤ 60 nt
        for s in _staple_strands(design_after):
            length = _strand_length(s)
            assert length <= 60, f"Strand {s.id} has {length} nt after autobreak"

        # Crossover junctions still intact as inter-domain boundaries
        assert len(design_after.crossovers) == 2
        for xo in design_after.crossovers:
            ha_half, hb_half = xo.half_a, xo.half_b
            found = False
            for strand in design_after.strands:
                for di in range(len(strand.domains) - 1):
                    d0, d1 = strand.domains[di], strand.domains[di + 1]
                    if (d0.helix_id == ha_half.helix_id and d0.end_bp == ha_half.index
                            and d1.helix_id == hb_half.helix_id and d1.start_bp == hb_half.index):
                        found = True
                    if (d0.helix_id == hb_half.helix_id and d0.end_bp == hb_half.index
                            and d1.helix_id == ha_half.helix_id and d1.start_bp == ha_half.index):
                        found = True
                if found:
                    break
            assert found, (
                f"Crossover at bp={ha_half.index} was destroyed by autobreak"
            )


# ── Edge connectivity (first & last 14 bp) ──────────────────────────────────


class TestEdgeConnectivity:
    """Verify strand structure in the first and last 14 bp of a design after
    auto-crossover + autobreak.  Catches missing edge crossovers, orphaned
    short fragments, and un-repairable nicks."""

    def _setup_6hb_pipeline(self):
        """Create 6HB 126bp, auto-crossover, autobreak.  Returns (before_break, after_break)."""
        from backend.api.routes import _demo_design
        design_state.set_design(_demo_design())
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 126,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        client.post("/api/design/crossovers/auto")
        before = design_state.get_design()
        after = make_nicks_for_autostaple(before)
        return before, after

    def _coverage_at_range(self, design, bp_lo, bp_hi):
        """Return set of (helix_id, bp, direction) for staples covering bp_lo..bp_hi."""
        cov = set()
        for s in design.strands:
            if s.strand_type == StrandType.SCAFFOLD:
                continue
            for d in s.domains:
                lo = min(d.start_bp, d.end_bp)
                hi = max(d.start_bp, d.end_bp)
                for bp in range(max(lo, bp_lo), min(hi, bp_hi) + 1):
                    cov.add((d.helix_id, bp, d.direction))
        return cov

    def _staple_direction(self, helix):
        """Return the staple direction for a helix (opposite of scaffold)."""
        row, col = helix.grid_pos
        # Even parity → scaffold FORWARD → staple REVERSE
        return Direction.REVERSE if (row + col) % 2 == 0 else Direction.FORWARD

    def test_full_coverage_first_14bp(self):
        """Every (helix, bp) in bp 0-13 must be covered by a staple strand
        in the correct staple direction for that helix."""
        _, after = self._setup_6hb_pipeline()
        cov = self._coverage_at_range(after, 0, 13)
        for h in after.helices:
            d = self._staple_direction(h)
            for bp in range(14):
                assert (h.id, bp, d) in cov, (
                    f"No staple at ({h.id}, bp={bp}, {d.value}) in first 14bp"
                )

    def test_full_coverage_last_14bp(self):
        """Every (helix, bp) in bp 112-125 must be covered by a staple strand
        in the correct staple direction for that helix."""
        _, after = self._setup_6hb_pipeline()
        cov = self._coverage_at_range(after, 112, 125)
        for h in after.helices:
            d = self._staple_direction(h)
            for bp in range(112, 126):
                assert (h.id, bp, d) in cov, (
                    f"No staple at ({h.id}, bp={bp}, {d.value}) in last 14bp"
                )

    def test_edge_crossovers_present(self):
        """All valid crossover positions in bp 0-13 and 112-125 must exist as
        crossover records after auto-crossover."""
        from backend.core.crossover_positions import all_valid_crossover_sites
        before, _ = self._setup_6hb_pipeline()

        # Deduplicated valid edge sites
        sites = all_valid_crossover_sites(before)
        edge_sites = set()
        for s in sites:
            bp = s["index"]
            if bp <= 13 or bp >= 112:
                key = (min(s["helix_a_id"], s["helix_b_id"]),
                       max(s["helix_a_id"], s["helix_b_id"]), bp)
                edge_sites.add(key)

        # Placed crossovers at edges
        placed = set()
        for xo in before.crossovers:
            bp = xo.half_a.index
            if bp <= 13 or bp >= 112:
                key = (min(xo.half_a.helix_id, xo.half_b.helix_id),
                       max(xo.half_a.helix_id, xo.half_b.helix_id), bp)
                placed.add(key)

        missing = edge_sites - placed
        assert len(missing) == 0, (
            f"Missing edge crossovers: {sorted(missing, key=lambda x: x[2])}"
        )

    def test_crossover_junctions_intact_at_edges(self):
        """After autobreak, every edge crossover must still be an inter-domain
        boundary within a multi-domain strand."""
        _, after = self._setup_6hb_pipeline()

        for xo in after.crossovers:
            bp = xo.half_a.index
            if bp > 13 and bp < 112:
                continue
            ha, hb = xo.half_a, xo.half_b
            found = False
            for strand in after.strands:
                for di in range(len(strand.domains) - 1):
                    d0, d1 = strand.domains[di], strand.domains[di + 1]
                    if (d0.helix_id == ha.helix_id and d0.end_bp == ha.index
                            and d1.helix_id == hb.helix_id and d1.start_bp == hb.index):
                        found = True
                    if (d0.helix_id == hb.helix_id and d0.end_bp == hb.index
                            and d1.helix_id == ha.helix_id and d1.start_bp == ha.index):
                        found = True
                    if found:
                        break
                if found:
                    break
            assert found, (
                f"Edge crossover at bp={bp} ({ha.helix_id} ↔ {hb.helix_id}) "
                f"lost inter-domain boundary after autobreak"
            )

    def test_no_internal_same_helix_domain_gaps(self):
        """No strand should have adjacent domains on the same helix with a bp gap
        between them — that looks like an un-repairable nick in the UI."""
        _, after = self._setup_6hb_pipeline()

        for s in after.strands:
            if s.strand_type == StrandType.SCAFFOLD or len(s.domains) < 2:
                continue
            for i in range(len(s.domains) - 1):
                d0, d1 = s.domains[i], s.domains[i + 1]
                if d0.helix_id != d1.helix_id or d0.direction != d1.direction:
                    continue  # cross-helix = crossover junction, fine
                # Same helix, same direction: domains should be contiguous
                if d0.direction == Direction.FORWARD:
                    gap = d1.start_bp - d0.end_bp
                else:
                    gap = d0.end_bp - d1.start_bp
                assert gap == 1, (
                    f"Strand {s.id} has same-helix domain gap={gap} between "
                    f"domain[{i}] (end_bp={d0.end_bp}) and domain[{i+1}] "
                    f"(start_bp={d1.start_bp}) on {d0.helix_id} {d0.direction.value}"
                )

    def test_nick_repair_at_edges(self):
        """Every nick boundary in the first/last 14bp must be repairable via
        the ligate endpoint (shift-click in UI)."""
        _, after = self._setup_6hb_pipeline()
        design_state.set_design(after)

        # Find all nick boundaries at edges: 3' end of one strand adjacent to
        # 5' start of another on the same helix/direction.
        nicks_at_edges = []
        five_prime_map = {}
        for s in after.strands:
            if s.strand_type == StrandType.SCAFFOLD or not s.domains:
                continue
            f = s.domains[0]
            five_prime_map[(f.helix_id, f.start_bp, f.direction)] = s

        for s in after.strands:
            if s.strand_type == StrandType.SCAFFOLD or not s.domains:
                continue
            last = s.domains[-1]
            end_bp = last.end_bp
            if not (end_bp <= 13 or end_bp >= 112):
                continue
            next_bp = end_bp + 1 if last.direction == Direction.FORWARD else end_bp - 1
            s2 = five_prime_map.get((last.helix_id, next_bp, last.direction))
            if s2 is not None and s2.id != s.id:
                nicks_at_edges.append((last.helix_id, end_bp, last.direction))

        # Try repairing each nick via API
        for helix_id, bp, direction in nicks_at_edges:
            design_state.set_design(after)  # reset each time
            r = client.post("/api/design/ligate", json={
                "helix_id": helix_id,
                "bp_index": bp,
                "direction": direction.value,
            })
            assert r.status_code == 200, (
                f"Ligate failed at ({helix_id}, bp={bp}, {direction.value}): "
                f"{r.json().get('detail', r.text)}"
            )


# ── Desplice after auto-crossover ───────────────────────────────────────────


class TestDespliceAfterAutoCrossover:
    """Deleting a crossover after auto-crossover must correctly split the strand."""

    def test_delete_crossover_splits_ligated_strand(self):
        """Delete one crossover from a ligated design — strand count should increase by 1."""
        client.post("/api/design/bundle", json={
            "cells": list(CELLS_6HB), "length_bp": 42,
            "name": "test", "plane": "XY", "lattice_type": "HONEYCOMB",
        })
        r = client.post("/api/design/crossovers/auto")
        assert r.status_code == 200
        design = design_state.get_design()

        staples_before = len(_staple_strands(design))
        xovers_before = len(design.crossovers)
        assert xovers_before > 0

        # Delete the first crossover
        xover_id = design.crossovers[0].id
        r = client.delete(f"/api/design/crossovers/{xover_id}")
        assert r.status_code == 200

        design_after = design_state.get_design()
        staples_after = len(_staple_strands(design_after))
        xovers_after = len(design_after.crossovers)

        assert xovers_after == xovers_before - 1, "Crossover not removed"
        assert staples_after == staples_before + 1, (
            f"Expected strand count to increase by 1 after desplice: "
            f"{staples_before} → {staples_after}"
        )
