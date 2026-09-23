"""Read-only backbone integrity checks shared by validation and scaffold routing.

Coordinates are global lattice indices, not bounds against the original helix
length. Reference strands are display geometry, never physical slot owners.
"""
from collections import defaultdict

from backend.core.models import Direction, StrandType


def slot(helix_id, bp, direction):
    return (helix_id, bp, getattr(direction, "value", direction))


def half_slot(half):
    return slot(half.helix_id, half.index, half.strand)


def forced_edge(fl):
    return (slot(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction),
            slot(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction))


def domain_order_errors(design):
    errors = []
    for strand in design.strands:
        if strand.is_reference:
            continue
        for dm in strand.domains:
            if ((dm.direction == Direction.FORWARD and dm.start_bp > dm.end_bp)
                    or (dm.direction == Direction.REVERSE and dm.start_bp < dm.end_bp)):
                errors.append(f"Strand {strand.id!r}: domain {dm.helix_id!r} "
                              f"{dm.start_bp}→{dm.end_bp} contradicts {dm.direction.value} traversal.")
    return errors


def occupancy_errors(design):
    """Detect intra- and inter-strand overlap using intervals, not a per-base index."""
    groups = defaultdict(list)
    skips = {h.id: {ls.bp_index for ls in h.loop_skips if ls.delta < 0} for h in design.helices}
    for si, s in enumerate(design.strands):
        if s.is_reference:
            continue
        for di, dm in enumerate(s.domains):
            groups[(dm.helix_id, dm.direction.value)].append(
                (min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp), si, di))
    errors = []
    for (hid, direction), intervals in groups.items():
        active = []
        for lo, hi, si, di in sorted(intervals):
            active = [x for x in active if x[1] >= lo]
            for _lo, end, sj, dj in active:
                bp = lo
                while bp <= min(hi, end) and bp in skips.get(hid, ()):
                    bp += 1
                if bp <= min(hi, end):
                    errors.append(f"Duplicate nucleotide occupancy at ({hid}, bp {bp}, {direction}): "
                                  f"{design.strands[sj].id!r} domain {dj} and {design.strands[si].id!r} domain {di}.")
                    if len(errors) >= 20:
                        return errors
            active.append((lo, hi, si, di))
    return errors


def junction_errors(design):
    """Check authored junction records against active strand paths.

Pending terminal-to-terminal connections remain representable. The validator's
existing nick-at-crossover check distinguishes them from realized crossovers.
Synthetic linker/overhang paths have their own explicit attachment model.
"""
    ranges = defaultdict(list)
    refs = defaultdict(list)
    transitions = set()
    terminals_3, terminals_5 = set(), set()
    for s in design.strands:
        for dm in s.domains:
            (refs if s.is_reference else ranges)[(dm.helix_id, dm.direction.value)].append(
                (min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)))
        if s.is_reference or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        terminals_5.add(slot(first.helix_id, first.start_bp, first.direction))
        terminals_3.add(slot(last.helix_id, last.end_bp, last.direction))
        for a, b in zip(s.domains, s.domains[1:]):
            transitions.add((slot(a.helix_id, a.end_bp, a.direction), slot(b.helix_id, b.start_bp, b.direction)))

    def covered(key, index=ranges):
        return any(lo <= key[1] <= hi for lo, hi in index.get((key[0], key[2]), ()))

    def continuous(a, b):
        if a[0] != b[0] or a[2] != b[2]:
            return False
        step = 1 if a[2] == "FORWARD" else -1
        return b[1] == a[1] + step and covered(a) and covered(b)

    records = set()
    errors = []
    used_slots = {}
    ids = set()
    for kind, items in (("crossover", design.crossovers), ("forced ligation", design.forced_ligations)):
        for item in items:
            a, b = ((half_slot(item.half_a), half_slot(item.half_b)) if kind == "crossover" else forced_edge(item))
            if not covered(a) and not covered(b) and covered(a, refs) and covered(b, refs):
                continue
            key = frozenset((a, b))
            if item.id in ids:
                errors.append(f"Duplicate junction ID {item.id!r}.")
            ids.add(item.id)
            if key in records:
                errors.append(f"Duplicate junction record {item.id!r}.")
            records.add(key)
            for endpoint in (a, b):
                if not covered(endpoint):
                    errors.append(f"{kind.capitalize()} {item.id!r} has no active nucleotide at {endpoint}.")
                if kind == "crossover":
                    if endpoint in used_slots and used_slots[endpoint] != key:
                        errors.append(f"Crossover endpoint {endpoint} is used by multiple junctions.")
                    used_slots[endpoint] = key
            realized = (a, b) in transitions or (kind == "crossover" and (b, a) in transitions)
            pending = a in terminals_3 and b in terminals_5
            if kind == "crossover":
                pending = pending or (b in terminals_3 and a in terminals_5)
            if not realized and not pending and not (kind == "forced ligation" and continuous(a, b)):
                errors.append(f"{kind.capitalize()} {item.id!r} does not match a backbone transition or pending termini.")
    for s in design.strands:
        if s.is_reference or s.strand_type == StrandType.LINKER:
            continue
        for a, b in zip(s.domains, s.domains[1:]):
            # Inline overhang/binder attachment is represented by its domain tags.
            if a.overhang_id or b.overhang_id or a.binds_overhang_id or b.binds_overhang_id:
                continue
            ka, kb = slot(a.helix_id, a.end_bp, a.direction), slot(b.helix_id, b.start_bp, b.direction)
            if not continuous(ka, kb) and frozenset((ka, kb)) not in records:
                errors.append(f"Strand {s.id!r} backbone transition {ka} → {kb} has no junction record.")
    return errors[:20]
