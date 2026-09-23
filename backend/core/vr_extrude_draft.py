"""Transport validation only; a painted footprint is not an authored lattice frame."""
MAX_PAINTED_CELLS = 16_641  # Native ExtrudeLatticeDraft capacity.
MAX_CELL_COORDINATE = 100_000
MAX_VR_EVENT_BYTES = 512 * 1024


def validate_painted_footprint(value):
    if not isinstance(value, dict) or set(value) != {'lattice_type', 'cells'}:
        raise ValueError('invalid painted footprint')
    if value['lattice_type'] not in ('HONEYCOMB', 'SQUARE'):
        raise ValueError('invalid painted lattice')
    cells = value['cells']
    if not isinstance(cells, list) or len(cells) > MAX_PAINTED_CELLS:
        raise ValueError('invalid painted cell count')
    seen = set()
    result = []
    for cell in cells:
        if (not isinstance(cell, list) or len(cell) != 2
                or any(type(v) is not int or abs(v) > MAX_CELL_COORDINATE for v in cell)):
            raise ValueError('invalid painted cell')
        key = tuple(cell)
        if key in seen:
            raise ValueError('duplicate painted cell')
        seen.add(key)
        result.append(list(cell))
    return {'lattice_type': value['lattice_type'], 'cells': result}


def action_config_sequence(event, current_sequence):
    """Legacy actions are unbound (zero); never infer their current paint state."""
    sequence = event.get('tool_action_config_sequence', 0)
    if type(sequence) is not int or not 0 <= sequence <= current_sequence:
        raise ValueError('invalid action-time configuration sequence')
    return sequence
