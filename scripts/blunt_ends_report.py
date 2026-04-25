"""Blunt-end positions and occupied-interval report for a design file.

A blunt end is expected at:
  • Each *free* physical helix endpoint (axis_start or axis_end, i.e. global bp_start or
    bp_start+physLen-1), where "free" means no other helix endpoint is within TOL=0.001 nm.
  • Each strand 5′/3′ terminus that falls *strictly inside* the physical bp range of a helix
    (i.e. strictly between bp_start and phys_end_bp).

Occupied intervals are computed independently from all strand domains on each helix and are
shown alongside the blunt-end table for cross-validation.

Usage:
    python scripts/blunt_ends_report.py "Examples/cadnano/Ultimate Polymer Hinge 191016.json"
    python scripts/blunt_ends_report.py Examples/Voltron_Core_Arm_V6.sc
"""
from __future__ import annotations

import json, math, sys
from collections import defaultdict

sys.path.insert(0, '.')

RISE = 0.334   # nm per bp (BDNA_RISE_PER_BP)
TOL  = 0.001   # nm — endpoint coincidence threshold (matches blunt_ends.js)


# ── Core geometry helpers ──────────────────────────────────────────────────────

def phys_len(h) -> int:
    """Physical bp count from original helix axis geometry.

    For cadnano imports h.length_bp = full array size (e.g. 832); this returns
    the actual number of bps the helix occupies in 3-D space.
    """
    dx = h.axis_end.x - h.axis_start.x
    dy = h.axis_end.y - h.axis_start.y
    dz = h.axis_end.z - h.axis_start.z
    return max(1, round(math.sqrt(dx*dx + dy*dy + dz*dz) / RISE) + 1)


def phys_end_bp(h) -> int:
    """Global bp index of the helix's physical end (axis_end)."""
    return h.bp_start + phys_len(h) - 1


def axis_point(h, bp_global: int) -> tuple[float, float, float]:
    """Linearly interpolate a 3-D position for a global bp index on this helix."""
    pl = phys_len(h)
    t  = (bp_global - h.bp_start) / (pl - 1) if pl > 1 else 0.0
    t  = max(0.0, min(1.0, t))
    return (
        h.axis_start.x + t * (h.axis_end.x - h.axis_start.x),
        h.axis_start.y + t * (h.axis_end.y - h.axis_start.y),
        h.axis_start.z + t * (h.axis_end.z - h.axis_start.z),
    )


def dist3(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


# ── Analysis functions ─────────────────────────────────────────────────────────

def compute_blunt_ends(design):
    """Return list of expected blunt-end dicts for the design.

    Each dict has:
        helix_id : str
        label    : str           display label (h.label or array index)
        type     : 'free_start' | 'free_end' | 'interior'
        bp       : int           global bp index
        x, y, z  : float         3-D axis coordinates at this bp
    """
    helices   = design.helices
    label_map = {h.id: (h.label if h.label is not None else str(i))
                 for i, h in enumerate(helices)}

    # Build 3-D endpoint positions for the free-endpoint check
    ep = {h.id: {'start': (h.axis_start.x, h.axis_start.y, h.axis_start.z),
                 'end':   (h.axis_end.x,   h.axis_end.y,   h.axis_end.z)}
          for h in helices}

    def is_free(hid: str, which: str) -> bool:
        pos = ep[hid][which]
        for other in helices:
            if other.id == hid:
                continue
            if dist3(pos, ep[other.id]['start']) < TOL:
                return False
            if dist3(pos, ep[other.id]['end'])   < TOL:
                return False
        return True

    results: list[dict] = []

    # ── Exterior rings: free physical endpoints ────────────────────────────────
    for h in helices:
        lbl = label_map[h.id]
        pe  = phys_end_bp(h)
        for which, bp, typ in [('start', h.bp_start, 'free_start'),
                                ('end',   pe,         'free_end')]:
            if is_free(h.id, which):
                x, y, z = axis_point(h, bp)
                results.append(dict(helix_id=h.id, label=lbl, type=typ,
                                    bp=bp, x=x, y=y, z=z))

    # ── Interior rings: strand 5′/3′ termini strictly inside physical range ────
    seen = set()   # (helix_id, bp) pairs already emitted
    for h_end in results:
        seen.add((h_end['helix_id'], h_end['bp']))

    hmap = {h.id: h for h in helices}
    for strand in design.strands:
        checks = [
            (strand.domains[0].helix_id,    strand.domains[0].start_bp),
            (strand.domains[-1].helix_id,   strand.domains[-1].end_bp),
        ]
        for hid, bp in checks:
            if hid is None or bp is None:
                continue
            h = hmap.get(hid)
            if h is None:
                continue
            pe = phys_end_bp(h)
            if bp <= h.bp_start or bp >= pe:
                continue   # at or beyond physical endpoint — exterior ring handles it
            key = (hid, bp)
            if key in seen:
                continue
            seen.add(key)
            x, y, z = axis_point(h, bp)
            results.append(dict(helix_id=hid, label=label_map[hid], type='interior',
                                bp=bp, x=x, y=y, z=z))

    # ── Overhang crossovers: main-helix side of regular↔overhang transitions ──
    # A crossover between a regular domain and an overhang domain on a different
    # helix exposes a connection point on the main helix for assembly mates.
    # Both the departure (regular→OH) and return (OH→regular) positions are added.
    for strand in design.strands:
        doms = strand.domains
        for i in range(len(doms) - 1):
            d0, d1 = doms[i], doms[i + 1]
            if d0.helix_id == d1.helix_id:
                continue  # same-helix nick/extension, not a crossover

            # regular → overhang: blunt end at d0.end_bp on main helix d0
            if getattr(d0, 'overhang_id', None) is None and \
               getattr(d1, 'overhang_id', None) is not None:
                hid, bp = d0.helix_id, d0.end_bp
                if hid is not None and bp is not None:
                    h = hmap.get(hid)
                    if h is not None:
                        pe  = phys_end_bp(h)
                        key = (hid, bp)
                        if key not in seen and h.bp_start <= bp <= pe:
                            seen.add(key)
                            x, y, z = axis_point(h, bp)
                            results.append(dict(helix_id=hid, label=label_map[hid],
                                                type='overhang_xover', bp=bp,
                                                x=x, y=y, z=z))

            # overhang → regular: blunt end at d1.start_bp on main helix d1
            if getattr(d0, 'overhang_id', None) is not None and \
               getattr(d1, 'overhang_id', None) is None:
                hid, bp = d1.helix_id, d1.start_bp
                if hid is not None and bp is not None:
                    h = hmap.get(hid)
                    if h is not None:
                        pe  = phys_end_bp(h)
                        key = (hid, bp)
                        if key not in seen and h.bp_start <= bp <= pe:
                            seen.add(key)
                            x, y, z = axis_point(h, bp)
                            results.append(dict(helix_id=hid, label=label_map[hid],
                                                type='overhang_xover', bp=bp,
                                                x=x, y=y, z=z))

    return results


def compute_occupied_intervals(design) -> dict[str, list[tuple[int, int]]]:
    """Return merged occupied bp intervals per helix.

    Intervals are sorted and non-overlapping.  Each interval (lo, hi) represents
    the contiguous bp range covered by at least one strand domain.
    """
    raw: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for strand in design.strands:
        for d in strand.domains:
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            raw[d.helix_id].append((lo, hi))

    merged: dict[str, list[tuple[int, int]]] = {}
    for hid, ivs in raw.items():
        ivs.sort()
        out = [ivs[0]]
        for lo, hi in ivs[1:]:
            if lo <= out[-1][1] + 1:
                out[-1] = (out[-1][0], max(out[-1][1], hi))
            else:
                out.append((lo, hi))
        merged[hid] = out
    return merged


# ── Loading ────────────────────────────────────────────────────────────────────

def load_design(path: str):
    if path.endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        with open(path) as f:
            d, _ = import_scadnano(json.loads(f.read()))
    else:
        from backend.core.cadnano import import_cadnano
        with open(path) as f:
            d, _ = import_cadnano(json.load(f))
    from backend.core.lattice import autodetect_all_overhangs
    from backend.api.crud import _recenter_design
    d = autodetect_all_overhangs(d)
    d = _recenter_design(d)
    return d


# ── Pretty-print helpers ───────────────────────────────────────────────────────

def _lbl(h, i: int) -> str:
    return h.label if h.label is not None else str(i)


def print_blunt_ends_table(blunt_ends: list[dict], helices) -> None:
    label_map = {h.id: (_lbl(h, i)) for i, h in enumerate(helices)}
    hmap      = {h.id: h for h in helices}

    # Sort by label (numeric if possible), then by bp
    def _key(e):
        lbl = e['label']
        return (int(lbl) if lbl.isdigit() else lbl, e['bp'])
    blunt_ends = sorted(blunt_ends, key=_key)

    TYPE_W = 12
    print(f"\n{'─'*6}  BLUNT-END POSITIONS  {'─'*50}")
    print(f"{'Label':>6}  {'Type':>{TYPE_W}}  {'bp':>6}  {'x':>8}  {'y':>8}  {'z':>8}")
    print("─" * 60)
    prev_lbl = None
    for e in blunt_ends:
        lbl = e['label']
        if lbl != prev_lbl and prev_lbl is not None:
            print()
        print(f"{lbl:>6}  {e['type']:>{TYPE_W}}  {e['bp']:>6}"
              f"  {e['x']:>8.3f}  {e['y']:>8.3f}  {e['z']:>8.3f}")
        prev_lbl = lbl

    by_helix: dict[str, list] = defaultdict(list)
    for e in blunt_ends:
        by_helix[e['helix_id']].append(e)
    n_free     = sum(1 for e in blunt_ends if 'free' in e['type'])
    n_interior = sum(1 for e in blunt_ends if e['type'] == 'interior')
    print(f"\nTotal: {len(blunt_ends)}  "
          f"(free_start={sum(1 for e in blunt_ends if e['type']=='free_start')}, "
          f"free_end={sum(1 for e in blunt_ends if e['type']=='free_end')}, "
          f"interior={n_interior})")


def print_occupied_table(intervals: dict[str, list[tuple[int,int]]],
                         helices, blunt_ends: list[dict]) -> None:
    be_by_helix: dict[str, set[int]] = defaultdict(set)
    for e in blunt_ends:
        be_by_helix[e['helix_id']].add(e['bp'])

    label_map = {h.id: (_lbl(h, i)) for i, h in enumerate(helices)}
    hmap      = {h.id: h for h in helices}

    def _sort_key(hid):
        lbl = label_map[hid]
        return (int(lbl) if lbl.isdigit() else lbl,)

    print(f"\n{'─'*6}  OCCUPIED INTERVALS PER HELIX  {'─'*40}")
    print(f"{'Label':>6}  {'bp_start':>8}  {'phys_end':>8}  Intervals (and gap-boundary blunt ends)")
    print("─" * 80)
    for hid in sorted(intervals.keys(), key=_sort_key):
        h    = hmap[hid]
        lbl  = label_map[hid]
        pe   = phys_end_bp(h)
        ivs  = intervals[hid]
        be   = sorted(be_by_helix.get(hid, set()))

        # Build compact interval string; mark gap boundaries with blunt-end flags
        parts = []
        for i, (lo, hi) in enumerate(ivs):
            parts.append(f"[{lo},{hi}]")
            if i + 1 < len(ivs):
                gap_lo, gap_hi = hi + 1, ivs[i+1][0] - 1
                be_at_gap = [b for b in be if hi <= b <= ivs[i+1][0]]
                parts.append(f" ──gap({gap_lo}..{gap_hi})── {be_at_gap} ")
        ivs_str = "".join(parts)
        print(f"{lbl:>6}  {h.bp_start:>8}  {pe:>8}  {ivs_str}")


def print_mismatch_report(blunt_ends: list[dict],
                          intervals: dict[str, list[tuple[int,int]]],
                          helices) -> None:
    """Cross-check occupied-interval structure against blunt-end positions.

    Categories:
      GAP-BOUNDARY ✓  Interior blunt end at the edge of a strand-coverage gap.
                      Both the gap's pre-gap end AND post-gap start should be blunt ends
                      when those bps are strand 5′/3′ termini.
      MID-COVERAGE    Interior blunt end inside a continuously covered region.
                      A strand simply ends here while other strands still cover this bp.
                      This is valid (e.g. staple ends at a crossover inside a long helix).
      GAP-NONTERMINUS Occupied-interval boundary has NO blunt end.
                      The strand continues to/from another helix via a crossover at this bp
                      — it is NOT a strand terminus, so no ring is expected here.
    """
    hmap      = {h.id: h for h in helices}
    label_map = {h.id: (_lbl(h, i)) for i, h in enumerate(helices)}

    # Build set of occupied-interval interior boundaries per helix
    iv_boundaries: dict[str, set[int]] = defaultdict(set)
    for hid, ivs in intervals.items():
        h  = hmap[hid]
        pe = phys_end_bp(h)
        for lo, hi in ivs:
            if lo > h.bp_start:
                iv_boundaries[hid].add(lo)
            if hi < pe:
                iv_boundaries[hid].add(hi)

    be_by_helix: dict[str, set[int]] = defaultdict(set)
    for e in blunt_ends:
        be_by_helix[e['helix_id']].add(e['bp'])

    gap_boundary_ok   = 0
    mid_coverage      = 0
    gap_nonterminus   = 0

    mid_coverage_ex:  list[str] = []
    gap_nonterm_ex:   list[str] = []

    for e in blunt_ends:
        if e['type'] != 'interior':
            continue
        hid = e['helix_id']
        bp  = e['bp']
        if bp in iv_boundaries.get(hid, set()):
            gap_boundary_ok += 1
        else:
            mid_coverage += 1
            if len(mid_coverage_ex) < 5:
                mid_coverage_ex.append(
                    f"    helix {e['label']:>4}  bp {bp}  "
                    f"({e['x']:.2f},{e['y']:.2f},{e['z']:.2f})")

    for hid, bps in iv_boundaries.items():
        lbl = label_map[hid]
        for bp in sorted(bps):
            if bp not in be_by_helix.get(hid, set()):
                gap_nonterminus += 1
                if len(gap_nonterm_ex) < 5:
                    gap_nonterm_ex.append(f"    helix {lbl:>4}  bp {bp}")

    print(f"\n{'─'*6}  MISMATCH REPORT  {'─'*50}")
    print(f"  GAP-BOUNDARY ✓    {gap_boundary_ok:>4}  "
          f"Interior blunt ends at occupied-interval gap edges")
    print(f"  MID-COVERAGE      {mid_coverage:>4}  "
          f"Strand terminates inside continuously-covered region (valid)")
    if mid_coverage_ex:
        for ex in mid_coverage_ex:
            print(ex)
        if mid_coverage > len(mid_coverage_ex):
            print(f"    ... and {mid_coverage - len(mid_coverage_ex)} more")
    print(f"  GAP-NONTERMINUS   {gap_nonterminus:>4}  "
          f"Gap boundary with no blunt end (crossover entry, not strand terminus)")
    if gap_nonterm_ex:
        for ex in gap_nonterm_ex:
            print(ex)
        if gap_nonterminus > len(gap_nonterm_ex):
            print(f"    ... and {gap_nonterminus - len(gap_nonterm_ex)} more")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    path   = sys.argv[1] if len(sys.argv) > 1 else \
             'Examples/cadnano/Ultimate Polymer Hinge 191016.json'
    design = load_design(path)
    print(f"\nFile: {path}")
    print(f"Helices: {len(design.helices)}   Strands: {len(design.strands)}")

    blunt_ends = compute_blunt_ends(design)
    intervals  = compute_occupied_intervals(design)

    print_blunt_ends_table(blunt_ends, design.helices)
    print_occupied_table(intervals, design.helices, blunt_ends)
    print_mismatch_report(blunt_ends, intervals, design.helices)


if __name__ == '__main__':
    main()
