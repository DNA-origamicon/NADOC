"""Exact-input migration to branch-stable native creator selections.

Only authored prefix definitions identify a creator. No geometry/recovery reads,
producer execution, guessed ownership, or mutation of the source recipe.
"""

from copy import deepcopy

from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_connection_owner_query import owner_ids
from backend.core.part_history_proof import digest
from backend.core.part_operation_input import validate_operation_input

_CONTRACTS = {
    'connection-version-apply-direct': ('direct_application_version', 1, 2),
    'connection-version-connect-direct': ('direct_composition_version', 1, 2),
    'connection-version-apply-linker': ('connection_application_version', 3, 4),
    'connection-version-connect-linker': ('connection_composition_version', 3, 4),
}


def _fail(message, code='unsupported_connection_owner_upgrade'):
    raise CommandContractError(message, code=code)


def contract(kind, params):
    validate_operation_input(params)
    if (kind != 'overhang-bulk' or type(params) is not dict
            or '_generated_scope' in params or '_connection_organization' in params):
        _fail('Only unscoped native literal-owner recipes can adopt creator selection')
    action = params.get('action')
    spec = _CONTRACTS.get(action) if type(action) is str else None
    if (spec is None or type(params.get(spec[0])) is not int or params[spec[0]] != spec[1]
            or type(params.get('conflict_duplex_ids')) is not list or not params['conflict_duplex_ids']
            or 'direct_owner_seeds' in params):
        _fail('Select an existing native literal-owner recipe with Duplex dependencies')
    return spec


def definition_sha256(kind, params):
    validate_operation_input(params)
    return digest({'kind': kind, 'params': params})


def upgrade_action(kind, params, feature_id):
    contract(kind, params)
    return {'action': 'upgrade_connection_owners', 'feature_id': feature_id, 'child_id': None,
            'expected_definition_sha256': definition_sha256(kind, params)}


def upgrade(source, entry, action, *, dependencies, check_expectations=True, copy_value=deepcopy):
    if type(entry) is not SnapshotLogEntry:
        _fail('Connection owner migration requires its original snapshot definition')
    kind, previous = entry.op_kind, entry.params
    marker, old_version, new_version = contract(kind, previous)
    if not check_expectations:
        # This source-free transition cannot introduce imported byte sources.
        # Discovery avoids hashing/scanning producer inputs under the source lock.
        return copy_value(previous), None
    if action.expected_definition_sha256 != definition_sha256(kind, previous):
        _fail('Connection definition changed after migration was proposed', 'repair_conflict')
    if len(source.feature_log) > 2000:
        _fail('Connection producer history exceeds the repair allowance', 'connection_owner_repair_limit')
    selected = set(previous['conflict_duplex_ids'])
    producers = {}
    for producer in source.feature_log:
        if producer.id == entry.id:
            break
        values = getattr(producer, 'params', None)
        if (type(producer) is not SnapshotLogEntry or producer.op_kind != 'overhang-bulk'
                or type(values) is not dict or values.get('action') not in
                ('connection-version-apply-direct', 'connection-version-connect-direct')):
            continue
        if not dependencies('overhang-bulk', values).known:
            continue
        duplex, binding = owner_ids(values['history_seed'])
        if duplex not in selected:
            continue
        if duplex in producers:
            _fail('Creator identity has multiple preceding producers', 'ambiguous_connection_creator')
        producers[duplex] = values['history_seed'], binding
    if not producers:
        _fail('No matching native creator precedes this connection feature')
    converted = [producers[identity] for identity in previous['conflict_duplex_ids'] if identity in producers]
    bindings = {binding for _, binding in converted}
    updated = {**copy_value(previous), marker: new_version,
        'direct_owner_seeds': [seed for seed, _ in converted],
        'conflict_duplex_ids': [identity for identity in previous['conflict_duplex_ids'] if identity not in producers],
        'conflict_binding_ids': [identity for identity in previous['conflict_binding_ids'] if identity not in bindings]}
    return updated, {'feature_id': entry.id, 'child_id': None, 'kind': kind,
        'family': 'connection_owner_selection', 'from_version': old_version, 'to_version': new_version,
        'before_definition_sha256': action.expected_definition_sha256,
        'after_definition_sha256': definition_sha256(kind, updated), 'changed': True,
        'direct_owner_seeds': list(updated['direct_owner_seeds'])}
