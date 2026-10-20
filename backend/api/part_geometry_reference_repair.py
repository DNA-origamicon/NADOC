"""Authored source slots for the existing geometry feature repair panel."""

SOURCES = {
    'sweep': ('source_helix_id', 'Source helix', 'helix', 'helices'),
    'extrude-continuation': ('source_frame_id', 'Source frame', 'lattice_frame', 'lattice_frames'),
    'extrude-frame': ('source_frame_id', 'Source frame', 'lattice_frame', 'lattice_frames'),
    'extrude-deformed-continuation': ('ref_helix_id', 'Reference helix', 'helix', 'helices'),
    'overhang-extrude': ('helix_id', 'Anchor helix', 'helix', 'helices'),
}


def fields(kind, params):
    from backend.api.part_geometry_inputs import normalize
    if kind not in SOURCES:
        return []
    normalize(kind, params, {})
    name, label, _, _ = SOURCES[kind]
    return [(name, label)] if type(params.get(name)) is str and params[name] else []


def reference(kind, params, path):
    if kind not in SOURCES or path != [SOURCES[kind][0]] or not fields(kind, params):
        return None
    _, _, resource, collection = SOURCES[kind]
    return resource, collection, 'geometry_source'


def eligible(kind, params, record, design):
    # This is typed source discovery only. Native execution checks all endpoint,
    # occupancy, attachment and geometry rules during full repair evaluation.
    if kind in {'extrude-frame', 'extrude-continuation'}:
        return record.plane == params.get('plane', 'XY')
    if kind == 'sweep':
        if record.grid_pos is None or list(record.grid_pos) not in params['cells']:
            return False
        frame = next((frame for frame in design.lattice_frames if frame.id == record.lattice_frame_id), None)
        return frame is None or frame.plane == params.get('plane', 'XY')
    return True


def bind_entry(entry, prefix, targets):
    if entry.id not in targets or entry.feature_type != 'snapshot' or entry.op_kind not in SOURCES:
        return entry
    from backend.api.part_geometry_inputs import normalize, bind_prefix
    params = normalize(entry.op_kind, entry.params, {})
    params = bind_prefix(entry.op_kind, params, prefix)
    return entry.model_copy(update={'params': params})
