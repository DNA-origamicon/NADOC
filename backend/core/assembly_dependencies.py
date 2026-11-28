"""Saved-input assembly dependencies using the shared typed dependency index.

Pose propagation, group membership, automatic pairing and cascading deletion
have state-dependent reach. Their reviewed contracts conservatively order the
whole assembly; replay determines whether a proposed order actually works.
Unknown/legacy commands stay unknown barriers, never independent operations.
"""
from backend.core.part_dependencies import Dependencies, Resource

GLOBAL_COMMANDS = frozenset('''
assembly-linear-pattern assembly-circular-pattern
assembly-delete-instance assembly-propagate-fk assembly-transform-instance
assembly-instance-overhang-extrude assembly-instance-overhang-patch
assembly-instance-history-change
assembly-transform-instance-cluster assembly-replace-instance-source
assembly-overhang-bind assembly-overhang-bind-patch assembly-overhang-unbind
assembly-overhang-connection-add assembly-overhang-connection-patch
assembly-overhang-connection-delete assembly-overhang-connection-relax
assembly-duplex-add assembly-duplex-connect assembly-duplex-sync
assembly-duplex-patch assembly-duplex-delete
assembly-create-belt assembly-patch-belt assembly-delete-belt
assembly-create-belt-rider assembly-delete-belt-rider assembly-polymerize-belt
assembly-patch-joint assembly-refresh-mate assembly-delete-joint
assembly-polymerize assembly-polymerize-periodic assembly-transform-group
assembly-create-group assembly-patch-group assembly-ungroup assembly-delete-group
assembly-duplicate-group assembly-create-gear assembly-patch-gear
assembly-delete-gear assembly-resolve-gear assembly-add-joint assembly-create-mate
'''.split())
LOCAL_COMMANDS = frozenset({'assembly-add-instance', 'assembly-duplicate-instance',
    'assembly-patch-instance', 'assembly-add-connector', 'assembly-delete-connector'})


def dependencies(kind, params, *, suppressed=False):
    if (not isinstance(params, dict) or type(params.get('command_version')) is not int
            or params['command_version'] != 1 or not isinstance(params.get('inputs'), dict)
            or len(params['inputs']) > 64 or kind not in GLOBAL_COMMANDS | LOCAL_COMMANDS):
        return Dependencies(known=False)
    if suppressed:
        return Dependencies()
    if kind in GLOBAL_COMMANDS:
        return Dependencies(barrier=True)
    inputs = params['inputs']
    if kind == 'assembly-patch-instance' and any(value is not None for key, value in inputs.items()
                                               if key not in {'name', 'visible', 'representation'}):
        return Dependencies(barrier=True)
    reads, writes = set(), set()
    def resource(key, collection):
        value = params.get(key)
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ValueError('Invalid instance selection')
        collection.add(Resource('assembly-instance', value))
    try:
        if kind == 'assembly-add-instance':
            resource('instance_id', writes)
        elif kind == 'assembly-duplicate-instance':
            resource('source_instance_id', reads)
            resource('new_instance_id', writes)
        else:
            resource('instance_id', reads)
            resource('instance_id', writes)
    except ValueError:
        return Dependencies(known=False)
    return Dependencies(reads=frozenset(reads), writes=frozenset(writes))
