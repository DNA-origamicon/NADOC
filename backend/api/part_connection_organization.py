"""Closed organization context for native connection recipes; no live rollout."""

from contextvars import ContextVar

from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input

KEY = '_connection_organization'
_trace = ContextVar('connection_organization_trace', default=None)
_VERSIONS = {
    'connection-version-apply-direct': ('direct_application_version', 2),
    'connection-version-connect-direct': ('direct_composition_version', 2),
    'connection-version-apply-linker': ('connection_application_version', 4),
    'connection-version-connect-linker': ('connection_composition_version', 4),
    'connection-version-disconnect': ('connection_disconnect_version', 1),
    **{f'connection-version-{action}': ('connection_version_contract', 2) for action in ('create', 'patch', 'delete')},
}


def split(kind, params):
    validate_operation_input(params)
    if kind != 'overhang-bulk' or type(params) is not dict or '_generated_scope' in params:
        raise ValueError('Connection organization requires a closed native connection command')
    context = params.get(KEY)
    if (type(context) is not dict or set(context) != {'version', 'removed_hosts'}
            or type(context['version']) is not int or context['version'] != 1
            or context['removed_hosts'] != 'follow_material'):
        raise ValueError('Unsupported connection organization context')
    action = params.get('action')
    contract = _VERSIONS.get(action) if type(action) is str else None
    if contract is None or type(params.get(contract[0])) is not int or params[contract[0]] != contract[1]:
        raise ValueError('Connection organization requires a qualified native contract version')
    return {key: value for key, value in params.items() if key != KEY}


def execute(kind, source, params, executor):
    from backend.core.part_connection_lineage import ConnectionLineage
    inputs = split(kind, params)
    if source.group_organization is None:
        raise CommandContractError('Connection organization requires an organized source', code='group_organization_required')
    if _trace.get() is not None:
        raise CommandContractError('Nested connection lineage is unsupported', code='invalid_connection_lineage')
    plan = ConnectionLineage(source)
    # Organization has already been bounded and selected. The unchanged native
    # builder sees a private projection; only final validated membership returns.
    token = _trace.set(plan)
    try:
        result = executor(kind, source.copy_with(group_organization=None), inputs)
        return plan.finish(result)
    finally:
        _trace.reset(token)


def observe(before, after, *, moved=None, added_linker=None, removed_linker=None):
    plan = _trace.get()
    if plan is not None:
        plan.advance(before, after, moved=moved, added_linker=added_linker, removed_linker=removed_linker)


def observe_direct(before, after, slots):
    if _trace.get() is None:
        return
    from backend.core.part_saved_topology import snapshot_for
    owners = [owner for kind, collection in [('overhang_binding', after.overhang_bindings), ('duplex', after.duplexes)]
              for owner in collection if (kind, owner.id) in slots and owner.bound and owner.prior_driven_topology]
    if len(owners) != 1:
        raise CommandContractError('Direct connection requires one material owner', code='invalid_connection_lineage')
    observe(before, after, moved=snapshot_for(owners[0]).value)
