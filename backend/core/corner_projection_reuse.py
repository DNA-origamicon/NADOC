"""Certified Full landmarks for deletion-only Bevels away from fitted seams.

The ordinary atomistic builder remains the oracle. Reuse requires unchanged
placement inputs, contiguous slices of the same strands, and no removed atom to enter
any source optimizer query or reciprocal-clearance neighbourhood. Unsupported
topologies or incomplete traces take the ordinary calculation path.
"""
from collections import OrderedDict
from copy import deepcopy
import threading
import pickle

import numpy as np

_lock = threading.Lock()
_entries = OrderedDict()
_MAX_BYTES = 16 * 1024**2


def clear_reuse_cache():
    with _lock:
        _entries.clear()


def _simple(design):
    if any(getattr(design, field) for field in ('crossovers', 'overhangs', 'extensions',
            'flexible_connections', 'flexible_segment_marks', 'nanoparticles', 'nanoparticle_conjugations',
            'protein_assets', 'protein_attachments', 'photoproduct_junctions', 'nucleotide_transforms',
            'atomistic_reference')):
        return False
    return not any(h.loop_skips for h in design.helices) and not any(
        d.overhang_id or d.binds_overhang_id for s in design.strands for d in s.domains)


def remember_reuse(design, model, projection, trace):
    from backend.core.corner_seam_projection import _projection_key
    from backend.core.corner_seam_placement import corner_insert_links
    from backend.core.memory_sizes import retained_bytes
    if (not _simple(design) or not trace['complete'] or not trace['fits'] or
            len(corner_insert_links(design)) != len(design.forced_ligations)):
        return
    points = {}
    for atom in model.atoms:
        if atom.crossover_id:
            continue
        site = atom.helix_id, atom.bp_index, atom.direction
        points.setdefault(site, []).append((atom.x, atom.y, atom.z))
    keys = tuple(points)
    bounds = np.array([(np.min(points[key], axis=0), np.max(points[key], axis=0)) for key in keys])
    # The derived straight-view Design intentionally has no placement owners;
    # it is not an authored document to validate/save/reopen. Private in-memory
    # transport preserves that existing read-only view, as the preview worker does.
    raw = pickle.dumps(design, protocol=pickle.HIGHEST_PROTOCOL)
    boxes = np.asarray(trace['boxes'])
    protected = {(model.atoms[i].helix_id, model.atoms[i].bp_index, model.atoms[i].direction)
                 for i in trace['protected'] if not model.atoms[i].crossover_id}
    charge = (len(raw) + bounds.nbytes + boxes.nbytes + retained_bytes(keys)
              + retained_bytes(tuple(protected)) + retained_bytes(projection))
    if charge > _MAX_BYTES:
        return
    with _lock:
        key = _projection_key(design)
        _entries[key] = (raw, keys, bounds, boxes, protected, deepcopy(projection), charge)
        _entries.move_to_end(key)
        while len(_entries) > 8 or sum(row[-1] for row in _entries.values()) > _MAX_BYTES:
            _entries.popitem(last=False)


def reuse_projection(design):
    match = certified_source(design)
    return deepcopy(match[1]) if match is not None else None


def certified_source(design):
    """Return source geometry identity and landmarks after the deletion proof."""
    from backend.core.corner_seam_projection import _projection_key
    if not _simple(design) or not design.feature_log:
        return None
    entry = design.feature_log[-1]
    if getattr(entry, 'op_kind', None) != 'bevel':
        return None
    target_key = _projection_key(design)
    occupied = {(d.helix_id, bp, d.direction.value) for s in design.strands for d in s.domains
                for bp in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)+1)}
    with _lock:
        candidates = list(reversed(_entries.values()))
    for raw, keys, bounds, boxes, protected, projection, _ in candidates:
        if not protected <= occupied:
            continue
        removed = bounds[[key not in occupied for key in keys]]
        if not len(removed):
            continue
        if any(np.any(np.all((removed[:, 1] >= box[0]) & (removed[:, 0] <= box[1]), axis=1))
               for box in boxes):
            continue
        source = pickle.loads(raw)
        if (source.forced_ligations != design.forced_ligations or
                [s.id for s in source.strands] != [s.id for s in design.strands]):
            continue
        # The command has already performed plane classification and recording.
        # Prove the resulting graph is a deletion, rather than evaluating the
        # plane a second time (especially in the derived straight view).
        if _projection_key(source.model_copy(update={'strands': design.strands})) != target_key:
            continue
        if _strand_slices(source, design):
            return _projection_key(source), projection
    return None


def _strand_slices(source, design):
    from backend.core.atomistic import _atomistic_domain_bp_range, _build_sequence_map
    old_sequence, new_sequence = _build_sequence_map(source), _build_sequence_map(design)
    for old, new in zip(source.strands, design.strands):
        excluded = {'domains', 'sequence', 'routing_seed', 'name'}
        if old.model_dump(exclude=excluded) != new.model_dump(exclude=excluded):
            return False
        def walk(strand):
            return [(d.helix_id, bp, d.direction.value) for d in strand.domains
                    for bp in _atomistic_domain_bp_range(d, strand)]
        before, after = walk(old), walk(new)
        if not after or len(set(before)) != len(before) or after[0] not in before:
            return False
        offset = before.index(after[0])
        if before[offset:offset+len(after)] != after:
            return False
        if any(old_sequence.get(site, 'N') != new_sequence.get(site, 'N') for site in after):
            return False
    return True


from backend.core.memory_budget import register_reclaimer
register_reclaimer('corner_projection_reuse', clear_reuse_cache)
