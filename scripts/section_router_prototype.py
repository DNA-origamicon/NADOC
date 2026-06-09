"""Full section-router build: router-trunk + router-window-cycles + 2-opt splice.

Validates a single full-coverage scaffold strand on teeth (and later dumbbell).
"""
import json, sys
from collections import defaultdict
from backend.core.models import Design, Domain, Strand, StrandType, Direction, HalfCrossover, Crossover
from backend.core import seamed_router as SR
import importlib.util, os
_HARNESS = os.path.join(os.path.dirname(__file__), 'section_router_harness.py')
_s = importlib.util.spec_from_file_location('h', _HARNESS)
H = importlib.util.module_from_spec(_s); _s.loader.exec_module(H)


def route_subbundle(design, sections):
    """Route a sub-bundle seed with the existing router; return its single scaffold strand."""
    routed, res = SR.auto_scaffold_seamed(H.sub_seed(design, sections))
    scaf = [s for s in routed.strands if s.is_scaffold and not s.is_reference]
    # sub-seed had no crossovers, so every crossover here is from this routing
    # (seam = auto_scaffold_seamed:seam, ends = create_near_ends/create_far_ends).
    return scaf[0], list(routed.crossovers)


def split_dom(dom, X):
    """Split a domain at the X|X+1 gap → (part_le_X, part_ge_Xp1) respecting direction."""
    lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
    if dom.direction == Direction.FORWARD:
        a = Domain(helix_id=dom.helix_id, start_bp=lo, end_bp=X, direction=Direction.FORWARD)
        b = Domain(helix_id=dom.helix_id, start_bp=X + 1, end_bp=hi, direction=Direction.FORWARD)
    else:
        a = Domain(helix_id=dom.helix_id, start_bp=X, end_bp=lo, direction=Direction.REVERSE)
        b = Domain(helix_id=dom.helix_id, start_bp=hi, end_bp=X + 1, direction=Direction.REVERSE)
    return a, b  # a covers [lo..X], b covers [X+1..hi]


def covers(dom, X):
    return min(dom.start_bp, dom.end_bp) <= X and max(dom.start_bp, dom.end_bp) >= X + 1


def cut_window_cycle(wdoms, helix_id, X):
    """Linearize the window cycle so the chain starts at helix_id[X+1] and ends at helix_id[X].

    wdoms is the cyclic domain list (5'->3'); find the visit of helix_id covering [X,X+1],
    split it, and rotate so the X+1-part is first and the X-part is last.
    """
    for i, dm in enumerate(wdoms):
        if dm.helix_id == helix_id and covers(dm, X):
            a, b = split_dom(dm, X)  # a=[..X], b=[X+1..]
            # In 5'->3' order the domain runs start->end. Determine which part is traversed first.
            if dm.direction == Direction.FORWARD:
                # forward: ..X (a) comes before X+1.. (b) -> order a,b
                first_half, second_half = a, b
            else:
                # reverse: hi->lo, so X+1.. (b) comes before ..X (a)
                first_half, second_half = b, a
            # cyclic chain that begins right AFTER the cut going through X+1 side, ends at X side.
            # We want chain starting at helix[X+1] (b) and ending at helix[X] (a).
            rest = wdoms[i + 1:] + wdoms[:i]  # the rest of the cycle, in order, after this domain
            # The original traversal at i was first_half then second_half. We cut between them.
            # chain = second_half ... wrap ... first_half  (so it starts after the cut, ends before)
            chain = [second_half] + rest + [first_half]
            # Ensure chain starts at X+1 side and ends at X side:
            if not (chain[0].helix_id == helix_id and (chain[0].start_bp == X + 1 or chain[0].end_bp == X + 1)):
                # second_half was the X side -> swap by reversing whole chain polarity
                chain = [_revd(d) for d in reversed(chain)]
            return chain
    return None


def _revd(dm):
    return Domain(helix_id=dm.helix_id, start_bp=dm.end_bp, end_bp=dm.start_bp,
                  direction=Direction.FORWARD if dm.direction == Direction.REVERSE else Direction.REVERSE)


def adj_pair_in_domain(design, hb, hT, hW_grid, lo, hi, tdoms, wdoms):
    """Find a valid double-pair (X,X+1) inside ONE trunk domain on hT and ONE window domain on the W helix."""
    r, c = hb[hT].grid_pos
    vb = [b for b in range(lo, hi + 1) if SR._scaf_nb(design, r, c, b) == hW_grid]
    whid = next(h for h in [f'h_XY_{hW_grid[0]}_{hW_grid[1]}'] )
    for i in range(len(vb) - 1):
        if vb[i + 1] != vb[i] + 1:
            continue
        X = vb[i]
        if not any(d.helix_id == hT and covers(d, X) for d in tdoms):
            continue
        if not any(d.helix_id == whid and covers(d, X) for d in wdoms):
            continue
        return X
    return None


def build(fixture, out=None):
    d = Design(**json.load(open(fixture)))
    hb = {h.id: h for h in d.helices}
    cont, windows = H.decompose(d)
    trunk_sec = {h: (iv['lo'], iv['hi']) for h, iv in cont.items()}
    Tstr, Tx = route_subbundle(d, trunk_sec)
    main_doms = list(Tstr.domains)
    all_x = list(Tx)

    for wi, w in enumerate(windows):
        lo = min(l for l, _ in w.values()); hi = max(h for _, h in w.values())
        Wstr, Wx = route_subbundle(d, w)
        wdoms = list(Wstr.domains)
        # trunk helix = the row-(continuous) helix grid-adjacent to a window helix
        wh = sorted(w, key=lambda h: tuple(hb[h].grid_pos))[0]
        rW, cW = hb[wh].grid_pos
        # nearest continuous helix grid-adjacent: same col, row-1 (teeth) — general: search cont for adjacency
        Tid = None
        for ch in cont:
            r2, c2 = hb[ch].grid_pos
            # grid adjacency by a valid scaf neighbor into this window helix within [lo,hi]
            if any(SR._scaf_nb(d, r2, c2, b) == (rW, cW) for b in range(lo, hi + 1)):
                Tid = ch; break
        if Tid is None:
            print(f'window{wi}: no trunk-adjacent continuous helix'); return
        X = adj_pair_in_domain(d, hb, Tid, (rW, cW), lo, hi, main_doms, wdoms)
        if X is None:
            print(f'window{wi}: no in-domain double pair'); return
        # split trunk domain on Tid covering [X,X+1]
        ti = next(i for i, dm in enumerate(main_doms) if dm.helix_id == Tid and covers(dm, X))
        Tdom = main_doms[ti]
        Ta, Tb = split_dom(Tdom, X)  # Ta=[..X], Tb=[X+1..]
        wchain = cut_window_cycle(wdoms, wh, X)  # starts wh[X+1], ends wh[X]
        if wchain is None:
            print(f'window{wi}: cut failed'); return
        if Tdom.direction == Direction.REVERSE:
            # traversal hi->lo: Tb (high side, [X+1..hi]) first, then window, then Ta (low side)
            newseg = [Tb] + wchain + [Ta]
        else:
            newseg = [Ta] + wchain + [Tb]
        main_doms = main_doms[:ti] + newseg + main_doms[ti + 1:]
        all_x += Wx
        # connecting crossovers Tid<->wh at X and X+1
        rT, cT = hb[Tid].grid_pos
        sT = Direction.FORWARD if SR._is_forward(rT, cT) else Direction.REVERSE
        sW = Direction.FORWARD if SR._is_forward(rW, cW) else Direction.REVERSE
        for bp in (X, X + 1):
            all_x.append(Crossover(half_a=HalfCrossover(helix_id=Tid, index=bp, strand=sT),
                                   half_b=HalfCrossover(helix_id=wh, index=bp, strand=sW),
                                   process_id='auto_scaffold_seamed:section'))

    keep = [s for s in d.strands if not (s.is_scaffold and not s.is_reference)]
    strand = Strand(id='scaf_section', domains=main_doms, strand_type=StrandType.SCAFFOLD)
    helices = recompute_helices(d, main_doms)
    out_d = d.copy_with(helices=helices, strands=keep + [strand], crossovers=all_x)
    validate(d, out_d, strand)
    check_overflow(out_d, strand)
    if out:
        json.dump(json.loads(out_d.model_dump_json()), open(out, 'w'))
        print('wrote', out)


def recompute_helices(design, domains):
    """Extend each helix geometry to cover the final strand's domain bp-range (never shrink)."""
    from collections import defaultdict
    rng = defaultdict(lambda: [10 ** 9, -10 ** 9])
    for dm in domains:
        lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
        rng[dm.helix_id][0] = min(rng[dm.helix_id][0], lo)
        rng[dm.helix_id][1] = max(rng[dm.helix_id][1], hi)
    hbid = {h.id: h for h in design.helices}
    cur = design
    for hid, (lo, hi) in rng.items():
        cur = SR._extend_helix_lo(cur, hbid, hid, lo)
        cur = SR._extend_helix_hi(cur, hbid, hid, hi)
    return cur.helices


def check_overflow(outd, strand):
    hbid = {h.id: h for h in outd.helices}
    over = 0
    for dm in strand.domains:
        h = hbid[dm.helix_id]; hs = h.bp_start; he = h.bp_start + h.length_bp - 1
        if min(dm.start_bp, dm.end_bp) < hs or max(dm.start_bp, dm.end_bp) > he:
            over += 1
    print('helix overflow domains:', over)


def validate(din, outd, strand):
    D = strand.domains
    print(f'\n=== {len(D)} domains, 1 strand ===')
    xset = set()
    for x in outd.crossovers:
        xset.add((x.half_a.helix_id, x.half_a.index, x.half_b.helix_id, x.half_b.index))
        xset.add((x.half_b.helix_id, x.half_b.index, x.half_a.helix_id, x.half_a.index))
    bad = 0
    for i in range(len(D) - 1):
        a, b = D[i], D[i + 1]
        if a.helix_id == b.helix_id:
            continue  # contiguous same-helix (seam-merge) — ok if bp adjacent
        if (a.helix_id, a.end_bp, b.helix_id, b.start_bp) not in xset:
            bad += 1
            if bad <= 6: print(f'  BAD {a.helix_id[-5:]}[{a.end_bp}]->{b.helix_id[-5:]}[{b.start_bp}]')
    print('bad transitions:', bad)
    cov = SR._scaffold_coverage(din); got = defaultdict(set); cnt = defaultdict(lambda: defaultdict(int))
    for dm in D:
        for bp in range(min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1):
            got[dm.helix_id].add(bp); cnt[dm.helix_id][bp] += 1
    miss = {}; extra = {}; dbl = {}
    for hid, ivs in cov.items():
        want = set()
        for iv in ivs: want |= set(range(iv['lo'], iv['hi'] + 1))
        if want - got[hid]: miss[hid[-5:]] = len(want - got[hid])
        if got[hid] - want: extra[hid[-5:]] = len(got[hid] - want)
        dd = [bp for bp in want if cnt[hid][bp] > 1]
        if dd: dbl[hid[-5:]] = len(dd)
    print('MISSING:', miss or 'none')
    print('IN-GAP(extra):', extra or 'none')
    print('DOUBLE:', dbl or 'none')


if __name__ == '__main__':
    fx = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/teeth_unrouted.nadoc'
    build(fx, sys.argv[2] if len(sys.argv) > 2 else None)
