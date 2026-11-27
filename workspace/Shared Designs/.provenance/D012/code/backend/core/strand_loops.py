"""Strand-owned insertion loops: topology, sequence offsets and authoring.

A loop consumes sequence after its anchor, before the existing next nucleotide.
It neither creates a complementary nucleotide nor changes the duplex register.
"""
from backend.core.models import Direction, StrandLoop


def loop_key(loop):
    return loop.helix_id, loop.bp_index, loop.direction


def strand_entries(design, strand):
    """Yield (helix, bp, direction, loop ordinal) in sequence order.

    Ordinal zero denotes the ordinary column; positive ordinals are unpaired.
    Legacy duplex insertions retain their pre-existing sequence consumption.
    """
    from backend.core.sequences import domain_bp_range
    marks = {(h.id, m.bp_index): m.delta for h in design.helices for m in h.loop_skips}
    loops = {loop_key(loop): loop for loop in strand.loops}
    for domain in strand.domains:
        for bp in domain_bp_range(domain):
            key = domain.helix_id, bp, domain.direction
            count = max(0, 1 + marks.get(key[:2], 0))
            for _ in range(count):
                yield (*key, 0)
            if count and key in loops:
                for ordinal in range(1, loops[key].length + 1):
                    yield (*key, ordinal)


def set_loop(design, params):
    """Set, resize, or remove a loop via the replayable user command."""
    strand = next((s for s in design.strands if s.id == params['strand_id']), None)
    if strand is None:
        raise ValueError('Selected strand is missing')
    if strand.is_reference:
        raise ValueError('Make the selected strand active before adding a loop')
    count = params['length']
    if type(count) is not int or not 0 <= count <= 512:
        raise ValueError('Loop length must be an integer from 0 to 512')
    key = params['helix_id'], params['bp_index'], Direction(params['direction'])
    entries = list(strand_entries(design, strand))
    anchors = [i for i, entry in enumerate(entries) if entry == (*key, 0)]
    if len(anchors) != 1:
        raise ValueError('Select one ordinary nucleotide, without a duplex insertion or skip')
    start = anchors[0] + 1
    existing = next((loop for loop in strand.loops if loop_key(loop) == key), None)
    old_length = existing.length if existing else 0
    if count and start + old_length >= len(entries):
        raise ValueError('A loop needs a following nucleotide; select a base before the 3′ end')
    domain = next(d for d in strand.domains if d.helix_id == key[0]
                  and d.direction == key[2] and min(d.start_bp, d.end_bp) <= key[1] <= max(d.start_bp, d.end_bp))
    if domain.overhang_id or domain.binds_overhang_id:
        raise ValueError('Select a scaffold or staple helix domain for an insertion loop')
    loops = [loop for loop in strand.loops if loop_key(loop) != key]
    if count:
        loops.append(StrandLoop(helix_id=key[0], bp_index=key[1], direction=key[2],
                                length=count, aspect_ratio=params.get('aspect_ratio', 3.0),
                                rotation_deg=params.get('rotation_deg', 0.0)))
    sequence = (strand.sequence or '').ljust(len(entries), 'N')
    inserted = sequence[start:start + min(count, old_length)].ljust(count, 'N')
    sequence = sequence[:start] + inserted + sequence[start + old_length:]
    updated = strand.model_copy(update={'loops': loops, 'sequence': sequence})
    return design.copy_with(strands=[updated if s.id == strand.id else s for s in design.strands])


def require_loop_export_support(design, operation):
    if any(s.loops for s in design.strands):
        raise ValueError(f"{operation} does not yet support strand-specific insertion loops. "
                         "Save the native NADOC document to preserve their topology and sequence.")


def loops_in_domains(loops, domains):
    return [loop for loop in loops if any(d.helix_id == loop.helix_id and d.direction == loop.direction
            and min(d.start_bp, d.end_bp) <= loop.bp_index <= max(d.start_bp, d.end_bp) for d in domains)]


def require_loop_transition(before, after, kind):
    """Refuse unsupported routing edits that would orphan or silently lose loops."""
    if not any(s.loops for s in before.strands) and not any(s.loops for s in after.strands):
        return
    old = {loop_key(loop) for s in before.strands for loop in s.loops}
    new = set()
    occupied = set()
    for strand in after.strands:
        if not strand.loops and not old:
            continue
        entries = list(strand_entries(after, strand))
        occupied.update(entry[:3] for entry in entries if entry[3] == 0)
        for loop in strand.loops:
            key = loop_key(loop)
            if key in new or key not in {entry[:3] for entry in entries if entry[3] == 0}:
                raise ValueError('Routing would orphan or duplicate a strand loop; remove it before this edit')
            index = entries.index((*key, 0))
            if index + loop.length + 1 >= len(entries):
                raise ValueError('Routing would detach a loop root; remove it before this edit')
            new.add(key)
    if kind != 'strand-loop-set' and (old - new) & occupied:
        raise ValueError('This routing operation cannot preserve strand loops; remove them before this edit')
