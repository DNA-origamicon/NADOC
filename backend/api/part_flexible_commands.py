"""Versioned replay of the public Relax flexible segments command.

Replay applies the recorded rigid poses, never reruns numerical minimisation.
The solver report records selection, reference bodies and achieved constraints.
"""
import math

from backend.core.part_dependencies import Dependencies, Resource


def values(params):
    from backend.core.part_operation_input import validate_operation_input

    validate_operation_input(params)
    allowed = {'_proof_version', 'cluster_ids', 'transforms', 'scope', 'conn_id', 'relaxation'}
    if (not isinstance(params, dict) or set(params) - allowed
            or params.get('_proof_version') != 1):
        raise ValueError('Unsupported flexible relaxation proof')
    transforms = params.get('transforms')
    if not isinstance(transforms, list) or not transforms:
        raise ValueError('Relax requires recorded poses')
    ids = []
    for t in transforms:
        if not isinstance(t, dict) or set(t) != {'cluster_id', 'pivot', 'translation', 'rotation'}:
            raise ValueError('Invalid relaxed pose')
        identity = t['cluster_id']
        if not isinstance(identity, str) or not identity:
            raise ValueError('Invalid relaxed cluster id')
        ids.append(identity)
        for key, n in (('pivot', 3), ('translation', 3), ('rotation', 4)):
            v = t[key]
            if (not isinstance(v, list) or len(v) != n
                    or any(type(x) not in (float, int) or not math.isfinite(x) for x in v)):
                raise ValueError('Invalid relaxed pose coordinates')
        if abs(sum(x*x for x in t['rotation']) - 1) > 1e-6:
            raise ValueError('Relaxed rotation must be a unit quaternion')
    if len(ids) != len(set(ids)) or params.get('cluster_ids') != ids:
        raise ValueError('Relaxed cluster selection does not match poses')
    if 'scope' in params and params['scope'] not in ('one', 'all'):
        raise ValueError('Invalid relaxation scope')
    return transforms


def dependencies(params):
    try:
        transforms = values(params)
    except (ValueError, TypeError, KeyError):
        return Dependencies(known=False)
    topology = Resource('part', 'topology')
    resources = frozenset({topology, *(Resource('cluster', t['cluster_id']) for t in transforms)})
    return Dependencies(resources, resources, barrier=True)


def apply_poses(design, transforms, *, carry=False):
    by_id = {t['cluster_id']: t for t in transforms}
    if not set(by_id) <= {c.id for c in design.cluster_transforms}:
        raise ValueError('Relaxed cluster no longer exists')
    updated = design.copy_with(cluster_transforms=[
        c.model_copy(update={key: by_id[c.id][key] for key in ('pivot', 'translation', 'rotation')})
        if c.id in by_id else c for c in design.cluster_transforms
    ])
    if carry:
        from backend.core.cluster_member_poses import carry_member_poses
        updated = carry_member_poses(design, updated)
    return updated


def execute(design, params):
    transforms = values(params)
    return apply_poses(design, transforms, carry='scope' in params)
