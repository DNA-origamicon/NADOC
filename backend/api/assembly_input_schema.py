"""Editable assembly inputs, bounded by source-part ownership.

Request schemas remain authoritative. This adapter supplies typed geometry and
historical reference choices where older requests use unstructured dict/list fields.
Recovery state is used only for choices, never as proof or new construction input.
"""
from copy import deepcopy
from importlib import import_module

from fastapi import HTTPException

from backend.api.assembly_command_replay import COMMANDS

PART_COMMANDS = frozenset({
    'assembly-instance-history-change', 'assembly-instance-overhang-extrude',
    'assembly-instance-overhang-patch', 'assembly-transform-instance-cluster',
    'assembly-replace-instance-source',
})
EXCLUDED = {
    'source': 'Open the source part separately; its definition is not an assembly input.',
    'silent': 'Playback transport is not an authored input.',
    'expected_revision': 'Revision guard is managed by the editor.',
    'expected_assembly_id': 'Document guard is managed by the editor.',
    'mode': 'Part flexibility is not edited by assembly history.',
    'allow_part_joints': 'Part-internal joint behavior belongs to the source part.',
    'joint_states': 'Part-internal joint states are not assembly inputs.',
    'cluster_transform_overrides': 'Part-internal transforms belong to the source part.',
}
VECTORS = {'translation', 'offset', 'axis_origin', 'axis_direction', 'axis_point',
           'position', 'normal', 'center_world', 'connector_world', 'vector', 'vector2'}
MATRICES = {'matrix', 'local_transform'}
ENUMS = {
    'joint_type': ['rigid', 'revolute', 'prismatic', 'spherical'],
    'binding_mode': ['duplex', 'toehold'], 'linker_type': ['ss', 'ds'],
    'length_unit': ['bp', 'nm'], 'overhang_a_attach': ['root', 'free_end'],
    'overhang_b_attach': ['root', 'free_end'], 'driver': ['left', 'right'],
    'representation': ['full', 'beads', 'cylinders', 'vdw', 'ballstick', 'stick', 'hull-prism', 'surface', 'surface-detail'],
}


def command_schema(kind):
    spec = COMMANDS.get(kind)
    if kind in PART_COMMANDS or not spec:
        raise HTTPException(422, 'This operation has no editable assembly-owned inputs.')
    model = getattr(import_module(f'backend.api.{spec[0]}'), spec[2]) if spec[2] else None
    raw = model.model_json_schema() if model else {'type': 'object', 'properties': {}}
    definitions = raw.get('$defs', {})

    def expand(node, key=''):
        node = deepcopy(node)
        if '$ref' in node:
            node = {**deepcopy(definitions[node.pop('$ref').split('/')[-1]]), **node}
        if 'anyOf' in node:
            choices = node.pop('anyOf')
            nonnull = [item for item in choices if item.get('type') != 'null']
            if len(nonnull) != 1:
                raise ValueError(f'Unreviewed assembly schema union: {key}')
            node = {**expand(nonnull[0], key), **node, 'nullable': True}
        if key in VECTORS | MATRICES:
            node.update(type='array', items={'type': 'number'}, minItems=16 if key in MATRICES else 3,
                        maxItems=16 if key in MATRICES else 3, format='matrix' if key in MATRICES else 'vector')
        elif key == 'transform':
            node.update(type='object', required=['values'], properties={'values': {
                'type': 'array', 'items': {'type': 'number'}, 'minItems': 16, 'maxItems': 16, 'format': 'matrix'}})
        if key in ENUMS:
            node['enum'] = ENUMS[key]
        if node.get('type') == 'object':
            node['properties'] = {name: expand(value, name) for name, value in node.get('properties', {}).items()}
        if node.get('type') == 'array':
            node['items'] = expand(node['items'])
        return node

    schema = expand(raw)
    if kind in {'assembly-linear-pattern', 'assembly-circular-pattern'}:
        from backend.api.pattern_features import LinearPatternBody, CircularPatternBody
        pattern = (LinearPatternBody if kind == 'assembly-linear-pattern' else CircularPatternBody).model_json_schema()
        pattern['properties'] = {k: v for k, v in pattern['properties'].items() if k not in {
            'cluster_id', 'cluster_ids', 'expected_revision', 'expected_design_id', '_organization_copy'}}
        pattern['required'] = [k for k in pattern.get('required', []) if k in pattern['properties']]
        schema['properties']['parameters'] = expand(pattern)
    excluded = {key: EXCLUDED[key] for key in schema['properties'] if key in EXCLUDED}
    schema['properties'] = {key: value for key, value in schema['properties'].items() if key not in excluded}
    schema['required'] = [key for key in schema.get('required', []) if key not in excluded]
    if spec[3]:
        targets = spec[3] if isinstance(spec[3], tuple) else (spec[3],)
        schema['properties']['_targets'] = {'type': 'object', 'required': list(targets),
            'properties': {key: {'type': 'string', **({'reference': 'connector'} if key == 'label' else {})} for key in targets}}
    schema.pop('$defs', None)
    return schema, excluded


def validate_editor_inputs(kind, inputs):
    """Do not expose internal mutations or transport through ordinary input edits."""
    schema, _ = command_schema(kind)
    if not isinstance(inputs, dict) or set(inputs) - schema['properties'].keys():
        raise HTTPException(422, 'Only assembly-owned editable inputs may be changed here.')


def reference_choices(assembly):
    result = {}
    for kind, field in [('instance', 'instances'), ('joint', 'joints'), ('group', 'groups'),
                        ('belt', 'belt_paths'), ('rider', 'belt_riders'), ('relation', 'gear_relations'),
                        ('binding', 'overhang_bindings'), ('connection', 'overhang_connections'), ('duplex', 'duplexes')]:
        result[kind] = [{'value': obj.id, 'label': getattr(obj, 'name', '') or f'{kind.title()} {i + 1}'}
                        for i, obj in enumerate(getattr(assembly, field))]
    result.update(connector=[], cluster=[], overhang=[], sub_domain=[])
    for instance in assembly.instances:
        owner = instance.name or 'Part'
        result['connector'].extend({'value': item.label, 'label': f'{owner} / {item.label}', 'instance_id': instance.id}
                                   for item in instance.interface_points)
        design = instance.source.design if instance.source.type == 'inline' else instance.source.revision
        if design is None:
            continue
        for kind, field in [('cluster', 'cluster_transforms'), ('overhang', 'overhangs')]:
            for index, item in enumerate(getattr(design, field)):
                label = getattr(item, 'name', None) or getattr(item, 'label', None) or f'{kind.title()} {index + 1}'
                result[kind].append({'value': item.id, 'label': f'{owner} / {label}', 'instance_id': instance.id})
                if kind == 'overhang':
                    result['sub_domain'].extend({'value': sub.id, 'label': f'{owner} / {label} / domain {i + 1}',
                        'instance_id': instance.id, 'overhang_id': item.id} for i, sub in enumerate(item.sub_domains or []))
    return result


def input_editor(index, expected_revision, expected_feature_id):
    from backend.api import assembly_state
    from backend.api.assembly import _decode_entry_pre_state
    source, revision = assembly_state.copy_for_persist()
    if source is None:
        raise HTTPException(404, 'No active assembly.')
    if revision != expected_revision or not 0 <= index < len(source.feature_log) or source.feature_log[index].id != expected_feature_id:
        raise HTTPException(409, 'The assembly changed. Reopen this editor.')
    entry = source.feature_log[index]
    if entry.params.get('command_version') != 1:
        raise HTTPException(422, 'This legacy feature lacks complete recorded command inputs.')
    schema, excluded = command_schema(entry.op_kind)
    try:
        prefix = _decode_entry_pre_state(source.feature_log, index)
    except HTTPException:
        # Complete native recipes remain editable after recovery eviction.
        # No live session or recovery snapshot becomes an authoring input.
        from backend.api.assembly_command_replay import replay
        from backend.core.assembly_history_contract import create_empty_assembly
        if source.recipe_root is None:
            raise HTTPException(422, 'Historical input choices are unavailable; this assembly lacks a recorded root.') from None
        prefix = create_empty_assembly(source.recipe_root.initial_name).model_copy(update={'id': source.id})
        for row in source.feature_log[:index]:
            if not row.suppressed:
                prefix = replay(prefix, row.op_kind, row.params)
    values = {key: value for key, value in entry.params['inputs'].items() if key not in excluded}
    if '_targets' in schema['properties']:
        values['_targets'] = {key: entry.params[key] for key in schema['properties']['_targets']['properties']}
    return {'assembly_id': source.id, 'revision': revision, 'feature_id': entry.id,
            'schema': schema, 'excluded': excluded,
            'inputs': values,
            'input_fields_set': [key for key in entry.params.get('input_fields_set', entry.params['inputs']) if key not in excluded],
            'references': reference_choices(prefix)}
