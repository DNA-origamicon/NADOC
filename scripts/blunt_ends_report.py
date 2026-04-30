"""Domain-end positions report for a design file.

A domain end is a bp index on a (helix, direction) pair that has exactly one
covered neighbor — i.e. the strand continues on one side but terminates (or
crosses to another helix) on the other side.

Detection rules:
  • Build covMap[(helix_id, direction)] = Set[bp] from all strand domains.
  • Build strandCovMap[(strand_id, helix_id, direction)] = Set[bp] for overhang domains.
  • Build scaffoldCovMap[helix_id] = Set[bp] from scaffold strands (all directions merged).
  • For each domain endpoint (lo = min(start_bp, end_bp), hi = max(start_bp, end_bp)):
      hasPlus  = (bp+1) in covMap[(helix_id, direction)]
      hasMinus = (bp-1) in covMap[(helix_id, direction)]
      isDomainEnd = hasPlus XOR hasMinus
      openSide = +1 if !hasPlus, else -1
    Overhang domains use strandCovMap so adjacent unrelated staples do not hide
    terminal overhang labels in dense imported designs.
  • Staple suppression: a staple domain end is suppressed when the open side has
    scaffold coverage on the same helix: scaffoldCovMap[helix_id].has(bp + openSide).
  • Deduplication key = (helix_id, disk_bp) where disk_bp = bp + openSide.
    If two records share the same key, the one with overhang_id wins over the one without.

The disk (blunt-end ring) is placed at axis_point(h, disk_bp), one RISE step beyond
the last real base and into the gap.

Usage:
    python scripts/blunt_ends_report.py workspace/OHtest2.nadoc
    python scripts/blunt_ends_report.py "Examples/cadnano/Ultimate Polymer Hinge 191016.json"
    python scripts/blunt_ends_report.py Examples/Voltron_Core_Arm_V6.sc
"""
from __future__ import annotations

import json, math, sys
from collections import defaultdict

sys.path.insert(0, '.')

RISE = 0.334   # nm per bp (BDNA_RISE_PER_BP)
TOL  = 0.001   # nm — endpoint coincidence threshold (kept for potential future use)


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


def axis_point(h, bp_global: int, clamp: bool = True) -> tuple[float, float, float]:
    """Linearly interpolate (or extrapolate) a 3-D position for a global bp index.

    Pass clamp=False to allow extrapolation beyond the helix axis endpoints,
    which is required for disk positions 1 bp outside the domain end.
    """
    pl = phys_len(h)
    t  = (bp_global - h.bp_start) / (pl - 1) if pl > 1 else 0.0
    if clamp:
        t = max(0.0, min(1.0, t))
    return (
        h.axis_start.x + t * (h.axis_end.x - h.axis_start.x),
        h.axis_start.y + t * (h.axis_end.y - h.axis_start.y),
        h.axis_start.z + t * (h.axis_end.z - h.axis_start.z),
    )


def dist3(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


# ── Analysis function ──────────────────────────────────────────────────────────

def compute_domain_ends(design) -> list[dict]:
    """Return one domain-end dict per unique (helix_id, disk_bp).

    Each dict contains:
        helix_id   : str
        label      : str    display label (h.label or array index)
        bp         : int    last real base (domain end)
        open_side  : int    +1 or -1 — direction of the gap
        disk_bp    : int    bp + open_side — where the disk/ring is placed
        x, y, z    : float  disk 3-D position (axis_point unclamped)
        end_x/y/z  : float  affiliated bead position (axis_point clamped)
        overhang_id: str|None
        strand_type: str    'scaffold' or 'staple'
    """
    helices  = design.helices
    hmap     = {h.id: h for h in helices}
    label_map = {h.id: (h.label if h.label is not None else str(i))
                 for i, h in enumerate(helices)}
    scaffold_dir_by_helix: dict[str, str] = {}
    for strand in design.strands:
        st = strand.strand_type.value if hasattr(strand.strand_type, 'value') \
             else str(strand.strand_type)
        if st != 'scaffold':
            continue
        for d in strand.domains:
            if d.helix_id not in scaffold_dir_by_helix:
                scaffold_dir_by_helix[d.helix_id] = (
                    d.direction.value if hasattr(d.direction, 'value') else str(d.direction)
                )

    # ── Coverage maps ──────────────────────────────────────────────────────────
    # cov: (helix_id, direction_str) -> Set[bp]
    cov: dict[tuple[str, str], set[int]] = {}
    # strand_cov: (strand_id, helix_id, direction_str) -> Set[bp]
    # Used for overhang domains so unrelated neighboring domains do not hide a
    # real terminal overhang label in dense imported caDNAno designs.
    strand_cov: dict[tuple[str, str, str], set[int]] = {}
    # scaf_cov: helix_id -> Set[bp]  (scaffold only, direction-agnostic)
    scaf_cov: dict[str, set[int]] = {}

    for strand in design.strands:
        st = strand.strand_type.value if hasattr(strand.strand_type, 'value') \
             else str(strand.strand_type)
        for d in strand.domains:
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            dir_str = d.direction.value if hasattr(d.direction, 'value') \
                      else str(d.direction)
            key = (d.helix_id, dir_str)
            if key not in cov:
                cov[key] = set()
            cov[key].update(range(lo, hi + 1))
            skey = (strand.id, d.helix_id, dir_str)
            if skey not in strand_cov:
                strand_cov[skey] = set()
            strand_cov[skey].update(range(lo, hi + 1))
            if st == 'scaffold':
                if d.helix_id not in scaf_cov:
                    scaf_cov[d.helix_id] = set()
                scaf_cov[d.helix_id].update(range(lo, hi + 1))

    # ── Domain end detection ───────────────────────────────────────────────────
    # results_map: (helix_id, disk_bp) -> dict  (first writer wins; overhang_id upgrades)
    results_map: dict[tuple[str, int], dict] = {}

    for strand in design.strands:
        st = strand.strand_type.value if hasattr(strand.strand_type, 'value') \
             else str(strand.strand_type)
        for d in strand.domains:
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            dir_str = d.direction.value if hasattr(d.direction, 'value') \
                      else str(d.direction)
            h        = hmap.get(d.helix_id)
            if h is None:
                continue
            ovhg_id = getattr(d, 'overhang_id', None)
            cov_set = (
                strand_cov.get((strand.id, d.helix_id, dir_str), set())
                if ovhg_id else cov.get((d.helix_id, dir_str), set())
            )

            for bp in (lo, hi):
                has_plus  = (bp + 1) in cov_set
                has_minus = (bp - 1) in cov_set

                if has_plus == has_minus:
                    continue  # both covered (nick) or neither — not a domain end

                open_side = 1 if not has_plus else -1
                disk_bp   = bp + open_side

                # Staple suppression: skip if scaffold is on the open side
                if st == 'staple':
                    if disk_bp in scaf_cov.get(d.helix_id, set()):
                        continue

                map_key  = (d.helix_id, disk_bp)
                existing = results_map.get(map_key)

                if existing is not None:
                    # Upgrade overhang_id if this record has one and existing doesn't
                    if ovhg_id and not existing['overhang_id']:
                        existing['overhang_id'] = ovhg_id
                    continue

                dx, dy, dz = axis_point(h, disk_bp, clamp=False)
                ex, ey, ez = axis_point(h, bp,      clamp=True)

                results_map[map_key] = dict(
                    helix_id   = d.helix_id,
                    label      = label_map[d.helix_id],
                    bp         = bp,
                    open_side  = open_side,
                    disk_bp    = disk_bp,
                    direction  = dir_str,
                    scaffold_dir = scaffold_dir_by_helix.get(d.helix_id, 'FORWARD'),
                    x=dx, y=dy, z=dz,
                    end_x=ex, end_y=ey, end_z=ez,
                    overhang_id = ovhg_id,
                    strand_type = st,
                )

    return list(results_map.values())


# ── Loading ────────────────────────────────────────────────────────────────────

def load_design(path: str):
    if path.endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        with open(path) as f:
            d, _ = import_scadnano(json.loads(f.read()))
    elif path.endswith('.nadoc'):
        from backend.core.models import Design
        import pathlib
        d = Design.model_validate_json(pathlib.Path(path).read_text())
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


def print_domain_ends_table(domain_ends: list[dict], helices) -> None:
    def _key(e):
        lbl = e['label']
        return (int(lbl) if lbl.isdigit() else lbl, e['disk_bp'])
    domain_ends = sorted(domain_ends, key=_key)

    print(f"\n{'─'*6}  DOMAIN END POSITIONS  {'─'*50}")
    print(f"{'Label':>6}  {'type':>8}  {'bp':>5}  {'side':>5}  {'disk_bp':>7}  "
          f"{'x':>8}  {'y':>8}  {'z':>8}  {'ovhg_id'}")
    print("─" * 80)
    prev_lbl = None
    for e in domain_ends:
        lbl = e['label']
        if lbl != prev_lbl and prev_lbl is not None:
            print()
        side_str = f"+{e['open_side']}" if e['open_side'] > 0 else str(e['open_side'])
        ovhg = e['overhang_id'] or ''
        print(f"{lbl:>6}  {e['strand_type']:>8}  {e['bp']:>5}  {side_str:>5}  "
              f"{e['disk_bp']:>7}  {e['x']:>8.3f}  {e['y']:>8.3f}  {e['z']:>8.3f}  {ovhg}")
        prev_lbl = lbl

    scaf_count = sum(1 for e in domain_ends if e['strand_type'] == 'scaffold')
    stpl_count = sum(1 for e in domain_ends if e['strand_type'] == 'staple')
    ovhg_count = sum(1 for e in domain_ends if e['overhang_id'])
    print(f"\nTotal: {len(domain_ends)}  "
          f"(scaffold={scaf_count}, staple={stpl_count}, with_overhang={ovhg_count})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    path   = sys.argv[1] if len(sys.argv) > 1 else 'workspace/OHtest2.nadoc'
    design = load_design(path)
    print(f"\nFile: {path}")
    print(f"Helices: {len(design.helices)}   Strands: {len(design.strands)}")

    domain_ends = compute_domain_ends(design)
    print_domain_ends_table(domain_ends, design.helices)


if __name__ == '__main__':
    main()
