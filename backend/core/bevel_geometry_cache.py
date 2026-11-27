"""Bounded exact derived records for Corner/Bevel history navigation.

Store serialized values so callers own their records. This avoids repeating
frame calculation and allocating intermediate geometry on undo/redo; recipes
and authoring state still use the normal recorder and independent replay.
"""
from collections import OrderedDict
import pickle
import threading

_lock = threading.Lock()
_entries = OrderedDict()
_MAX_BYTES = 32 * 1024**2


def design_key(design):
    from backend.core.corner_projection_reuse import _simple
    from backend.core.corner_seam_projection import _projection_key
    if not _simple(design) or not any(getattr(row, 'op_kind', None) in {'corner', 'bevel'}
                                     for row in design.feature_log):
        return None
    return _projection_key(design)


def axes_key(design):
    from backend.core.corner_projection_reuse import _simple
    from backend.core.corner_seam_projection import _projection_key
    # Command replay intentionally omits recovery history. Material axes do not
    # read Corner seam ownership, so use the same exact key with or without it.
    return (_projection_key(design.model_copy(update={'feature_log': []}))
            if _simple(design) else None)


def material_key(design):
    from backend.core.corner_projection_reuse import _simple
    from backend.core.corner_seam_projection import _projection_key
    if (not _simple(design) or any(c.domain_ids or c.base_ids or c.parent_cluster_id
                                  for c in design.cluster_transforms)
            or any(op.target_ranges is not None for op in design.deformations)):
        return None
    # The admitted per-helix array path reads construction helices, whole-helix
    # poses and unscoped deformations; strand occupancy is applied afterwards.
    return _projection_key(design.model_copy(update={
        'strands': [], 'forced_ligations': [], 'feature_log': []}))


def get(key):
    with _lock:
        raw = _entries.get(key)
        if raw is not None:
            _entries.move_to_end(key)
    return pickle.loads(raw) if raw is not None else None


def put(key, value):
    raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    if len(raw) > _MAX_BYTES:
        return
    with _lock:
        _entries[key] = raw
        _entries.move_to_end(key)
        while len(_entries) > 512 or sum(map(len, _entries.values())) > _MAX_BYTES:
            _entries.popitem(last=False)


def clear():
    with _lock:
        _entries.clear()


def put_full(key, records):
    from backend.core.design_geometry import _compact_geometry_from_nucleotides
    put(key, records)
    put(('compact', key[1]), _compact_geometry_from_nucleotides(records))


def compact(design):
    identity = design_key(design)
    if identity is None:
        return None
    cached = get(('compact', identity))
    if cached is not None:
        return cached
    # Keep wire arrays throughout a certified trim instead of rebuilding Full
    # dictionaries only to transpose them. Regenerate all topology metadata.
    from backend.core.corner_projection_reuse import certified_source
    from backend.core.design_geometry import _strand_nucleotide_info
    from backend.core.models import Direction
    if not _fixed_sites(design):
        return None
    match = certified_source(design)
    source = get(('compact', match[0])) if match is not None else None
    if source is None:
        return None
    info = _strand_nucleotide_info(design)
    fields = {'sid': 'strand_id', 'stype': 'strand_type', 'is5': 'is_five_prime',
              'is3': 'is_three_prime', 'did': 'domain_index', 'ohid': 'overhang_id',
              'unpaired': 'is_unpaired'}
    result = {}
    for helix, directions in source.items():
        for direction, bucket in directions.items():
            strand_direction = Direction(direction)
            rows = [(i, info[(helix, bp, strand_direction)])
                    for i, bp in enumerate(bucket['bp'])
                    if (helix, bp, strand_direction) in info]
            if not rows:
                continue
            output = {key: [values[i] for i, _ in rows] for key, values in bucket.items()}
            for key, field in fields.items():
                output[key] = [metadata[field] for _, metadata in rows]
            result.setdefault(helix, {})[direction] = output
    put(('compact', identity), result)
    return result


def _fixed_sites(design):
    if any(c.domain_ids or c.base_ids for c in design.cluster_transforms):
        return False
    helices = {h.id: h for h in design.helices}
    if any(d.helix_id not in helices or
           min(d.start_bp, d.end_bp) < helices[d.helix_id].bp_start or
           max(d.start_bp, d.end_bp) >= helices[d.helix_id].bp_start + helices[d.helix_id].length_bp
           for s in design.strands for d in s.domains):
        return False
    return True


def slice_certified(design):
    """Reuse fixed native frames; recompute all strand/end/occupancy metadata.

    Only complete-helix placement and in-helix sites are admitted. The seam
    certificate proves all retained atomistic landmarks are unchanged as well.
    """
    from backend.core.corner_projection_reuse import certified_source
    from backend.core.design_geometry import _strand_nucleotide_info
    from backend.core.models import Direction
    if not _fixed_sites(design):
        return None
    match = certified_source(design)
    records = get(('full', match[0])) if match is not None else None
    if records is None:
        return None
    info = _strand_nucleotide_info(design)
    result = []
    for record in records:
        metadata = info.get((record['helix_id'], record['bp_index'], Direction(record['direction'])))
        if metadata is not None:
            record.update(metadata)
            result.append(record)
    return result


def slice_positions(design):
    """Filter the canonical positions DTO without rematerializing Full records."""
    from backend.core.corner_projection_reuse import certified_source
    if not _fixed_sites(design):
        return None
    match = certified_source(design)
    cached = get(('positions', match[0])) if match is not None else None
    if cached is None:
        return None
    occupied = {(d.helix_id, bp, d.direction.value) for s in design.strands for d in s.domains
                for bp in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)+1)}
    result = {}
    for helix, directions in cached[0].items():
        for direction, bucket in directions.items():
            indices = [i for i, bp in enumerate(bucket['bp']) if (helix, bp, direction) in occupied]
            if indices:
                result.setdefault(helix, {})[direction] = {
                    key: [values[i] for i in indices] for key, values in bucket.items()}
    return result


from backend.core.memory_budget import register_reclaimer
register_reclaimer('bevel_geometry', clear)
