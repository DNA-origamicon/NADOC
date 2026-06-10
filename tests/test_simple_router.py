"""Tests for the simple deterministic staple router.

Covers the three stages that replaced the Aksel method:
  1. seam detection — scaffold_seam_positions() finds double scaffold crossovers
     (two scaffold crossovers on the same helix pair at consecutive bps) and
     ignores single u-turn end caps.
  2. crossover placement — auto-crossover keeps full density at the end caps but
     leaves a ±7 (HC) / ±8 (SQ) bp band clear around every seam.
  3. break + grow — full-autostaple nicks the tick grid FIRST, then places
     crossovers, then grows fragments back to ≤56 nt (allowing >56 only to avoid
     stranding a neighbour < 14 nt).  Nicking before crossover placement keeps every
     crossover traversed (no nick lands on a crossover).
"""

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.crossover_positions import scaffold_seam_positions
from backend.core.lattice import _strand_nucleotide_positions
from backend.core.models import Direction, LatticeType, StrandType


# Honeycomb 6-helix ring (workspace 6hb cells) and a 3×2 square block.
_HC6_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
_SQ6_CELLS = [(0, 0), (0, 1), (0, 2), (1, 2), (1, 1), (1, 0)]


def _route(cells, length, lattice, *, seamless=False):
    """Build + scaffold + crossover + break a bundle in an isolated session.

    Returns (crossed_design, broken_design) snapshots.
    """
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, length, lattice=lattice, name="t")
        hb.auto_scaffold(seamless=seamless)
        hb.auto_crossover()
        crossed = design_state.get_or_404().model_copy(deep=True)
        hb.auto_break()
        broken = design_state.get_or_404().model_copy(deep=True)
    return crossed, broken


def _scaffold_half(design, half):
    helix = next((h for h in design.helices if h.id == half.helix_id and h.grid_pos is not None), None)
    if helix is None:
        return False
    row, col = helix.grid_pos
    return half.strand.value == ("FORWARD" if (row + col) % 2 == 0 else "REVERSE")


def _staple_lengths(design):
    return sorted(
        len(_strand_nucleotide_positions(s))
        for s in design.strands
        if s.strand_type not in (StrandType.SCAFFOLD, StrandType.LINKER) and not s.is_reference
    )


# ── 1. seam detection ─────────────────────────────────────────────────────────


def test_seam_detection_finds_consecutive_double_crossover_pairs():
    crossed, _ = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB)
    seams = scaffold_seam_positions(crossed)
    assert seams, "a seamed 6hb must expose at least one internal seam"
    # Every flagged bp belongs to a consecutive (X, X+1) run — the double-crossover
    # signature — never an isolated position.
    for helix_id, bps in seams.items():
        ordered = sorted(bps)
        for bp in ordered:
            assert (bp - 1 in bps) or (bp + 1 in bps), (
                f"seam bp {bp} on {helix_id} has no adjacent partner — not a double crossover"
            )


def test_seam_detection_ignores_non_consecutive_end_caps():
    crossed, _ = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB)
    seams = scaffold_seam_positions(crossed)

    # Collect scaffold-crossover bps grouped by normalized helix pair.  A cap pair
    # carries its near (-lo) and far (+hi) u-turn crossovers — two bps far apart,
    # never consecutive, so they must NOT be flagged as a seam.
    by_pair: dict[tuple[str, str], list[int]] = {}
    for xo in crossed.crossovers:
        if not (_scaffold_half(crossed, xo.half_a) and _scaffold_half(crossed, xo.half_b)):
            continue
        key = (min(xo.half_a.helix_id, xo.half_b.helix_id),
               max(xo.half_a.helix_id, xo.half_b.helix_id))
        by_pair.setdefault(key, []).append(xo.half_a.index)

    non_consecutive_bps = [
        (hid_a, hid_b, bp)
        for (hid_a, hid_b), bps in by_pair.items()
        for bp in bps
        if (bp - 1) not in bps and (bp + 1) not in bps
    ]
    assert non_consecutive_bps, "the 6hb caps should give non-consecutive crossover bps"
    for hid_a, hid_b, bp in non_consecutive_bps:
        assert bp not in seams.get(hid_a, set())
        assert bp not in seams.get(hid_b, set())


def test_seamless_routing_has_no_seams():
    crossed, _ = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB, seamless=True)
    # Seamless routing places one end crossover per pair — no double crossovers.
    assert scaffold_seam_positions(crossed) == {}


# ── 2. crossover placement: seam-clear, edge-dense ────────────────────────────


def test_auto_crossover_clears_seam_band_on_both_lattices():
    for cells, length, lattice, margin in (
        (_HC6_CELLS, 84, LatticeType.HONEYCOMB, 7),
        (_SQ6_CELLS, 96, LatticeType.SQUARE, 8),
    ):
        crossed, _ = _route(cells, length, lattice)
        seams = scaffold_seam_positions(crossed)
        staple_xovers = [
            xo for xo in crossed.crossovers
            if not (_scaffold_half(crossed, xo.half_a) and _scaffold_half(crossed, xo.half_b))
        ]
        assert staple_xovers, "auto-crossover must place staple crossovers"
        for xo in staple_xovers:
            for half in (xo.half_a, xo.half_b):
                for sp in seams.get(half.helix_id, ()):
                    assert abs(half.index - sp) > margin, (
                        f"{lattice}: staple crossover bp {half.index} within {margin} "
                        f"of seam {sp} on {half.helix_id}"
                    )


def test_auto_crossover_places_edge_crossovers_at_staple_termini():
    # The near/far bundle edges (the staple 5'/3' termini, e.g. bp 0) must carry
    # crossovers — this was the gap the helix-range coverage gate caused.
    crossed, _ = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB)
    staple_bps = {
        half.index
        for xo in crossed.crossovers
        if not (_scaffold_half(crossed, xo.half_a) and _scaffold_half(crossed, xo.half_b))
        for half in (xo.half_a, xo.half_b)
    }
    covered = [
        bp
        for s in crossed.strands
        if s.strand_type == StrandType.STAPLE and not s.is_reference
        for d in s.domains
        for bp in (d.start_bp, d.end_bp)
    ]
    lo, hi = min(covered), max(covered)
    assert lo in staple_bps, f"no crossover at the near edge (bp {lo})"
    assert hi in staple_bps, f"no crossover at the far edge (bp {hi})"


def test_auto_crossover_places_full_density_away_from_seams():
    # Full density: any valid crossover bp that is far from *every* seam (so no
    # per-helix exclusion could apply) must be placed.  This pins that the router
    # is not silently dropping interior or edge sites.
    from backend.core.crossover_positions import all_valid_crossover_sites

    crossed, _ = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB)
    seams = scaffold_seam_positions(crossed)
    placed = {
        half.index
        for xo in crossed.crossovers
        if not (_scaffold_half(crossed, xo.half_a) and _scaffold_half(crossed, xo.half_b))
        for half in (xo.half_a, xo.half_b)
    }
    valid_bps = {s["index"] for s in all_valid_crossover_sites(crossed)}
    all_seam_bps = {sp for sps in seams.values() for sp in sps}

    far_from_seams = {
        bp for bp in valid_bps
        if all(abs(bp - sp) > 8 for sp in all_seam_bps)  # >8 so neither bp nor bp-1 is in any seam band
    }
    assert far_from_seams, "expected some valid sites well clear of every seam"
    assert far_from_seams <= placed, (
        f"valid sites clear of all seams were dropped: {sorted(far_from_seams - placed)}"
    )


# ── 3. break + merge ──────────────────────────────────────────────────────────


def test_autobreak_nicks_only_on_major_ticks():
    _, broken = _route(_HC6_CELLS, 84, LatticeType.HONEYCOMB)
    period, ticks = 21, {0, 7, 14}
    xover_bps = set()
    for xo in broken.crossovers:
        xover_bps.add((xo.half_a.helix_id, xo.half_a.index))
        xover_bps.add((xo.half_b.helix_id, xo.half_b.index))

    # The interior boundary of every staple domain that is NOT a crossover junction
    # (i.e. a real nick) must sit on a major tick.
    for s in broken.strands:
        if s.strand_type != StrandType.STAPLE or s.is_reference:
            continue
        last = s.domains[-1]
        # 3' terminus of the staple: a nick unless it ends at a crossover.
        if (last.helix_id, last.end_bp) in xover_bps:
            continue
        tick_bp = (last.end_bp + 1) if last.direction == Direction.FORWARD else last.end_bp
        # Strand ends at a helix terminus are exempt (no nick was placed there).
        helix = next((h for h in broken.helices if h.id == last.helix_id), None)
        if helix is not None and last.end_bp in (helix.bp_start, helix.bp_start + helix.length_bp - 1):
            continue
        assert tick_bp % period in ticks, (
            f"staple 3' nick at bp {last.end_bp} (tick {tick_bp % period}) is off-grid"
        )


def test_autobreak_caps_all_staples_at_56_both_lattices():
    for cells, length, lattice in (
        (_HC6_CELLS, 168, LatticeType.HONEYCOMB),
        (_SQ6_CELLS, 96, LatticeType.SQUARE),
    ):
        _, broken = _route(cells, length, lattice)
        lengths = _staple_lengths(broken)
        assert lengths, "broken design must have staples"
        assert max(lengths) <= 56, f"{lattice}: staple longer than 56 nt — {max(lengths)}"


def test_merge_combines_short_colinear_pairs_up_to_56():
    from backend.core.lattice import make_merge_short_staples
    from backend.core.models import Design, Domain, Helix, Strand, Vec3
    from backend.core.constants import BDNA_RISE_PER_BP

    def _design(left_len, right_len):
        # One helix, two abutting REVERSE staple fragments meeting at a nick.
        total = left_len + right_len
        helix = Helix(
            id="h0",
            axis_start=Vec3(x=0.0, y=0.0, z=0.0),
            axis_end=Vec3(x=0.0, y=0.0, z=total * BDNA_RISE_PER_BP),
            length_bp=total,
            bp_start=0,
        )
        # REVERSE: start_bp > end_bp.  5'→3' runs high→low, so the first (5') fragment
        # occupies the high bps and the second occupies the low bps; they abut at the nick.
        left = Strand(id="s_left", strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id="h0", start_bp=total - 1, end_bp=right_len, direction=Direction.REVERSE)])
        right = Strand(id="s_right", strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id="h0", start_bp=right_len - 1, end_bp=0, direction=Direction.REVERSE)])
        return Design(helices=[helix], strands=[left, right], lattice_type=LatticeType.HONEYCOMB)

    # 21 + 21 = 42 ≤ 56 → merges into a single staple.
    merged = make_merge_short_staples(_design(21, 21), max_merged_length=56)
    staples = [s for s in merged.strands if s.strand_type == StrandType.STAPLE]
    assert len(staples) == 1, "co-linear pair summing 42 should merge"
    assert len(_strand_nucleotide_positions(staples[0])) == 42

    # 35 + 28 = 63 > 56 → stays split.
    kept = make_merge_short_staples(_design(35, 28), max_merged_length=56)
    assert len([s for s in kept.strands if s.strand_type == StrandType.STAPLE]) == 2, (
        "co-linear pair summing 63 must not merge past 56"
    )


# ── validation: a strand nicked at a crossover is a hard failure ──────────────


def _two_helix_design_with_crossover(*, nicked: bool):
    """Two helices joined by one crossover at (h0, bp10)/(h1, bp10).

    nicked=False → a single strand traverses the crossover (valid).
    nicked=True  → two strands meet at the crossover with free termini on it.
    """
    from backend.core.models import Crossover, Design, Domain, Helix, HalfCrossover, Strand, Vec3
    from backend.core.constants import BDNA_RISE_PER_BP

    helices = [
        Helix(id=f"h{i}", grid_pos=(0, i),
              axis_start=Vec3(x=i * 2.5, y=0.0, z=0.0),
              axis_end=Vec3(x=i * 2.5, y=0.0, z=21 * BDNA_RISE_PER_BP),
              length_bp=21, bp_start=0)
        for i in range(2)
    ]
    xo = Crossover(
        half_a=HalfCrossover(helix_id="h0", index=10, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=10, strand=Direction.REVERSE),
    )
    if nicked:
        # Two staples: one ends its 3' at (h0,10,FWD), the other starts 5' at (h1,10,REV).
        strands = [
            Strand(id="s_a", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="h0", start_bp=0, end_bp=10, direction=Direction.FORWARD)]),
            Strand(id="s_b", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="h1", start_bp=10, end_bp=0, direction=Direction.REVERSE)]),
        ]
    else:
        # One staple traverses: domain on h0 ends at 10, continues on h1 from 10.
        strands = [
            Strand(id="s", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="h0", start_bp=0, end_bp=10, direction=Direction.FORWARD),
                Domain(helix_id="h1", start_bp=10, end_bp=0, direction=Direction.REVERSE)]),
        ]
    return Design(helices=helices, strands=strands, crossovers=[xo],
                  lattice_type=LatticeType.HONEYCOMB)


def test_strand_nicked_at_crossover_is_a_validation_failure():
    from backend.core.validator import validate_design

    report = validate_design(_two_helix_design_with_crossover(nicked=True))
    nick_fails = [r for r in report.results if not r.ok and "nicked at crossover" in r.message]
    assert nick_fails, "a strand terminus on a crossover half must be a hard failure"
    assert not report.passed


def test_strand_traversing_crossover_passes_validation():
    from backend.core.validator import validate_design

    report = validate_design(_two_helix_design_with_crossover(nicked=False))
    nick_fails = [r for r in report.results if not r.ok and "nicked at crossover" in r.message]
    assert not nick_fails, "a continuous strand crossing the junction is valid"


# ── full-autostaple: nick-first order, valid, full density ────────────────────


def _full_autostaple(cells, length, lattice):
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, length, lattice=lattice, name="t")
        hb.auto_scaffold(seamless=False)
        return hb.full_autostaple("M13mp18")


def _staple_crossover_count(design):
    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}
    n = 0
    for xo in design.crossovers:
        if not (_scaffold_half(design, xo.half_a) and _scaffold_half(design, xo.half_b)):
            n += 1
    return n


def test_full_autostaple_is_valid_with_no_nick_on_crossover():
    from backend.core.validator import validate_design

    for cells, length, lattice in (
        (_HC6_CELLS, 168, LatticeType.HONEYCOMB),
        (_SQ6_CELLS, 96, LatticeType.SQUARE),
    ):
        d = _full_autostaple(cells, length, lattice)
        report = validate_design(d)
        nick_fail = [r.message for r in report.results if not r.ok and "nicked at crossover" in r.message]
        assert not nick_fail, f"{lattice}: full-autostaple left a nick on a crossover: {nick_fail}"
        assert report.passed, [r.message for r in report.results if not r.ok]


def test_full_autostaple_staple_lengths_in_range():
    # Honeycomb staples are 21..56 nt (lattice minimum 21 = 3×7); none stranded
    # below the minimum, none capped over 56.
    d = _full_autostaple(_HC6_CELLS, 168, LatticeType.HONEYCOMB)
    lengths = _staple_lengths(d)
    assert lengths
    assert min(lengths) >= 21, f"a honeycomb staple below 21 nt: {min(lengths)}"
    assert max(lengths) <= 56, f"a staple over 56 nt: {max(lengths)}"


def test_full_autostaple_keeps_full_crossover_density():
    # Nick-first placement never prunes crossovers, so the placed count equals the
    # standalone seam-aware density on the same nicked substrate.
    from backend.core.sequences import assign_scaffold_sequence
    from backend.core.lattice import nick_all_major_ticks
    from backend.api.crud import _linearize_staple_precursors, _place_auto_crossovers

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(_HC6_CELLS, 168, lattice=LatticeType.HONEYCOMB, name="t")
        hb.auto_scaffold(seamless=False)
        base = design_state.get_or_404().model_copy(deep=True)
        full = hb.full_autostaple("M13mp18")

    seq, _, _ = assign_scaffold_sequence(base, "M13mp18")
    prec, _ = _linearize_staple_precursors(seq)
    crossed, rep = _place_auto_crossovers(nick_all_major_ticks(prec))
    assert _staple_crossover_count(full) == rep["placed"], (
        "full-autostaple dropped crossovers vs. the place stage"
    )


def test_grow_staples_rebalances_instead_of_exceeding_the_cap():
    # A 14-nt fragment is below the honeycomb minimum (21); its only co-linear
    # neighbour is 49 nt, so a straight merge would be 63 nt (over the 56 cap).
    # Rebalance-then-split must nick the neighbour at the balancing tick so both
    # resulting staples land in [21, 56] — never producing an over-cap staple.
    from backend.core.lattice import grow_staples, _strand_nucleotide_positions
    from backend.core.models import Design, Domain, Helix, Strand, Vec3
    from backend.core.constants import BDNA_RISE_PER_BP

    total = 63
    helix = Helix(id="h0", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
                  axis_end=Vec3(x=0.0, y=0.0, z=total * BDNA_RISE_PER_BP),
                  length_bp=total, bp_start=0)
    # REVERSE staples abut at the nick: 5' fragment (49 nt) high bps, 3' fragment (14 nt) low bps.
    big = Strand(id="s_big", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="h0", start_bp=total - 1, end_bp=14, direction=Direction.REVERSE)])
    small = Strand(id="s_small", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="h0", start_bp=13, end_bp=0, direction=Direction.REVERSE)])
    design = Design(helices=[helix], strands=[big, small], lattice_type=LatticeType.HONEYCOMB)

    grown = grow_staples(design, max_merged_length=56)  # lattice default min → 21
    lengths = sorted(len(_strand_nucleotide_positions(s))
                     for s in grown.strands if s.strand_type == StrandType.STAPLE)
    assert len(lengths) == 2, "rebalance must split, not build one over-cap staple"
    assert all(21 <= n <= 56 for n in lengths), f"both pieces must be in [21,56]: {lengths}"
    assert sum(lengths) == 63, "no nucleotides lost in the rebalance"


def test_full_autostaple_splits_oversize_seam_bridge():
    # Regression for workspace/3x6sq_route_test1: a seam-bridging co-linear run that
    # the greedy merge+absorb grew to 72 nt must be split at a tick into two ≤56-nt
    # staples (the nick the user had to add by hand).
    from backend.core.validator import validate_design

    CELLS = [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 5], [1, 4], [1, 3],
             [1, 2], [1, 1], [1, 0], [2, 0], [2, 1], [2, 2], [2, 3], [2, 4], [2, 5]]
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(CELLS, 256, lattice=LatticeType.SQUARE, name="t")
        hb.auto_scaffold(seamless=False)
        d = hb.full_autostaple("M13mp18")

    lengths = _staple_lengths(d)
    assert max(lengths) <= 56, f"a seam-bridging staple exceeds 56 nt: {max(lengths)}"
    assert min(lengths) >= 24, f"a square staple below 24 nt: {min(lengths)}"
    assert validate_design(d).passed


# ── anti-sandwich rule + merge-order uniformity ───────────────────────────────


def test_has_sandwich_detects_runs_not_just_single_domains():
    from backend.core.lattice import _has_sandwich
    # Single short domain flanked by longer.
    assert _has_sandwich([14, 7, 14])
    # A *run* of short domains flanked by longer (the cases the old rule missed).
    assert _has_sandwich([14, 7, 7, 14])
    assert _has_sandwich([14, 7, 7, 7, 14])
    assert _has_sandwich([14, 7, 7, 21])      # flanks need not be equal
    # Not sandwiches: terminal shorts, uniform, peak-in-the-middle.
    assert not _has_sandwich([14, 7, 7])      # run is terminal
    assert not _has_sandwich([7, 14, 7])      # the 14 sticks up
    assert not _has_sandwich([7, 7, 7])
    assert not _has_sandwich([14, 14, 14])


def _reverse_staple(sid, hi, lo):
    from backend.core.models import Domain, Strand
    return Strand(id=sid, strand_type=StrandType.STAPLE,
                  domains=[Domain(helix_id="h0", start_bp=hi, end_bp=lo, direction=Direction.REVERSE)])


def _single_helix_design(strands, length_bp, lattice=LatticeType.HONEYCOMB):
    from backend.core.models import Design, Helix, Vec3
    from backend.core.constants import BDNA_RISE_PER_BP
    helix = Helix(id="h0", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
                  axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
                  length_bp=length_bp, bp_start=0)
    return Design(helices=[helix], strands=strands, lattice_type=lattice)


def test_merge_favours_growing_the_shorter_segment():
    # Co-linear chain 21 · 7 · 49.  The 7 can top the 49 up to 56 OR grow the 21
    # to 28 — favour the shorter neighbour → {28, 49}, not {21, 56}.
    from backend.core.lattice import make_merge_short_staples, _strand_nucleotide_positions
    design = _single_helix_design([
        _reverse_staple("s21", 76, 56),   # 21 nt
        _reverse_staple("s7", 55, 49),    # 7 nt
        _reverse_staple("s49", 48, 0),    # 49 nt
    ], length_bp=77)
    merged = make_merge_short_staples(design, max_merged_length=56)
    lengths = sorted(len(_strand_nucleotide_positions(s))
                     for s in merged.strands if s.strand_type == StrandType.STAPLE)
    assert lengths == [28, 49], f"expected the 7 to grow the 21 → {{28,49}}, got {lengths}"


def test_full_autostaple_output_is_sandwich_free():
    from backend.core.lattice import _strand_domain_lens, _has_sandwich
    for cells, length, lattice in (
        (_HC6_CELLS, 168, LatticeType.HONEYCOMB),
        (_SQ6_CELLS, 96, LatticeType.SQUARE),
    ):
        d = _full_autostaple(cells, length, lattice)
        bad = [s.id for s in d.strands
               if s.strand_type == StrandType.STAPLE and not s.is_reference
               and _has_sandwich(_strand_domain_lens(_strand_nucleotide_positions(s)))]
        assert not bad, f"{lattice}: sandwiched staples present: {bad}"
