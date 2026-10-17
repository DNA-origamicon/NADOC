"""Closed host-selected recovery scopes; saved JSON never selects authority."""

BATCH = 'strict_recovery_v1'
GEOMETRY = 'geometry_recovery_v1'
GEOMETRY_STORAGE = 'native_extrusion_v1'


def storage_scope(context):
    if context.scope_tag == BATCH:
        return 'registered_batch_v1'
    if context.scope_tag == GEOMETRY:
        return GEOMETRY_STORAGE
    raise ValueError('Unknown recovery admission scope')


def require_scope(context):
    scope = storage_scope(context)
    if context.scope_tag == GEOMETRY:
        from backend.api.part_immutable_geometry_publication import require_policy
        require_policy(context)
    return scope
