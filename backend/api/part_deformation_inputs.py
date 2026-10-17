"""Owned Bend/Twist inputs for typed feature history; no geometry builder."""

from copy import deepcopy
import json

from backend.core.models import BendParams, TwistParams, DeformationOp, DeformationLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input

FIELDS = frozenset({'type', 'plane_a_bp', 'plane_b_bp', 'params', 'targets', 'cluster_ids'})


def _reject(detail):
    raise CommandContractError(detail, code='invalid_deformation_input')


def _values(values):
    if values.get('type') not in {'bend', 'twist'}:
        _reject('Choose Bend or Twist')
    for key in ('plane_a_bp', 'plane_b_bp'):
        if type(values.get(key)) is not int or abs(values[key]) > 1_000_000:
            _reject('Deformation planes require bounded integer addresses')
    if values['plane_a_bp'] >= values['plane_b_bp']:
        _reject('The first deformation plane must precede the second')
    params = values.get('params')
    schema = BendParams if values['type'] == 'bend' else TwistParams
    if type(params) is not dict or params.keys() - schema.model_fields.keys():
        _reject('Parameters must match the selected deformation family')
    native = schema.model_validate_json(json.dumps(params, allow_nan=False), strict=True)
    if native.kind != values['type']:
        _reject('Parameters cannot change deformation family')
    ids = values.get('cluster_ids', [])
    if (type(ids) is not list or any(type(v) is not str or not 0 < len(v) <= 256 for v in ids)
            or len(ids) != len(set(ids))):
        _reject('Cluster selection requires unique bounded identities')
    return native


def normalize(previous, patch):
    validate_operation_input(patch)
    if type(patch) is not dict or patch.keys() - FIELDS:
        _reject('Deformation edits cannot replace identity or derived selection receipts')
    if patch.get('type', previous.get('type')) != previous.get('type'):
        _reject('An edit cannot change deformation family')
    _values({**previous, **patch})
    # Keep patch presence: resubmitting derived selection would change native
    # group-edit semantics. Prefix-aware overlay editing resolves changed groups.
    return deepcopy(patch)


def normalize_creation(params):
    validate_operation_input(params)
    if type(params) is not dict or params.keys() - FIELDS:
        _reject('Creation accepts authored inputs only')
    _values(params)
    return deepcopy(params)


def creation_entry(params, prefix, identity):
    from backend.api.part_deformation_preview import creation_scope, _operation
    native = _values(params)
    a, b = params['plane_a_bp'], params['plane_b_bp']
    groups, targets = params.get('cluster_ids', []), params.get('targets')
    ids, ranges = creation_scope(prefix, targets, groups, planes=(a, b))
    op = DeformationOp(id=identity, type=params['type'], plane_a_bp=a, plane_b_bp=b,
        params=native, cluster_ids=groups, targets=deepcopy(targets),
        affected_helix_ids=ids, target_ranges=ranges)
    _operation(op, prefix)
    return DeformationLogEntry(id=identity, deformation_id=identity, op_snapshot=op, proof_version=1)
