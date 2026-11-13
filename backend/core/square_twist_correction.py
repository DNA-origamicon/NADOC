"""Compose square-lattice register correction with authored twist locally.

Insertion/deletion counts are signed strain budgets, not independent annotation
layers. Cancel them only within the same duplex run and deformation interval.
This is an initial topology prescription; the relaxed angle needs FEM validation.
"""
from bisect import bisect_left

from backend.core.models import LoopSkip
from backend.core.loop_skip_calculator import (
    _active_intervals_for_helices, forbidden_loop_skip_bps,
    CELL_BP_DEFAULT, MAX_DELTA_PER_CELL,
)


def compose_square_twist_marks(design, modifications):
    """Net all contributions within each twist/bend window on affected helices.

    Outside twist scopes keep the existing placement path. Inside those helices,
    split at every operation boundary and duplex gap so cancellation/relocation
    cannot erase opposite-handed sections or move marks into another section.
    Colliding contributions count algebraically; insufficient safe sites fail.
    """
    twists = [op for op in design.deformations if op.type == 'twist' and
              (op.params.total_degrees or op.params.degrees_per_nm)]
    affected = {hid for op in twists for hid in op.affected_helix_ids}
    forbidden = forbidden_loop_skip_bps(design)
    result = dict(modifications)
    for helix in design.helices:
        hid = helix.id
        if hid not in affected or hid not in modifications:
            continue
        ops = [op for op in design.deformations if hid in op.affected_helix_ids]
        bounds = {v for op in ops for v in (op.plane_a_bp, op.plane_b_bp)}
        placed = []
        cells = {}
        for lo, hi in _active_intervals_for_helices(design, {hid}):
            lo, hi = max(lo, helix.bp_start), min(hi, helix.bp_start + helix.length_bp)
            cuts = sorted({lo, hi} | {b for b in bounds if lo < b < hi})
            for a, b in zip(cuts, cuts[1:]):
                marks = [m for m in modifications[hid] if a <= m.bp_index < b]
                net = sum(m.delta for m in marks)
                count = abs(net)
                if not count:
                    continue
                free = [bp for bp in range(a, b) if bp not in forbidden.get(hid, set())]
                if count > len(free):
                    raise ValueError(f'Square twist correction: helix {hid}, bp {a}–{b} needs '
                                     f'{count} marks but has {len(free)} safe sites')
                # Keep original positions if no cancellation/collision is needed.
                unchanged = (count == len(marks) and len({m.bp_index for m in marks}) == count)
                ideals = sorted(m.bp_index for m in marks) if unchanged else [
                    a + (i + .5) * (b-a) / count for i in range(count)]
                for ideal in ideals:
                    eligible = [bp for bp in free if cells.get((bp-helix.bp_start)//CELL_BP_DEFAULT, 0) < MAX_DELTA_PER_CELL]
                    if not eligible:
                        raise ValueError(f'Square twist correction: helix {hid}, bp {a}–{b} exceeds safe-site density')
                    index = bisect_left(eligible, ideal)
                    bp = min(eligible[max(0,index-1):index+1], key=lambda x: (abs(x-ideal), x))
                    free.remove(bp)
                    cell = (bp-helix.bp_start)//CELL_BP_DEFAULT
                    cells[cell] = cells.get(cell, 0) + 1
                    placed.append(LoopSkip(bp_index=bp, delta=1 if net > 0 else -1))
        result[hid] = sorted(placed, key=lambda m: m.bp_index)
    return result
