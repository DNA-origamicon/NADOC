"""
Section scaffold router — single-strand routing for irregular *multi-section*
designs (teeth, dumbbells) that the per-helix seamed router fragments.

Background (ISSUE-8).  The seamed router models routing per HELIX and finds a
Hamiltonian path over the helix-adjacency graph.  A design with a continuous
base slab plus discrete axial "teeth" (helices that exist only in a few bp
windows) has articulation points with no Hamiltonian path, so the scaffold
fragments into many strands.  This module routes such designs to ONE scaffold
strand by decomposition + splice instead of one global path:

  1. Decompose into UNIFORM sub-bundles: the continuous helices (one coverage
     section each) form the TRUNK; the segmented helices, grouped by bp-overlap,
     form WINDOWS.
  2. Route each sub-bundle with the existing, proven ``auto_scaffold_seamed``
     (trunk → one linear, full-coverage strand; each window → a single loop that
     the router leaves nicked at one bp on one helix — a near-free cycle).
  3. 2-opt domain-surgery SPLICE each window cycle into the trunk at a grid-
     adjacent helix via a reciprocal double crossover (X, X+1).
  4. Recompute helix geometry so domains never overflow their helix extent.

Three-Layer Law: only topology + the helix axis extension (physical room for the
added nucleotides) are touched, exactly as the seamed router already does.

DISPATCH: ``auto_scaffold_seamed`` routes any design with a multi-section helix
through here by default (uniform prisms + matched-ends behaviour are untouched —
they have no multi-section helix; designs with forced ligations are never
overridden).  ``route_sections`` returns ``None`` for anything it cannot cleanly
route, so the seamed pipeline falls back to its classic path.

Window end-turns are placed at the nearest valid crossover to each tooth's OWN
ragged face (bounded ``auto_scaffold_seamed_bounded``), so the inter-tooth gaps
stay clear: on the clean teeth fixture this routes to 1 strand with a worst
gap dip of ~9 bp and ~32 bp of every gap left open (vs the per-helix seamed path,
which bridges a gap).  This is a "tests pass but visually wrong" area — the gap
invariants in tests/test_section_router.py guard it.
"""

from __future__ import annotations

from collections import defaultdict

from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    Strand,
    StrandType,
)
from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
from backend.core.models import LatticeType
from backend.core.seamed_router import (
    _HC_SCAF_BOW_RIGHT,
    _SQ_SCAF_BOW_RIGHT,
    SeamedResult,
    _extend_helix_hi,
    _extend_helix_lo,
    _is_forward,
    _nick_bp,
    _scaf_nb,
    _scaffold_coverage,
    append_single_strand_warning,
    auto_scaffold_seamed,
    auto_scaffold_seamed_bounded,
)

# Crossover process ids the seamed router emits for SCAFFOLD routing (so we can
# preserve everything else — staple crossovers, manual edges — untouched).
_SCAF_ROUTE_PREFIXES = ("auto_scaffold_",)
_SCAF_ROUTE_IDS = frozenset({"create_near_ends", "create_far_ends"})

_SECTION_PROCESS_ID = "auto_scaffold_seamed:section"


def has_multisection_helix(coverage: dict[str, list[dict]]) -> bool:
    """True when any helix's scaffold coverage spans more than one section."""
    return any(len(ivs) > 1 for ivs in coverage.values())


# ── Decomposition ──────────────────────────────────────────────────────────────

def _decompose(design: Design) -> tuple[dict[str, dict], list[dict[str, tuple[int, int]]]]:
    """Split scaffold coverage into the continuous TRUNK and segmented WINDOWS.

    Returns ``(trunk_sections, windows)`` where ``trunk_sections`` is
    ``{helix_id: (lo, hi)}`` for every single-section helix and each window is a
    ``{helix_id: (lo, hi)}`` group of segmented sections that mutually bp-overlap.
    Iteration is sorted for PYTHONHASHSEED-independence.
    """
    coverage = _scaffold_coverage(design)
    trunk = {h: (coverage[h][0]["lo"], coverage[h][0]["hi"])
             for h in coverage if len(coverage[h]) == 1}

    seg: list[tuple[str, int, int]] = []
    for h in coverage:
        if len(coverage[h]) > 1:
            for iv in coverage[h]:
                seg.append((h, iv["lo"], iv["hi"]))
    seg.sort(key=lambda t: (t[1], t[2], t[0]))

    windows: list[dict[str, tuple[int, int]]] = []
    spans: list[tuple[int, int]] = []
    for hid, lo, hi in seg:
        placed = False
        for wi, (wlo, whi) in enumerate(spans):
            if lo <= whi and hi >= wlo:  # bp-overlap → same window
                windows[wi][hid] = (lo, hi)
                spans[wi] = (min(wlo, lo), max(whi, hi))
                placed = True
                break
        if not placed:
            windows.append({hid: (lo, hi)})
            spans.append((lo, hi))
    return trunk, windows


def _sub_seed(design: Design, sections: dict[str, tuple[int, int]]) -> Design:
    """Clean per-helix scaffold seed sub-design over ``sections`` (no crossovers).

    Only the sub-bundle's helices are included so the seamed router routes them in
    isolation; each helix gets one scaffold domain spanning its section in the
    lattice-correct direction.
    """
    hb = {h.id: h for h in design.helices}
    helices = [h for h in design.helices if h.id in sections]
    strands: list[Strand] = []
    for hid, (lo, hi) in sorted(sections.items()):
        r, c = hb[hid].grid_pos
        if _is_forward(r, c):
            dom = Domain(helix_id=hid, start_bp=lo, end_bp=hi, direction=Direction.FORWARD)
        else:
            dom = Domain(helix_id=hid, start_bp=hi, end_bp=lo, direction=Direction.REVERSE)
        strands.append(Strand(id=f"section_seed_{hid}", domains=[dom],
                              strand_type=StrandType.SCAFFOLD))
    return design.copy_with(helices=helices, strands=strands, crossovers=[])


def _route_subbundle(
    design: Design, sections: dict[str, tuple[int, int]], *,
    matched: bool = False, seamless: bool = False, close_cycle: bool = False,
):
    """Route a sub-bundle seed; return (strand, crossovers).

    The seed has no crossovers, so every crossover in the routed result is from this
    routing (collect ALL of them — seam/end turns and bridge/zig alike lack a uniform
    prefix).  The routing style is chosen so the spliced output keeps a single style:

    - ``seamless=True`` (seamless-mode section router) → ``auto_scaffold_seamless``:
      each sub-bundle is routed zig/bridge with NO seam.  A whole multi-section design
      fragments under the seamless router, but each uniform sub-bundle routes to one
      clean strand, so decomposing + splicing keeps it seamless AND single-strand.
    - Windows (seamed, ``matched=False``) → ``auto_scaffold_seamed_bounded``:
      per-helix-face turns at each tooth's OWN face so the inter-tooth gaps stay clear.
    - The trunk (seamed, ``matched=True``) → ``auto_scaffold_seamed`` = MATCHED ends
      (far = near + P) so the two farthest faces puzzle-fit for end-to-end
      polymerization; the ~one-period outer extension IS the periodic-boundary spacing.
    """
    seed = _sub_seed(design, sections)
    if seamless:
        from backend.core.seamless_router import auto_scaffold_seamless
        routed, _res = auto_scaffold_seamless(seed, close_cycle=close_cycle)
    elif matched:
        routed, _res = auto_scaffold_seamed(seed)
    else:
        routed, _res = auto_scaffold_seamed_bounded(seed)
    scaf = [s for s in routed.strands if s.is_scaffold and not s.is_reference]
    # The splice assumes each sub-bundle is one clean strand.  A ragged or
    # already-routed input can make the seamed router fragment even a sub-bundle;
    # signal that so the caller falls back instead of splicing a partial strand
    # (which would silently DROP the un-routed coverage).
    if len(scaf) != 1:
        return None, []
    return scaf[0], list(routed.crossovers)


# ── Domain-surgery helpers ──────────────────────────────────────────────────────

def _covers(dom: Domain, X: int) -> bool:
    return min(dom.start_bp, dom.end_bp) <= X and max(dom.start_bp, dom.end_bp) >= X + 1


def _split_dom(dom: Domain, X: int) -> tuple[Domain, Domain]:
    """Split ``dom`` at the X|X+1 gap → (part covering ≤X, part covering ≥X+1)."""
    lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
    if dom.direction == Direction.FORWARD:
        a = Domain(helix_id=dom.helix_id, start_bp=lo, end_bp=X, direction=Direction.FORWARD)
        b = Domain(helix_id=dom.helix_id, start_bp=X + 1, end_bp=hi, direction=Direction.FORWARD)
    else:
        a = Domain(helix_id=dom.helix_id, start_bp=X, end_bp=lo, direction=Direction.REVERSE)
        b = Domain(helix_id=dom.helix_id, start_bp=hi, end_bp=X + 1, direction=Direction.REVERSE)
    return a, b


def _revd(dm: Domain) -> Domain:
    return Domain(
        helix_id=dm.helix_id, start_bp=dm.end_bp, end_bp=dm.start_bp,
        direction=Direction.FORWARD if dm.direction == Direction.REVERSE else Direction.REVERSE,
    )


def _cut_window_cycle(wdoms: list[Domain], helix_id: str, X: int) -> list[Domain] | None:
    """Linearise the window loop so the chain starts at ``helix_id[X+1]`` and ends at ``helix_id[X]``.

    ``wdoms`` is the router's window strand in 5'→3' order; its 5'/3' sit on one
    helix at adjacent bp, so it is a loop nicked at one spot.  Find the visit of
    ``helix_id`` covering [X, X+1], split it there, and rotate the cycle so the
    cut sits at the chain ends — ready to graft into the trunk between 1_0[X] and
    1_0[X+1].
    """
    for i, dm in enumerate(wdoms):
        if dm.helix_id == helix_id and _covers(dm, X):
            a, b = _split_dom(dm, X)  # a=[..X], b=[X+1..]
            # which half is traversed first in 5'->3' order
            first, second = (a, b) if dm.direction == Direction.FORWARD else (b, a)
            rest = wdoms[i + 1:] + wdoms[:i]
            chain = [second] + rest + [first]  # cut between first/second; wrap
            # ensure chain starts at the X+1 side
            head = chain[0]
            if not (head.helix_id == helix_id and (head.start_bp == X + 1 or head.end_bp == X + 1)):
                chain = [_revd(d) for d in reversed(chain)]
            return chain
    return None


def _adj_pair_in_domain(
    design: Design, hb: dict, hT: str, hW_grid: tuple[int, int],
    whid: str, lo: int, hi: int, tdoms: list[Domain], wdoms: list[Domain],
) -> int | None:
    """Valid double-pair (X, X+1) nearest the tooth MIDPOINT, inside ONE trunk domain
    on ``hT`` and ONE window domain on ``whid``.

    The trunk↔tooth reciprocal double crossover is the scaffold's dip into the tooth;
    placing it near the centre of the tooth's bp-span (rather than at the first valid
    site near the lo face) keeps the connection balanced between the two tooth faces.
    """
    r, c = hb[hT].grid_pos
    vb = [b for b in range(lo, hi + 1) if _scaf_nb(design, r, c, b) == hW_grid]
    mid = (lo + hi) / 2.0
    candidates = [
        vb[i] for i in range(len(vb) - 1)
        if vb[i + 1] == vb[i] + 1
        and any(d.helix_id == hT and _covers(d, vb[i]) for d in tdoms)
        and any(d.helix_id == whid and _covers(d, vb[i]) for d in wdoms)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda X: abs((X + 0.5) - mid))


def _pull_window_turns(
    main_doms: list[Domain],
    all_x: list[Crossover],
    design: Design,
    window_secs: dict[str, list[tuple[int, int]]],
) -> tuple[list[Domain], list[Crossover]]:
    """Pull each window end-turn back to the first valid crossover at-or-just-past its
    nominal face, so extension past the tooth faces is BOUNDED (~one turn) instead of
    the seamed router's `+3 … +period` (period 32 on SQ → up to +32 bp of gap-fill).

    This reproduces the reference's design rule (the user-confirmed physics): turns sit
    at/just past each tooth face with only the bounded turn-around room, never the full
    crossover-period overshoot.  Search is constrained to t ≥ nominal hi (far) / t ≤
    nominal lo (near) so coverage is never lost; the nearest such valid bp is minimal.

    ⚠ WIP — NOT YET WIRED into route_sections.  First cut regressed (domain-retarget
    matched/mutated the wrong domain → 6 bad transitions + a giant corrupted domain) and
    it does not yet bound the turn-around (path-end / parked-open) helix, which carries
    the largest extension.  Two fixes needed before wiring: (1) scope `_retarget` to the
    one domain whose terminal == old_term AND whose body lies within the turn's tooth
    section (not just the first match); (2) separately bound the turn-around helix's span.
    See the ISSUE-8 plan for the reference extension spec (≤10 bp, gap-aware).
    """
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT
    hb = {h.id: h for h in design.helices}
    doms = list(main_doms)

    def _nearest_section(hid: str, i: int) -> tuple[int, int]:
        return min(window_secs[hid], key=lambda s: min(abs(i - s[0]), abs(i - s[1])))

    def _valid(hid_a: str, hid_b: str, t: int) -> bool:
        ra, ca = hb[hid_a].grid_pos
        rb, cb = hb[hid_b].grid_pos
        return (_scaf_nb(design, ra, ca, t) == (rb, cb)
                and _scaf_nb(design, rb, cb, t) == (ra, ca))

    def _retarget(hid: str, old_term: int, new_term: int, far: bool) -> None:
        for idx, d in enumerate(doms):
            if d.helix_id != hid:
                continue
            hi_end = max(d.start_bp, d.end_bp)
            lo_end = min(d.start_bp, d.end_bp)
            if far and hi_end == old_term:
                key = "start_bp" if d.start_bp >= d.end_bp else "end_bp"
                doms[idx] = d.model_copy(update={key: new_term})
                return
            if (not far) and lo_end == old_term:
                key = "start_bp" if d.start_bp <= d.end_bp else "end_bp"
                doms[idx] = d.model_copy(update={key: new_term})
                return

    new_x: list[Crossover] = []
    for xo in all_x:
        if (xo.process_id not in ("create_near_ends", "create_far_ends")
                or xo.half_a.helix_id not in window_secs
                or xo.half_b.helix_id not in window_secs):
            new_x.append(xo)
            continue
        a, b = xo.half_a, xo.half_b
        i = a.index
        sA, sB = _nearest_section(a.helix_id, i), _nearest_section(b.helix_id, i)
        far = i > (sA[0] + sA[1]) / 2
        face = max(sA[1], sB[1]) if far else min(sA[0], sB[0])
        # nearest valid bp at-or-just-past the face, never crossing into the section
        rng = range(face, i + 1) if far else range(face, i - 1, -1)
        t = next((bp for bp in rng if _valid(a.helix_id, b.helix_id, bp)), i)
        if t != i:
            _retarget(a.helix_id, _nick_bp(i, a.strand, period, bow),
                      _nick_bp(t, a.strand, period, bow), far)
            _retarget(b.helix_id, _nick_bp(i, b.strand, period, bow),
                      _nick_bp(t, b.strand, period, bow), far)
        new_x.append(Crossover(
            half_a=HalfCrossover(helix_id=a.helix_id, index=t, strand=a.strand),
            half_b=HalfCrossover(helix_id=b.helix_id, index=t, strand=b.strand),
            process_id=xo.process_id,
        ))
    return doms, new_x


def _recompute_helices(design: Design, domains: list[Domain]):
    """Extend each helix geometry to cover the final strand's domain bp-range (never shrink)."""
    rng: dict[str, list[int]] = defaultdict(lambda: [10 ** 9, -10 ** 9])
    for dm in domains:
        lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
        rng[dm.helix_id][0] = min(rng[dm.helix_id][0], lo)
        rng[dm.helix_id][1] = max(rng[dm.helix_id][1], hi)
    hbid = {h.id: h for h in design.helices}
    cur = design
    for hid in sorted(rng):
        lo, hi = rng[hid]
        cur = _extend_helix_lo(cur, hbid, hid, lo)
        cur = _extend_helix_hi(cur, hbid, hid, hi)
    return cur.helices


# ── Entry point ─────────────────────────────────────────────────────────────────

def route_sections(design: Design, *, seamless: bool = False):
    """Route an irregular multi-section design to a single scaffold strand.

    ``seamless`` selects the routing style for the sub-bundles and the result type:
    seamed (default) → ``SeamedResult`` with a matched, polymerizable trunk; seamless
    → ``SeamlessResult`` with zig/bridge sub-bundles (no seam).  Either way the
    decompose → route-each-sub-bundle → 2-opt splice machinery yields ONE strand.

    Returns ``(updated_design, result)``, or ``None`` when the design is not a
    section-router case (no continuous trunk, no windows, or a forced ligation is
    present) so the caller can fall back to its existing pipeline.
    """
    if design.forced_ligations:
        return None  # never override manual anchors

    hb = {h.id: h for h in design.helices}
    trunk_sec, windows = _decompose(design)
    if not trunk_sec or not windows:
        return None

    if seamless:
        from backend.core.seamless_router import SeamlessResult
        result = SeamlessResult()
    else:
        result = SeamedResult()

    # The trunk closes into a circle so the single nick lands BURIED mid-bundle.
    # Seamed mode → matched ends (polymerizable).  Seamless mode → a fully-seamless
    # Hamiltonian-CYCLE trunk (zero backbone seams, like the hand reference); if the
    # bundle can't close cleanly into a seamless cycle (e.g. some honeycomb rings),
    # fall back to a bounded-seamed trunk (buried nick, a few backbone seams).
    if seamless:
        trunk_strand, trunk_x = _route_subbundle(
            design, trunk_sec, seamless=True, close_cycle=True
        )
        if trunk_strand is None:
            trunk_strand, trunk_x = _route_subbundle(design, trunk_sec)
    else:
        trunk_strand, trunk_x = _route_subbundle(design, trunk_sec, matched=True)
    if trunk_strand is None:
        return None
    main_doms = list(trunk_strand.domains)
    all_x = list(trunk_x)

    for wi, w in enumerate(windows):
        lo = min(l for l, _ in w.values())
        hi = max(h for _, h in w.values())
        w_strand, w_x = _route_subbundle(design, w, seamless=seamless)
        if w_strand is None:
            # A window that won't route cleanly can't be spliced without dropping
            # its coverage — bail to the existing router rather than ship a partial.
            return None
        wdoms = list(w_strand.domains)

        # window helix nearest the trunk (grid-adjacent to a continuous helix)
        wh = sorted(w, key=lambda h: tuple(hb[h].grid_pos))[0]
        rW, cW = hb[wh].grid_pos
        Tid = next(
            (ch for ch in sorted(trunk_sec)
             if any(_scaf_nb(design, *hb[ch].grid_pos, b) == (rW, cW)
                    for b in range(lo, hi + 1))),
            None,
        )
        if Tid is None:
            return None  # no trunk-adjacent continuous helix — fall back
        X = _adj_pair_in_domain(design, hb, Tid, (rW, cW), wh, lo, hi, main_doms, wdoms)
        if X is None:
            return None  # no valid in-domain double-pair — fall back

        ti = next(i for i, dm in enumerate(main_doms) if dm.helix_id == Tid and _covers(dm, X))
        Tdom = main_doms[ti]
        Ta, Tb = _split_dom(Tdom, X)  # Ta=[..X], Tb=[X+1..]
        wchain = _cut_window_cycle(wdoms, wh, X)
        if wchain is None:
            return None  # cycle cut failed — fall back
        if Tdom.direction == Direction.REVERSE:
            newseg = [Tb] + wchain + [Ta]
        else:
            newseg = [Ta] + wchain + [Tb]
        main_doms = main_doms[:ti] + newseg + main_doms[ti + 1:]
        all_x += w_x

        rT, cT = hb[Tid].grid_pos
        sT = Direction.FORWARD if _is_forward(rT, cT) else Direction.REVERSE
        sW = Direction.FORWARD if _is_forward(rW, cW) else Direction.REVERSE
        for bp in (X, X + 1):
            all_x.append(Crossover(
                half_a=HalfCrossover(helix_id=Tid, index=bp, strand=sT),
                half_b=HalfCrossover(helix_id=wh, index=bp, strand=sW),
                process_id=_SECTION_PROCESS_ID,
            ))
        # The trunk↔tooth dip is a reciprocal double crossover — count it as the
        # bridge it is in seamless mode, or a seam in seamed mode.
        if seamless:
            result.bridge_xovers += 2
        else:
            result.seam_xovers += 2

    # Assemble the final design: the single section strand replaces every active
    # scaffold strand; reference + non-scaffold strands and non-routing crossovers
    # are preserved.
    keep_strands = [s for s in design.strands if not (s.is_scaffold and not s.is_reference)]
    keep_xovers = [xo for xo in design.crossovers if not _is_scaffold_route_xover(xo)]
    strand = Strand(id="scaffold_section_route", domains=main_doms, strand_type=StrandType.SCAFFOLD)
    helices = _recompute_helices(design, main_doms)
    out = design.copy_with(
        helices=helices,
        strands=keep_strands + [strand],
        crossovers=keep_xovers + all_x,
    )
    append_single_strand_warning(out, result)
    return out, result


def _is_scaffold_route_xover(xo: Crossover) -> bool:
    pid = xo.process_id or ""
    return pid.startswith(_SCAF_ROUTE_PREFIXES) or pid in _SCAF_ROUTE_IDS or pid == _SECTION_PROCESS_ID
