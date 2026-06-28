"""
Hinge weave realizer — turn the abstract single-strand hinge route
(:func:`backend.core.hinge_ladder.weave_hinge_full`) into a concrete, gate-clean
scaffold ``Design``.

Background.  A hinge is two rigid leaves bridged across a gap by forced-ligation
rungs (see ``memory/project_hinge_autoscaffold.md``).  ``weave_hinge_full`` gives
the exact helix-visit order for one scaffold strand that threads every rung; this
module *realizes* that order at bp resolution by driving the PROVEN seamed-router
placement primitives (``_place_xover`` nick/validate/ligate-merge over the seed
segments, ``_extend_*`` for ≥3 bp ssDNA margins), then opening the resulting loop
with a buried nick.  The rungs are NOT placed — they are the pre-connected
forced-ligation bridge seeds, so the FL records are preserved verbatim.

Key facts the realizer relies on (all empirically grounded in the five hand-routed
references in ``workspace/Scaffold routing``):

* **Crossover face is determined by helix scaffold direction.**  At a trail
  junction X→Y the crossover sits at X's 3′ end — HI face if X is forward, LO if
  reverse — and since lattice-adjacent helices always have opposite parity, X and
  Y agree.  So near (LO) / far (HI) classification is forced, not chosen.
* **Seams split double-passed helices.**  Every helix visited twice (except
  *turn/nick* helices, traversed full-length) must be split once by a mid-helix
  double crossover.  That is a perfect matching over the non-turn double-passed
  helices using actual trail-junction edges; the gate requires ≥1 such seam.

Self-gated: returns ``None`` (caller falls back to the classic pipeline) unless the
output is exactly one scaffold strand, every forced ligation is preserved, every
placement succeeded, ``scaffold_routing_invariants`` is clean and ``validate_design``
passes.  So it can never regress.

Three-Layer Law: topology only (plus the seamed router's helix-axis extension).
"""

from __future__ import annotations

from collections import Counter

from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
from backend.core.hinge_ladder import weave_hinge_full
from backend.core.models import Design, Direction, HalfCrossover, LatticeType
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import (
    SeamedResult,
    _HC_SCAF_BOW_RIGHT,
    _SQ_SCAF_BOW_RIGHT,
    _extend_helix_hi,
    _extend_helix_lo,
    _extend_scaf_domain_hi,
    _extend_scaf_domain_lo,
    _is_forward,
    _linearize_circular_scaffolds,
    _nick_bp,
    _place_xover,
    _scaf_nb,
    _scaffold_coverage,
)
from backend.core.validator import validate_design


def _scaffold_strands(design: Design):
    return [s for s in design.strands if s.is_scaffold and not s.is_reference]


def _scaffold_fls(forced_ligations, coverage):
    """Forced ligations whose BOTH endpoints lie on scaffold-covered helices.

    Scaffold routing owns only these.  Overhang / staple-binding FLs (e.g. an
    overhang-duplex bind whose endpoint helix carries only staples, like a
    ``bound end to root`` binding) are NOT scaffold rungs — they must be ignored
    by scaffold routing and left untouched.  See ``memory/project_hinge_autoscaffold.md``.
    """
    return [
        fl for fl in forced_ligations
        if fl.three_prime_helix_id in coverage and fl.five_prime_helix_id in coverage
    ]


def _fls_all_rungs(fls, gp, rail_a, rail_b) -> bool:
    """True iff every given forced ligation is a gap rung (rail A ↔ rail B, same column)."""
    for fl in fls:
        ga, gb = gp[fl.three_prime_helix_id], gp[fl.five_prime_helix_id]
        if {ga[0], gb[0]} != {rail_a, rail_b} or ga[1] != gb[1]:
            return False
    return True


def _analyze_leaves(design: Design, scaffold_hids):
    """Return (rows, cols, leaf_a_rows, leaf_b_rows) or None if not a 2-leaf gap.

    Only scaffold-covered helices define the leaf grid; staple-only helices (e.g. an
    overhang / root-binding helix) are excluded so they don't break the rectangular
    bundle assumption.
    """
    scaf_helices = [h for h in design.helices if h.id in scaffold_hids]
    gp = {h.id: tuple(h.grid_pos) for h in scaf_helices if h.grid_pos is not None}
    if not gp or len(gp) != len(scaf_helices):
        return None
    rows = sorted({r for r, _ in gp.values()})
    cols = sorted({c for _, c in gp.values()})
    gaps = [i for i in range(len(rows) - 1) if rows[i + 1] - rows[i] > 1]
    if len(gaps) != 1:
        return None  # not a single clean gap → not a hinge this realizer handles
    gi = gaps[0]
    leaf_a, leaf_b = rows[: gi + 1], rows[gi + 1:]
    # rectangular bundle expected (every row × every col present)
    if len(gp) != len(rows) * len(cols):
        return None
    return rows, cols, leaf_a, leaf_b


def realize_hinge_weave(design: Design) -> tuple[Design, SeamedResult] | None:
    """Realize the full hinge weave as a single gate-clean scaffold strand.

    Returns ``(updated_design, result)`` or ``None`` if the realization is not
    applicable or fails any self-gate (caller falls back).
    """
    coverage = _scaffold_coverage(design)
    analysis = _analyze_leaves(design, set(coverage))
    if analysis is None:
        return None
    rows, cols, leaf_a, leaf_b = analysis
    n = len(cols)
    if n < 2 or n % 2 != 0:
        return None  # only even column counts (reciprocal rung pairs)

    rail_a, rail_b = leaf_a[-1], leaf_b[0]
    gp_pre = {h.id: tuple(h.grid_pos) for h in design.helices}
    # Scaffold routing owns only FLs with both endpoints on scaffold; overhang /
    # staple-binding FLs are preserved untouched and ignored here.
    scaf_fls = _scaffold_fls(design.forced_ligations, coverage)
    if not scaf_fls:
        return None
    # Every scaffold forced ligation must be a gap rung (inner rail A ↔ inner rail B,
    # same column).  An FL between lattice-adjacent helices is a one-off manual
    # anchor, not a hinge bridge → decline so the classic preserve pipeline handles it.
    for fl in scaf_fls:
        ga, gb = gp_pre[fl.three_prime_helix_id], gp_pre[fl.five_prime_helix_id]
        if {ga[0], gb[0]} != {rail_a, rail_b} or ga[1] != gb[1]:
            return None

    try:
        weave = weave_hinge_full(leaf_a, leaf_b, n)
    except ValueError:
        return None
    trail, rail_a, rail_b = weave.trail, weave.rail_a, weave.rail_b

    gp = {h.id: tuple(h.grid_pos) for h in design.helices}
    id_of = {v: k for k, v in gp.items()}
    helix_by_id = {h.id: h for h in design.helices}
    # The scaffold *duplex* (seed coverage) — crossover faces are relative to this,
    # not the helix geometry, which may already be pre-extended past the duplex.
    duplex = {
        hid: (min(iv["lo"] for iv in ivs), max(iv["hi"] for iv in ivs))
        for hid, ivs in coverage.items()
    }

    # A rail helix is entered/exited via its rung (forced ligation) at the GAP end,
    # so its every other crossover must sit at the OPPOSITE (outer) end — otherwise
    # the fold collides with the rung terminus and cannot ligate.  Determine which
    # end the rungs occupy (they sit at one shared face across all columns).
    rail_rows = {rail_a, rail_b}
    near_lo_votes = 0
    rung_count = 0
    for fl in scaf_fls:
        for hid, bp in (
            (fl.three_prime_helix_id, fl.three_prime_bp),
            (fl.five_prime_helix_id, fl.five_prime_bp),
        ):
            if gp[hid][0] in rail_rows and hid in duplex:
                lo, hi = duplex[hid]
                rung_count += 1
                near_lo_votes += (bp - lo) <= (hi - bp)
    gap_is_lo = rung_count == 0 or near_lo_votes * 2 >= rung_count
    rail_fold_face = "far" if gap_is_lo else "near"  # outer end, opposite the rung
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT

    passes = Counter(trail)

    def fwd(rc):
        return _is_forward(rc[0], rc[1])

    def is_rung(x, y):
        return {x[0], y[0]} == {rail_a, rail_b} and x[1] == y[1]

    # ── Classify every non-rung junction by its (direction-determined) face ──
    result = SeamedResult()
    pair_faces: dict[frozenset, list] = {}
    for x, y in zip(trail, trail[1:]):
        if is_rung(x, y):
            continue
        face = "far" if fwd(x) else "near"  # X's 3′ end: HI(far) if fwd else LO(near)
        pair_faces.setdefault(frozenset([x, y]), []).append((x, y, face))

    # ── Seam matching: split every non-turn double-passed helix exactly once ──
    turn = {trail[0], trail[-1]}
    for i in range(1, len(trail) - 1):
        if trail[i - 1] == trail[i + 1]:
            turn.add(trail[i])  # U-turn helix (full-length), not split
    to_seam = {h for h, c in passes.items() if c == 2 and h not in turn}
    seam_edges = [k for k in pair_faces if all(h in to_seam for h in k)]
    # A maximum-cardinality matching over the trail-junction edges: each matched
    # edge becomes a seam that splits BOTH its helices once.  Greedy can leave
    # helices uncovered where a maximum matching would not, so use the real thing.
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(to_seam)
    g.add_edges_from(tuple(k) for k in seam_edges)
    matching = nx.max_weight_matching(g, maxcardinality=True)
    matched = {h for edge in matching for h in edge}
    if any(h not in matched for h in to_seam):
        return None  # no perfect matching (some helix can't be split) → fall back
    seam_pairs = {frozenset(edge) for edge in matching}

    folds = [
        occ for key, occs in pair_faces.items() if key not in seam_pairs
        for occ in occs
    ]

    cur = design

    def site_near(rc, grid_y, target, descending):
        step = -1 if descending else 1
        bound = target - 200 if descending else target + 200
        for bp in range(target, bound, step):
            if _scaf_nb(cur, rc[0], rc[1], bp) == grid_y:
                return bp
        return None

    # ── Phase 1: seams (mid-helix double crossover, two adjacent valid sites) ──
    for key in seam_pairs:
        gx, gy, _ = pair_faces[key][0]
        hx, hy = id_of[gx], id_of[gy]
        sa = Direction.FORWARD if fwd(gx) else Direction.REVERSE
        sb = Direction.FORWARD if fwd(gy) else Direction.REVERSE
        lo = max(duplex[hx][0], duplex[hy][0])
        hi = min(duplex[hx][1], duplex[hy][1])
        mid = (lo + hi) // 2
        valid = [bp for bp in range(lo, hi + 1) if _scaf_nb(cur, gx[0], gx[1], bp) == gy]
        best, adj = 1e9, None
        for j in range(len(valid) - 1):
            if valid[j + 1] == valid[j] + 1:
                d = abs((valid[j] + valid[j + 1]) / 2 - mid)
                if d < best:
                    best, adj = d, (valid[j], valid[j + 1])
        if adj is None:
            return None
        for bp in adj:
            ha = HalfCrossover(helix_id=hx, index=bp, strand=sa)
            hb = HalfCrossover(helix_id=hy, index=bp, strand=sb)
            cur, _xo = _place_xover(
                cur, ha, hb, _nick_bp(bp, sa, period, bow),
                _nick_bp(bp, sb, period, bow), "manual", result.warnings,
            )
        result.seam_xovers += 1

    # ── Phase 2: end folds at the direction-determined face (extend for margin) ──
    for gx, gy, face in folds:
        # A fold touching a rail helix must sit at the rail's outer end (its gap
        # end is consumed by the rung), overriding the direction-determined face.
        if gx[0] in rail_rows or gy[0] in rail_rows:
            face = rail_fold_face
        hx, hy = id_of[gx], id_of[gy]
        sa = Direction.FORWARD if fwd(gx) else Direction.REVERSE
        sb = Direction.FORWARD if fwd(gy) else Direction.REVERSE
        lox, hix = duplex[hx]
        loy, hiy = duplex[hy]
        if face == "near":
            bp = site_near(gx, gy, lox - 3, descending=True)
            if bp is not None:
                cur = _extend_helix_lo(cur, helix_by_id, hx, bp)
                cur = _extend_helix_lo(cur, helix_by_id, hy, bp)
                cur = _extend_scaf_domain_lo(cur, hx, lox, bp)
                cur = _extend_scaf_domain_lo(cur, hy, loy, bp)
        else:
            bp = site_near(gx, gy, hix + 3, descending=False)
            if bp is not None:
                cur = _extend_helix_hi(cur, helix_by_id, hx, bp)
                cur = _extend_helix_hi(cur, helix_by_id, hy, bp)
                cur = _extend_scaf_domain_hi(cur, hx, hix, bp)
                cur = _extend_scaf_domain_hi(cur, hy, hiy, bp)
        if bp is None:
            return None
        ha = HalfCrossover(helix_id=hx, index=bp, strand=sa)
        hb = HalfCrossover(helix_id=hy, index=bp, strand=sb)
        cur, _xo = _place_xover(
            cur, ha, hb, _nick_bp(bp, sa, period, bow),
            _nick_bp(bp, sb, period, bow), "manual", result.warnings,
        )
        if face == "near":
            result.near_end_xovers += 1
        else:
            result.far_end_xovers += 1

    # ── Open the closed loop with a buried, mid-structure nick ──
    cur = _linearize_circular_scaffolds(cur, result)

    # ── Self-gate: never return anything non-compliant ──
    if any("skip" in w or "No " in w for w in result.warnings):
        return None
    scaf = _scaffold_strands(cur)
    if len(scaf) != 1:
        return None
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp, f.five_prime_helix_id, f.five_prime_bp)
        for f in design.forced_ligations
    }
    new_fls = {
        (f.three_prime_helix_id, f.three_prime_bp, f.five_prime_helix_id, f.five_prime_bp)
        for f in cur.forced_ligations
    }
    if new_fls != orig_fls:
        return None
    if scaffold_routing_invariants(cur, require_seams=True):
        return None
    if not validate_design(cur).passed:
        return None
    return cur, result


def realize_hinge_weave_seamless(
    design: Design,
) -> tuple[Design, SeamlessResult] | None:
    """Realize a hinge as a single SEAMLESS scaffold strand (no seams).

    Seamless routing is single-pass.  The route is a Hamiltonian CYCLE (a closed
    loop, so it reopens to one strand with a buried mid-bundle nick, exactly like
    the seamed route — no dangling ends): a horizontal SPINE along one outer row
    plus a boustrophedon SNAKE over the remaining rows, whose every column sweep
    crosses the gap once via that column's rung.

    Two parities are load-bearing (decoded from ``workspace/3x2_hinge_seamless.nadoc``):

    * **Spine row by leaf thickness** — top outer row for even ``k``, bottom outer
      row for odd ``k``.  Each inner rail is entered/exited via its rung at the gap
      end, so its leaf-side fold must sit at the outer end; that requires the rail's
      column to be swept in a direction set by ``c ≡ k (mod 2)``, and the cycle's
      closure fixes column 0's direction — which the spine-row choice aligns.
    * **Rail-fold-face override** — any fold touching a rail goes to the outer
      (non-rung) end (the same rule as the seamed realizer).

    Self-gated (``require_seams=False``): returns ``None`` unless the result is one
    scaffold strand, FLs preserved, every placement clean, invariant-clean and
    validated.
    """
    from backend.core.seamless_router import SeamlessResult  # lazy: avoid import cycle

    coverage = _scaffold_coverage(design)
    analysis = _analyze_leaves(design, set(coverage))
    if analysis is None:
        return None
    rows, cols, leaf_a, leaf_b = analysis
    n = len(cols)
    if n < 2 or n % 2 != 0:
        return None
    k = len(leaf_a)
    rail_a, rail_b = leaf_a[-1], leaf_b[0]
    rail_rows = {rail_a, rail_b}
    gp = {h.id: tuple(h.grid_pos) for h in design.helices}
    # Scaffold routing owns only both-endpoints-scaffold FLs; overhang / staple-
    # binding FLs are preserved untouched and ignored here.
    scaf_fls = _scaffold_fls(design.forced_ligations, coverage)
    if not scaf_fls or not _fls_all_rungs(scaf_fls, gp, rail_a, rail_b):
        return None

    id_of = {v: key for key, v in gp.items()}
    helix_by_id = {h.id: h for h in design.helices}
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT
    duplex = {
        hid: (min(iv["lo"] for iv in ivs), max(iv["hi"] for iv in ivs))
        for hid, ivs in coverage.items()
    }
    # Which end the rungs occupy → rail folds go to the opposite (outer) end.
    near_lo, rung_n = 0, 0
    for fl in scaf_fls:
        for hid, bp in (
            (fl.three_prime_helix_id, fl.three_prime_bp),
            (fl.five_prime_helix_id, fl.five_prime_bp),
        ):
            if gp[hid][0] in rail_rows and hid in duplex:
                lo, hi = duplex[hid]
                rung_n += 1
                near_lo += (bp - lo) <= (hi - bp)
    gap_is_lo = rung_n == 0 or near_lo * 2 >= rung_n
    rail_fold_face = "far" if gap_is_lo else "near"

    # Hamiltonian cycle: spine row (top for even k, bottom for odd k) + a column
    # boustrophedon over the remaining rows that crosses every gap rung.
    rows_all = leaf_a + leaf_b
    if k % 2 == 0:
        spine_row, inner = rows_all[0], rows_all[1:]          # col 0 sweeps down
    else:
        spine_row, inner = rows_all[-1], list(reversed(rows_all[:-1]))  # col 0 up
    trail: list[tuple[int, int]] = [(spine_row, 0)]
    for c in range(n):
        seq = inner if c % 2 == 0 else list(reversed(inner))
        trail.extend((r, c) for r in seq)
    trail.extend((spine_row, c) for c in range(n - 1, 0, -1))

    def fwd(rc):
        return _is_forward(rc[0], rc[1])

    def is_rung(x, y):
        return {x[0], y[0]} == {rail_a, rail_b} and x[1] == y[1]

    def site_near(rc, grid_y, target, descending):
        step = -1 if descending else 1
        bound = target - 200 if descending else target + 200
        for bp in range(target, bound, step):
            if _scaf_nb(cur, rc[0], rc[1], bp) == grid_y:
                return bp
        return None

    cur = design
    result = SeamlessResult()
    # Edges include the wraparound (spine end → start) so the route closes into a
    # cycle; the closing crossover stays unligated and _linearize buries the nick.
    for x, y in zip(trail, trail[1:] + [trail[0]]):
        if is_rung(x, y):
            continue  # the rung is the pre-connected FL bridge — preserved
        face = "far" if fwd(x) else "near"
        if x[0] in rail_rows or y[0] in rail_rows:
            face = rail_fold_face
        hx, hy = id_of[x], id_of[y]
        sa = Direction.FORWARD if fwd(x) else Direction.REVERSE
        sb = Direction.FORWARD if fwd(y) else Direction.REVERSE
        lox, hix = duplex[hx]
        loy, hiy = duplex[hy]
        if face == "near":
            bp = site_near(x, y, lox - 3, descending=True)
            if bp is not None:
                cur = _extend_helix_lo(cur, helix_by_id, hx, bp)
                cur = _extend_helix_lo(cur, helix_by_id, hy, bp)
                cur = _extend_scaf_domain_lo(cur, hx, lox, bp)
                cur = _extend_scaf_domain_lo(cur, hy, loy, bp)
        else:
            bp = site_near(x, y, hix + 3, descending=False)
            if bp is not None:
                cur = _extend_helix_hi(cur, helix_by_id, hx, bp)
                cur = _extend_helix_hi(cur, helix_by_id, hy, bp)
                cur = _extend_scaf_domain_hi(cur, hx, hix, bp)
                cur = _extend_scaf_domain_hi(cur, hy, hiy, bp)
        if bp is None:
            return None
        ha = HalfCrossover(helix_id=hx, index=bp, strand=sa)
        hb = HalfCrossover(helix_id=hy, index=bp, strand=sb)
        cur, _xo = _place_xover(
            cur, ha, hb, _nick_bp(bp, sa, period, bow),
            _nick_bp(bp, sb, period, bow), "manual", result.warnings,
        )
        result.end_xovers += 1

    cur = _linearize_circular_scaffolds(cur, result)

    if any("skip" in w or "No " in w for w in result.warnings):
        return None
    scaf = _scaffold_strands(cur)
    if len(scaf) != 1:
        return None
    orig = {
        (f.three_prime_helix_id, f.three_prime_bp, f.five_prime_helix_id, f.five_prime_bp)
        for f in design.forced_ligations
    }
    new = {
        (f.three_prime_helix_id, f.three_prime_bp, f.five_prime_helix_id, f.five_prime_bp)
        for f in cur.forced_ligations
    }
    if new != orig:
        return None
    if scaffold_routing_invariants(cur, require_seams=False):
        return None
    if not validate_design(cur).passed:
        return None
    return cur, result
