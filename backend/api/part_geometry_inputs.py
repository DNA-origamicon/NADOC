"""Closed native snapshot catalog for the shared immutable geometry lifecycle.

Family validation stays in the existing tool modules. This adapter selects those
contracts; it neither builds geometry nor grants publication authority.
"""

from backend.api import part_extrusion_edit_inputs as extrusion
from backend.core.part_command_errors import CommandContractError

KINDS = extrusion.KINDS | {'sweep', 'deformation'}


def normalize(kind, previous, patch):
    if kind == 'deformation':
        from backend.api.part_deformation_inputs import normalize as deformation_normalize
        return deformation_normalize(previous, patch)
    if kind == 'sweep':
        from backend.api.part_sweep_preview import normalize as sweep_normalize
        return sweep_normalize(previous, patch)
    return extrusion.normalize(kind, previous, patch)


def normalize_creation(kind, params, *, identity):
    if kind == 'deformation':
        from backend.api.part_deformation_inputs import normalize_creation as deformation_creation
        return deformation_creation(params)
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


def selected(entry, kind, feature_id):
    """Typed target binding shared by transport and native evaluation."""
    from backend.core.models import SnapshotLogEntry, DeformationLogEntry
    from backend.core.part_overlay_commands import command_input
    if entry.id != feature_id or kind not in KINDS:
        raise CommandContractError('Geometry feature changed', code='source_changed')
    if kind == 'deformation':
        if (type(entry) is not DeformationLogEntry or type(entry.proof_version) is not int
                or entry.proof_version != 1 or entry.op_snapshot is None
                or entry.deformation_id != entry.op_snapshot.id or entry.op_snapshot.type not in {'bend', 'twist'}):
            raise CommandContractError('Select a typed native Bend/Twist feature', code='source_changed')
        return command_input(entry)[1]
    if (type(entry) is not SnapshotLogEntry or entry.op_kind != kind
            or type(entry.params.get('_proof_version')) is not int or entry.params['_proof_version'] != 1
            or {'_generated_scope', '_generator'} & entry.params.keys()):
        raise CommandContractError('Geometry snapshot changed', code='source_changed')
    return entry.params


def bounded_executor(executor):
    """Retain native preview span admission before allocating deformation frames."""
    def run(kind, design, params):
        if kind == 'deformation':
            from backend.api.part_deformation_preview import _operation
            from backend.core.models import DeformationOp
            op = DeformationOp.model_validate({k: v for k, v in params.items() if k != '_proof_version'})
            _operation(op, design)
        return executor(kind, design, params)
    return run
