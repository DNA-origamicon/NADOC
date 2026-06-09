"""Empirical probe for the section-router single-strand build.

Decompose teeth into trunk (continuous helices) + windows (segmented sections),
route each sub-bundle in isolation with the EXISTING seamed router, and report
strand count / coverage / extension so we can decide the gap-suppression approach.
"""
import json, sys
from collections import defaultdict
from backend.core.models import Design, Domain, Strand, StrandType, Direction
from backend.core import seamed_router as SR


def sub_seed(design, sections):
    """Clean per-helix scaffold seed sub-design over `sections` = {helix_id:(lo,hi)}."""
    hb = {h.id: h for h in design.helices}
    helices = [h for h in design.helices if h.id in sections]
    strands = []
    for hid, (lo, hi) in sections.items():
        r, c = hb[hid].grid_pos
        if SR._is_forward(r, c):
            dom = Domain(helix_id=hid, start_bp=lo, end_bp=hi, direction=Direction.FORWARD)
        else:
            dom = Domain(helix_id=hid, start_bp=hi, end_bp=lo, direction=Direction.REVERSE)
        strands.append(Strand(id=f"seed_{hid}", domains=[dom], strand_type=StrandType.SCAFFOLD))
    return design.copy_with(helices=helices, strands=strands, crossovers=[])


def decompose(design):
    cov = SR._scaffold_coverage(design)
    continuous = {h: cov[h][0] for h in cov if len(cov[h]) == 1}
    # segmented sections grouped into windows by bp-overlap
    seg_secs = []  # (helix_id, lo, hi)
    for h in cov:
        if len(cov[h]) > 1:
            for iv in cov[h]:
                seg_secs.append((h, iv["lo"], iv["hi"]))
    seg_secs.sort(key=lambda t: (t[1], t[2], t[0]))
    windows = []  # list of {helix_id:(lo,hi)}
    win_span = []  # (lo,hi) running
    for hid, lo, hi in seg_secs:
        placed = False
        for wi, (wlo, whi) in enumerate(win_span):
            if lo <= whi and hi >= wlo:  # overlap
                windows[wi][hid] = (lo, hi)
                win_span[wi] = (min(wlo, lo), max(whi, hi))
                placed = True
                break
        if not placed:
            windows.append({hid: (lo, hi)})
            win_span.append((lo, hi))
    return continuous, windows


def cover_report(seed_sections, routed):
    """Report coverage of routed scaffold vs the seed section windows."""
    scaf = [s for s in routed.strands if s.is_scaffold and not s.is_reference]
    got = defaultdict(set)
    for s in scaf:
        for dm in s.domains:
            for bp in range(min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1):
                got[dm.helix_id].add(bp)
    miss = {}; extra = {}
    for hid, (lo, hi) in seed_sections.items():
        want = set(range(lo, hi + 1))
        m = want - got[hid]; e = got[hid] - want
        if m: miss[hid[-6:]] = (min(m), max(m), len(m))
        if e: extra[hid[-6:]] = (min(e), max(e), len(e))
    return len(scaf), miss, extra


def main():
    d = Design(**json.load(open('tests/fixtures/teeth_unrouted.nadoc')))
    cont, windows = decompose(d)
    print(f"continuous helices: {len(cont)}  windows: {len(windows)}")
    for wi, w in enumerate(windows):
        spans = sorted((lo, hi) for lo, hi in w.values())
        print(f"  window {wi}: {len(w)} helices  span {spans[0][0]}..{max(h for _,h in w.values())}")

    # --- route the trunk (continuous) sub-bundle ---
    trunk_sec = {h: (iv['lo'], iv['hi']) for h, iv in cont.items()}
    seed = sub_seed(d, trunk_sec)
    routed, res = SR.auto_scaffold_seamed(seed)
    n, miss, extra = cover_report(trunk_sec, routed)
    print(f"\nTRUNK: strands={n}  warnings={len(res.warnings)}")
    print(f"  MISSING: {miss or 'none'}")
    print(f"  EXTENDED(into-out-of-section): {extra or 'none'}")
    for w in res.warnings[:6]: print('   !', w)

    # --- route window 0 sub-bundle ---
    w0 = windows[0]
    seed0 = sub_seed(d, w0)
    routed0, res0 = SR.auto_scaffold_seamed(seed0)
    n0, miss0, extra0 = cover_report(w0, routed0)
    print(f"\nWINDOW0 (span {min(l for l,_ in w0.values())}..{max(h for _,h in w0.values())}): strands={n0}  warnings={len(res0.warnings)}")
    print(f"  MISSING: {miss0 or 'none'}")
    print(f"  EXTENDED(into-gap): {extra0 or 'none'}")
    for w in res0.warnings[:8]: print('   !', w)


if __name__ == '__main__':
    main()
