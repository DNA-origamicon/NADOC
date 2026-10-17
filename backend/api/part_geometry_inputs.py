"""Closed native snapshot catalog for the shared immutable geometry lifecycle.

Family validation stays in the existing tool modules. This adapter selects those
contracts; it neither builds geometry nor grants publication authority.
"""

from backend.api import part_extrusion_edit_inputs as extrusion
from backend.core.part_command_errors import CommandContractError

KINDS = extrusion.KINDS | {'sweep'}


def normalize(kind, previous, patch):
    if kind == 'sweep':
        from backend.api.part_sweep_preview import normalize as sweep_normalize
        return sweep_normalize(previous, patch)
    return extrusion.normalize(kind, previous, patch)


def normalize_creation(kind, params, *, identity):
    if kind != 'sweep':
        return extrusion.normalize_creation(kind, params, identity=identity)
    from backend.api.part_sweep_preview import EDIT_FIELDS
    from backend.core.sweep import SweepRequest
    from backend.core.part_operation_input import validate_operation_input
    validate_operation_input(params)
    if type(params) is not dict or params.keys() - EDIT_FIELDS:
        raise CommandContractError('Sweep creation accepts authored inputs only', code='invalid_sweep_input')
    values = SweepRequest.model_validate({**params, 'sweep_id': identity}).model_dump(mode='json')
    values = {key: value for key, value in values.items() if key in EDIT_FIELDS}
    values.update(params)
    values.update(sweep_id=identity, _proof_version=1)
    return normalize(kind, values, {})


def bind_prefix(kind, params, prefix):
    if kind == 'sweep':
        from backend.api.part_sweep_preview import _source
        values = normalize(kind, params, {})
        _source(prefix, values)
        return values
    return extrusion.bind_prefix(kind, params, prefix)
