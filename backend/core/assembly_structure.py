"""Bounded assembly relation checks, without flattening or external file reads.

This checks live assembly ownership/selection references, not molecular geometry
or source-part topology. Historical configuration/animation selections may refer
to removed objects by their existing restore-only-if-present contract.
"""

COLLECTIONS = ('instances', 'joints', 'gear_relations', 'belt_paths', 'belt_riders',
               'groups', 'overhang_bindings', 'overhang_connections', 'duplexes',
               'protein_assets', 'protein_attachments')


class _Limit(Exception):
    pass


def assess_references(assembly, *, checkpoint=lambda: None, max_items=30000, max_issues=100):
    if any(type(v) is not int or v < 0 for v in (max_items, max_issues)):
        raise ValueError('Reference allowances must be nonnegative integers')
    result = {'scope': 'assembly_relation_references', 'version': 1, 'status': 'valid',
              'complete': True, 'scientific_integrity_checked': False, 'issues': [], 'checked_items': 0}
    indexes, source_indexes = {}, {}

    def step():
        checkpoint()
        result['checked_items'] += 1
        if result['checked_items'] > max_items:
            raise _Limit('reference_item_limit')

    def issue(code, path, value=None):
        if len(result['issues']) >= max_issues:
            raise _Limit('reference_issue_limit')
        result['issues'].append({'code': code, 'model_path': path, 'reference': value})

    def ref(index, value, path, optional=False):
        step()
        if value is None and optional:
            return None
        if not isinstance(value, str) or not value or len(value) > 512:
            issue('invalid_reference', path)
            return None
        if value not in index:
            issue('missing_reference', path, value)
            return None
        return index[value]

    def index_rows(rows, path, key='id'):
        index = {}
        for n, row in enumerate(rows):
            step()
            identity = getattr(row, key)
            if not isinstance(identity, str) or not identity or len(identity) > 512:
                issue('invalid_identity', [*path, n, key])
            elif identity in index:
                issue('duplicate_identity', [*path, n, key], identity)
            else:
                index[identity] = row
        return index

    def source(instance):
        if instance is None:
            return None
        key = id(instance.source)
        if key not in source_indexes:
            step()
            # Integrity is checked by source proof. Reference inspection uses
            # only the already embedded revision and never hashes physical data.
            design = instance.source.design if instance.source.type == 'inline' else instance.source.revision
            if design is None:
                raise _Limit('unpinned_source_reference_check')
            prefix = ['instances', instance.id, 'source']
            overhangs = index_rows(design.overhangs, [*prefix, 'overhangs'])
            source_indexes[key] = {
                'clusters': index_rows(design.cluster_transforms, [*prefix, 'cluster_transforms']),
                'joints': index_rows(design.cluster_joints, [*prefix, 'cluster_joints']),
                'overhangs': overhangs,
                'subdomains': {oid: index_rows(o.sub_domains, [*prefix, 'overhangs', oid, 'sub_domains']) for oid, o in overhangs.items()},
            }
        return source_indexes[key]

    def endpoint(instance_id, path, *, overhang=None, subdomain=None, connector=None, cluster=None):
        instance = ref(indexes['instances'], instance_id, path)
        if instance is None:
            return
        if connector is not None:
            ref(connectors[instance_id], connector, [*path, 'connector'])
        if any(value is not None for value in (overhang, subdomain, cluster)):
            data = source(instance)
            if data is None:
                return
            if cluster is not None:
                ref(data['clusters'], cluster, [*path, 'cluster'])
            if overhang is not None:
                found = ref(data['overhangs'], overhang, [*path, 'overhang'])
                if found is not None and subdomain is not None:
                    ref(data['subdomains'][overhang], subdomain, [*path, 'subdomain'])

    try:
        for field in COLLECTIONS:
            indexes[field] = index_rows(getattr(assembly, field), [field])
        connectors = {i.id: index_rows(i.interface_points, ['instances', i.id, 'interface_points'], 'label') for i in assembly.instances}
        for instance in assembly.instances:
            if instance.joint_states or instance.cluster_transform_overrides:
                data = source(instance)
                if data is not None:
                    for key in instance.joint_states:
                        ref(data['joints'], key, ['instances', instance.id, 'joint_states'])
                    for override in instance.cluster_transform_overrides:
                        ref(data['clusters'], override.id, ['instances', instance.id, 'cluster_transform_overrides'])
        for joint in assembly.joints:
            for side in ('a', 'b'):
                iid = getattr(joint, f'instance_{side}_id')
                if iid is None and side == 'a':
                    continue  # Ground is a legitimate parent.
                endpoint(iid, ['joints', joint.id, side], connector=getattr(joint, f'connector_{side}_label'), cluster=getattr(joint, f'cluster_id_{side}'))
        for gear in assembly.gear_relations:
            for side in ('a', 'b'):
                path = ['gear_relations', gear.id, side]
                joint = ref(indexes['joints'], getattr(gear, f'joint_{side}_id'), path)
                iid = getattr(gear, f'endpoint_{side}_instance_id')
                endpoint_side = getattr(gear, f'endpoint_{side}_side')
                if joint is not None:
                    if joint.joint_type != 'revolute':
                        issue('non_revolute_joint', path, joint.id)
                    if iid is not None and iid not in (joint.instance_a_id, joint.instance_b_id):
                        issue('endpoint_not_on_joint', path, iid)
                    if iid is not None and endpoint_side is not None and iid != getattr(joint, f'instance_{endpoint_side}_id'):
                        issue('endpoint_side_mismatch', path, iid)
        for belt in assembly.belt_paths:
            for side in ('a', 'b'):
                pulley = getattr(belt, f'pulley_{side}')
                path = ['belt_paths', belt.id, side]
                joint = ref(indexes['joints'], pulley.joint_id, path)
                if joint is not None:
                    if joint.joint_type != 'revolute':
                        issue('non_revolute_joint', path, joint.id)
                    expected = getattr(joint, f'instance_{pulley.side}_id')
                    if pulley.instance_id is not None and pulley.instance_id != expected:
                        issue('endpoint_side_mismatch', path, pulley.instance_id)
                    if expected is not None:
                        endpoint(expected, path, connector=pulley.connector_label)
        for rider in assembly.belt_riders:
            ref(indexes['belt_paths'], rider.belt_path_id, ['belt_riders', rider.id, 'belt_path_id'])
            endpoint(rider.instance_id, ['belt_riders', rider.id], connector=rider.connector_label)
        for field in ('overhang_bindings', 'overhang_connections'):
            for edge in getattr(assembly, field):
                for side in ('a', 'b'):
                    endpoint(getattr(edge, f'instance_{side}_id'), [field, edge.id, side],
                             overhang=getattr(edge, f'overhang_{side}_id'), subdomain=getattr(edge, f'sub_domain_{side}_id', None))
        for duplex in assembly.duplexes:
            for side in ('left', 'right'):
                end = getattr(duplex, side)
                endpoint(end.instance_id, ['duplexes', duplex.id, side], overhang=end.overhang_id)
            ref(indexes['overhang_connections'], duplex.connection_id, ['duplexes', duplex.id, 'connection_id'], optional=True)
        for attachment in assembly.protein_attachments:
            ref(indexes['protein_assets'], attachment.asset_id, ['protein_attachments', attachment.id, 'asset_id'])
            target = attachment.target
            if target.kind == 'assembly':
                endpoint(target.instance_id, ['protein_attachments', attachment.id, 'target'], overhang=target.overhang_id, connector=target.interface_label)
        parents, remaining = {}, {}
        for group in assembly.groups:
            remaining[group.id] = len(group.subgroup_ids)
            for field, index in (('instance_ids', indexes['instances']), ('subgroup_ids', indexes['groups'])):
                for identity in getattr(group, field):
                    ref(index, identity, ['groups', group.id, field])
                    key = (field, identity)
                    if key in parents:
                        issue('multiple_group_parents', ['groups', group.id, field], identity)
                    parents[key] = group.id
        pending = [gid for gid, count in remaining.items() if count == 0]
        visited = set()
        while pending:
            step()
            gid = pending.pop()
            visited.add(gid)
            parent = parents.get(('subgroup_ids', gid))
            if parent in remaining:
                remaining[parent] -= 1
                if remaining[parent] == 0:
                    pending.append(parent)
        if len(visited) != len(remaining):
            issue('group_cycle_or_unresolved_child', ['groups'])
    except _Limit as error:
        result.update(status='incomplete', complete=False, limit=str(error))
        return result
    if result['issues']:
        result['status'] = 'invalid'
    return result
