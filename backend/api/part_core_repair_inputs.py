"""Reviewed core-tool repair fields, using the ordinary native edit contracts.

Only authored leaves from a closed family schema are exposed. Output identities,
frozen deformation receipts and placement provenance never become input knobs.
Reference choices describe the preceding recipe; full replay decides validity.
"""

from copy import deepcopy

from backend.core.part_command_errors import CommandContractError
from backend.core.part_overlay_commands import command_input


COLLECTIONS = {'helix': 'helices', 'strand': 'strands', 'cluster': 'cluster_transforms',
               'crossover': 'crossovers', 'forced_ligation': 'forced_ligations',
               'nucleotide_transform': 'nucleotide_transforms', 'lattice_frame': 'lattice_frames'}
REFERENCES = {'helix_id': 'helix', 'helix_ids': 'helix', 'affected_helix_ids': 'helix',
              'strand_id': 'strand', 'three_prime_strand_id': 'strand', 'five_prime_strand_id': 'strand',
              'cluster_id': 'cluster', 'cluster_ids': 'cluster', 'crossover_id': 'crossover',
              'crossover_ids': 'crossover', 'fl_id': 'forced_ligation',
              'forced_ligation_ids': 'forced_ligation', 'transform_id': 'nucleotide_transform'}
REFERENCES.update(source_helix_id='helix', ref_helix_id='helix', source_frame_id='lattice_frame')
OVERLAYS = {'deformation', 'cluster_create', 'cluster_op'}


def core_entry(entry):
    """Typed, source-free discovery: no serialization or hashing under a lock."""
    from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, DeformationLogEntry
    if type(entry) not in {ClusterCreateLogEntry, ClusterOpLogEntry, DeformationLogEntry} or type(entry.proof_version) is not int:
        return False
    if type(entry) is ClusterCreateLogEntry:
        return entry.proof_version == 3 and entry.cluster_snapshot is not None and entry.cluster_id == entry.cluster_snapshot.id
    if type(entry) is ClusterOpLogEntry:
        return entry.proof_version == 1
    return (type(entry) is DeformationLogEntry and entry.proof_version == 1
            and entry.op_snapshot is not None and entry.deformation_id == entry.op_snapshot.id
            and type(entry.deformation_id) is str and 0 < len(entry.deformation_id) <= 256
            and entry.op_snapshot.params.kind == entry.op_snapshot.type
            and entry.op_snapshot.type in {'bend', 'twist'} and _native_targets(entry.op_snapshot.targets))


def _native_targets(targets):
    return targets is None or (type(targets) is list and bool(targets) and
        all(type(target) is dict and target.get('kind') in {'cluster', 'strand', 'domain'} for target in targets))


def _reject(detail):
    raise CommandContractError(detail, code='protected_recipe_identity')


def supported(kind, params):
    from backend.api.part_routing_edit_inputs import KINDS as ROUTING
    from backend.api.part_transform_inputs import KINDS as TRANSFORMS
    from backend.api.part_extrusion_edit_inputs import KINDS as EXTRUSIONS
    if kind == 'cluster_create':
        return params.get('_proof_version') == 3
    if kind == 'deformation':
        # Retired named-group selectors retain their existing separate adapter.
        return params.get('type') in {'bend', 'twist'} and _native_targets(params.get('targets'))
    return kind in ROUTING | TRANSFORMS | EXTRUSIONS | {'sweep'}


def _normalized(kind, params):
    from backend.api import part_routing_edit_inputs as routing, part_transform_inputs as transform
    from backend.api import part_extrusion_edit_inputs as extrusion
    if kind in routing.KINDS:
        return routing.normalize(kind, params, {})
    if kind in transform.KINDS:
        return transform.normalize(kind, params, {})
    if kind in extrusion.KINDS or kind == 'sweep':
        from backend.api.part_geometry_inputs import normalize
        return normalize(kind, params, {})
    if kind == 'deformation':
        from backend.api.part_deformation_inputs import normalize
        from backend.core.models import DeformationOp
        if type(params.get('_proof_version')) is not int or params['_proof_version'] != 1:
            _reject('Deformation repair requires its native proof version')
        normalize(params, {})
        DeformationOp.model_validate({k: v for k, v in params.items() if k != '_proof_version'})
        from backend.core.part_group_selection import target_references
        target_references(params.get('targets'))
    elif kind == 'cluster_create':
        from backend.core.models import ClusterRigidTransform
        if set(params) != {'cluster', '_proof_version'} or type(params['_proof_version']) is not int or params['_proof_version'] != 3:
            _reject('Cluster repair requires native placement-preserving creation')
        ClusterRigidTransform.model_validate(params['cluster'])
    else:
        _reject('This family has no reviewed core repair inputs')
    return deepcopy(params)


def fields(kind, params):
    """Closed top-level allowlists plus schema-validated nested scalar leaves."""
    from backend.api import part_routing_edit_inputs as routing, part_transform_inputs as transform
    from backend.api import part_extrusion_edit_inputs as extrusion
    _normalized(kind, params)
    values = params  # Defaults are not existing authored paths/expectations.
    if kind in routing.KINDS:
        names = routing._fields(kind, values)
    elif kind in extrusion.KINDS:
        names = extrusion.EDIT_FIELDS[kind]
    elif kind == 'sweep':
        from backend.api.part_sweep_preview import EDIT_FIELDS
        names = EDIT_FIELDS
    elif kind == 'deformation':
        names = {'plane_a_bp', 'plane_b_bp', 'params', 'cluster_ids'}
        if values.get('targets') is not None:
            names.discard('cluster_ids')
            names.add('targets')
        if values.get('target_ranges') is None and not values.get('cluster_ids'):
            names.add('affected_helix_ids')
    elif kind == 'cluster_create':
        names = {'cluster'}
    elif kind == 'cluster_op':
        names = transform.POSE_FIELDS | transform.AUTHORED_FIELDS | {'cluster_id'}
    elif kind == 'placement-poses':
        # Frame/owner replacement is coupled and uses the existing whole-pose editor.
        names = {'poses'}
    elif kind == 'nucleotide-transform-batch':
        names = {'transforms'}
    elif kind == 'nucleotide-transform-delete':
        names = {'transform_id'}
    else:
        names = transform._BODY_FIELDS - {'kind'}
    result = []

    def visit(value, path, name):
        if name.startswith('_') or (kind == 'crossover-place-batch' and name == 'crossover_id'):
            return  # Allocated batch outputs are never replacement targets.
        if kind == 'nucleotide-transform-batch' and name == 'kind':
            return
        if kind == 'cluster_create' and len(path) == 2 and name not in {
                'name', 'helix_ids', 'domain_ids', 'color', 'opacity'}:
            return
        if kind == 'placement-poses' and len(path) == 3 and name not in transform.POSE_FIELDS:
            return
        if path[:1] == ['params'] and name in {'kind', 'endpoints', 'midpoint', 'polymer_circle_count'}:
            return
        if kind == 'deformation' and path[:1] == ['targets'] and len(path) == 3:
            target = values['targets'][path[1]]
            resource = target['kind'] if name == 'id' else 'strand' if name in {'strand_id', 'strandId'} else None
            if resource:
                result.append((path, 'reference', resource, False))
            elif name in {'domain_index', 'domainIndex'}:
                result.append((path, 'integer', None, False))
            return
        if type(value) is dict:
            for key, child in value.items():
                visit(child, [*path, key], key)
        elif type(value) is list:
            for index, child in enumerate(value):
                visit(child, [*path, index], name)
        elif name in REFERENCES and type(value) is str:
            result.append((path, 'reference', REFERENCES[name], False))
        elif type(value) in {str, bool, int, float} or (value is None and name in {
                'total_degrees', 'degrees_per_nm', 'color'}):
            input_type = ('number' if value is None and name != 'color' else
                          'boolean' if type(value) is bool else 'integer' if type(value) is int else
                          'number' if type(value) is float else 'string')
            result.append((path, input_type, None, name in {'total_degrees', 'degrees_per_nm', 'color'}))

    for name in sorted(names):
        if name in values:
            visit(values[name], [name], name)
    if len(result) > 512:
        _reject('Repair input inspection exceeds 512 authored fields; use the ordinary batch editor')
    return result


def validate_paths(kind, previous, proposed, paths):
    allowed = {tuple(path) for path, _, _, _ in fields(kind, previous)}
    if any(tuple(path) not in allowed for path in paths):
        _reject('Repair can change only the reviewed authored input fields')
    _normalized(kind, proposed)


def replacement(entry, params):
    """Rebuild the typed wrapper; prefix-dependent scope is bound during replay."""
    from backend.core.models import DeformationOp
    from backend.core.part_overlay_commands import edit_entry
    kind, _ = command_input(entry)
    if kind == 'deformation':
        return entry.model_copy(update={'op_snapshot': DeformationOp.model_validate(
            {k: v for k, v in params.items() if k != '_proof_version'})})
    if kind == 'cluster_create':
        return edit_entry(entry, params['cluster'])
    if kind == 'cluster_op':
        updated = edit_entry(entry, params)
        return updated.model_copy(update={'cluster_id': params['cluster_id']})
    return entry.model_copy(update={'params': params})


def bind_entry(entry, prefix, originals):
    original = originals.get(entry.id)
    if original is None:
        return entry
    kind, values = command_input(entry)
    if not supported(kind, values):
        return entry
    if kind == 'deformation':
        from backend.core.part_deformation_edit import resolve_group_edit
        if original.op_snapshot.targets != entry.op_snapshot.targets:
            from backend.core.part_group_selection import resolve_deformation_targets
            ranges = resolve_deformation_targets(prefix, entry.op_snapshot.targets)
            return entry.model_copy(update={'op_snapshot': entry.op_snapshot.model_copy(update={
                'target_ranges': ranges, 'affected_helix_ids': sorted({item.helix_id for item in ranges})})})
        patch = ({'cluster_ids': values['cluster_ids']} if
                 original.op_snapshot.cluster_ids != entry.op_snapshot.cluster_ids else {})
        return entry.model_copy(update={'op_snapshot': resolve_group_edit(
            prefix, original.op_snapshot, entry.op_snapshot, patch)})
    if kind == 'cluster_create':
        return entry  # Native creation checks membership, ownership and placement.
    from backend.api import part_routing_edit_inputs as routing, part_transform_inputs as transform
    from backend.api import part_geometry_inputs as geometry
    module = routing if kind in routing.KINDS else transform if kind in transform.KINDS else geometry
    return replacement(entry, module.bind_prefix(kind, values, prefix))


def reference(kind, params, path):
    if not supported(kind, params):
        return None
    for candidate, input_type, resource, _ in fields(kind, params):
        if candidate == path and input_type == 'reference':
            return resource, COLLECTIONS[resource], 'core_input'
    return None
