"""Typed connection reference candidates from an independently rebuilt prefix.

No current geometry, guessed names, ownership migration or automatic repair.
Candidate eligibility never certifies a whole command or downstream recipe.
"""

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_NODES

_CREATE = {'connection-version-create', 'connection-version-connect-direct', 'connection-version-connect-linker'}
_SELECT = {'connection-version-patch', 'connection-version-delete', 'connection-version-apply-direct',
           'connection-version-apply-linker', 'connection-version-disconnect'}


def reference_slots(params):
    from backend.api.part_proof_commands import dependencies
    from backend.api.part_repair_selection import ReferenceSlot
    if not dependencies('overhang-bulk', params).known:
        return {}
    action = params.get('action')
    if type(action) is not str:
        return {}
    if action in _CREATE:
        return {name: ReferenceSlot('overhang', 'overhangs', 'connection_endpoint')
                for name in ('overhang_a_id', 'overhang_b_id')}
    if action in _SELECT:
        return {'version_id': ReferenceSlot('connection_version', 'connection_versions', 'connection_version')}
    return {}


def reference_slot(params, path):
    return reference_slots(params).get(path[0]) if len(path) == 1 else None


def candidates(design, slot, params, request, checkpoint):
    records = getattr(design, slot.collection)
    if type(records) is not list or len(records) > MAX_OPERATION_NODES:
        raise CommandContractError('Connection selection exceeds its record allowance', code='connection_selection_limit')
    seen = set()
    for record in records:
        checkpoint()
        if record.id in seen:
            raise ReferenceResolutionError('Connection replacement identities are ambiguous', code='invalid_selection',
                references=[{'kind': slot.resource_kind, 'identity': record.id,
                             'parameter_path': request.parameter_path}])
        seen.add(record.id)
    other = params.get('overhang_b_id' if request.parameter_path == ['overhang_a_id'] else 'overhang_a_id')
    candidates, count = [], 0
    for record in records:
        checkpoint()
        if slot.family == 'connection_endpoint':
            eligible = record.id != other and not record.auxiliary_endpoint
        else:
            # Preserve the explicitly authored endpoint orientation and type.
            # Changing the pair or type requires a separate reviewed input edit.
            eligible = (record.overhang_a_id == params['overhang_a_id']
                        and record.overhang_b_id == params['overhang_b_id']
                        and ('connection_type' not in params or record.connection_type == params['connection_type']))
        if not eligible or type(record.id) is not str or not 1 <= len(record.id) <= 256:
            continue
        count += 1
        if len(candidates) < request.limit:
            label = getattr(record, 'name', None) or record.id
            candidates.append({'kind': slot.resource_kind, 'identity': record.id, 'label': label[:256]})
    return candidates, count
