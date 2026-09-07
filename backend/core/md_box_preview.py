"""Read-only cell estimates for the wizard; final topology is measured at preparation."""
from functools import lru_cache
import json


@lru_cache(maxsize=4)
def _design_pdb(serialized: str) -> str:
    from backend.core.models import Design
    from backend.core.pdb_export import export_pdb
    return export_pdb(Design.model_validate_json(serialized))


def preview_box(design, request) -> dict:
    keys = ('devices', 'padding_nm', 'box_mode', 'graphene_nanopore', 'graphene_only',
            'graphene_surface_axis', 'graphene_surface_offset_nm', 'graphene_pore_diameter_nm',
            'graphene_layers', 'graphene_layer_spacing_nm', 'graphene_atomistic_clearance_nm',
            'graphene_sheet_margin_nm')
    result = dict(_calculated_box(design.model_dump_json(), json.dumps({k: getattr(request, k) for k in keys})))
    result['selected_nm'] = [v if v is not None else result['calculated_nm'][i]
                             for i, v in enumerate(request.box_size_nm or (None,) * 3)]
    return result


@lru_cache(maxsize=8)
def _calculated_box(serialized: str, settings: str) -> dict:
    from backend.core.models import Design
    from backend.api.routes_md import CreateJobRequest
    design = Design.model_validate_json(serialized)
    request = CreateJobRequest(**json.loads(settings))
    from backend.core.namd_solvate import (
        _graphene_pdb_atoms, _recenter_pdb_in_padded_box, _box_mode_atom_cap,
        resolve_padding_nm, resolve_box_mode,
    )
    control = request.graphene_only or (request.graphene_nanopore and not design.strands)
    pdb = 'END\n' if control else _design_pdb(design.model_dump_json())
    if request.graphene_nanopore:
        spec = {
            'surface_axis': request.graphene_surface_axis or ('-z' if control else '-y'),
            'surface_offset_nm': request.graphene_surface_offset_nm,
            'pore_diameter_nm': request.graphene_pore_diameter_nm,
            'layers': request.graphene_layers,
            'layer_spacing_nm': request.graphene_layer_spacing_nm,
            'atomistic_clearance_nm': 0 if control else request.graphene_atomistic_clearance_nm,
            'sheet_margin_nm': request.graphene_sheet_margin_nm,
        }
        lines = _graphene_pdb_atoms(pdb, spec)
        pdb = pdb.rstrip().removesuffix('END').rstrip() + '\n' + '\n'.join(lines) + '\nEND\n'
    cap = _box_mode_atom_cap(request.devices)
    padding, padding_note = resolve_padding_nm(pdb, request.padding_nm, max_atoms=cap)
    mode, mode_note = resolve_box_mode(pdb, padding, max_atoms=cap, free_ns=None, preferred=request.box_mode)
    pad_xyz = None
    if control:
        axis = int(max(range(3), key=lambda i: abs(spec['dir'][i])))
        pad_xyz = tuple(padding if i == axis else 0.08 for i in range(3))
    _, calculated = _recenter_pdb_in_padded_box(pdb, padding, 'bbox' if control else mode, pad_xyz)
    return {
        'calculated_nm': list(calculated), 'estimated': True,
        'note': 'Estimated from the current design; preparation recalculates automatic axes from the final atomistic seed.',
        'sizing_notes': [n for n in (padding_note, mode_note) if n],
    }
