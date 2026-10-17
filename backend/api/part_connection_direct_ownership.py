"""Bounded source/ownership admission for native direct Apply."""

from backend.api import part_connection_application_commands as common
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_saved_topology import snapshot_for, validate_owner
from backend.core.part_scope_references import identity_index, referenced_resources


def _index(design, body):
    common._bounded_source(design, extra_fields=frozenset({'overhang_bindings', 'duplexes'}))
    if design.group_organization is not None:
        common._unsupported('Direct application organization integration is not yet qualified')
    try:
        index, _ = identity_index(design)
        for (kind, identity), record in index.items():
            missing = referenced_resources(record) - index.keys()
            if missing:
                target = sorted(missing)[0]
                path = next((field for field in ('overhang_a_id', 'overhang_b_id')
                             if target == ('overhang', getattr(body, field))), 'version_id')
                common._fail(f'{kind} {identity} has a missing source reference', *target, path, missing=True)
    except (NotImplementedError, TypeError) as error:
        common._unsupported(f'Direct application cannot classify source ownership: {error}')
    common._work_admission(design, 0, [])
    return index


def _backings(design):
    backings, hosts = {}, {}
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id is not None:
                backings.setdefault(domain.overhang_id, []).append((strand, domain))
    for spec in design.overhangs:
        hosts.setdefault(spec.helix_id, []).append(spec.id)
    return backings, hosts


def _conflicts(design, body, index, *, pair_only=False):
    from backend.api.connection_version_teardown import matches_endpoints
    selected = {body.overhang_a_id, body.overhang_b_id}
    result = {}
    for kind, collection, field in [
        ('overhang_connection', 'overhang_connections', 'conflict_connection_ids'),
        ('overhang_binding', 'overhang_bindings', 'conflict_binding_ids'),
        ('duplex', 'duplexes', 'conflict_duplex_ids'),
        ('connection_version', 'connection_versions', 'conflict_version_ids'),
    ]:
        records = [item for item in getattr(design, collection)
                   if matches_endpoints(item, selected, pair_only=pair_only)]
        actual, expected = [item.id for item in records], getattr(body, field)
        if actual != expected:
            absent = next((value for value in expected if (kind, value) not in index), None)
            common._fail('Direct application requires the exact ordered conflict set', kind,
                         absent or next(iter(actual or expected), body.version_id), field, missing=absent is not None)
        result[kind] = records
    return result


def _restoration_owners(design, records, index):
    from backend.core.duplex_cluster import _duplex_domain_refs

    driven_ids = set()
    for record in [*records['overhang_binding'], *records['duplex']]:
        kind = 'duplex' if hasattr(record, 'left') else 'overhang_binding'
        path = 'conflict_duplex_ids' if kind == 'duplex' else 'conflict_binding_ids'
        try:
            saved = snapshot_for(record)
            if saved is None:
                if record.bound:
                    common._fail('Bound direct owner has no restoration state', kind, record.id, path)
                continue
            validate_owner(saved, index)
        except ReferenceResolutionError as error:
            common._fail(str(error), kind, record.id, path)
        except NotImplementedError as error:
            common._unsupported(str(error))
        if not record.bound:
            common._fail('Unbound direct owner retains restoration state', kind, record.id, path)
        driven = saved.value['driven_oh_id']
        if driven in driven_ids:
            common._fail('Direct restoration ownership overlaps', 'overhang', driven, path)
        driven_ids.add(driven)
        driver = saved.value['driver_oh_id']
        if kind == 'duplex':
            live_driver = record.left.overhang_id if record.driver == 'left' else record.right.overhang_id
        else:
            live_driver = record.driver_oh_id
            if record.driven_oh_id != driven:
                common._fail('Direct driven selection disagrees with restoration ownership', kind, record.id, path)
        if live_driver != driver:
            common._fail('Direct driver selection disagrees with restoration ownership', kind, record.id, path)
        domain = index[('strand', saved.value['strand_id'])].domains[saved.value['domain_index']]
        prior = saved.value['prior_domain']
        if (domain.helix_id != index[('overhang', driver)].helix_id
                or abs(domain.end_bp - domain.start_bp) != abs(prior['end_bp'] - prior['start_bp'])):
            common._fail('Direct driven domain was edited outside its restoration contract', kind, record.id, path)
        for key, definition in saved.definitions():
            live = index.get(key)
            if live is not None and live != definition:
                common._fail('Restoration would overwrite an edited native owner', *key, path)
        if saved.ligation is not None and ('forced_ligation', saved.ligation.id) not in index:
            common._fail('Direct restoration lost its generated ligation', 'forced_ligation', saved.ligation.id, path, missing=True)
        clusters = [c for c in design.cluster_transforms if c.overhang_duplex_driver_id == driver]
        helix, refs = _duplex_domain_refs(design, driver)
        if (len(clusters) != 1 or not clusters[0].auto_created
                or clusters[0].helix_ids != [helix] or clusters[0].domain_ids != refs):
            common._fail('Direct restoration does not wholly own its placement cluster', kind, record.id, path)


def prepare(design, body):
    from backend.api.part_connection_direct_commands import output_slots
    restored, version, _, _ = prepare_replacement(design, body, slots=output_slots(body), slot_path='history_seed')
    return restored, version


def prepare_replacement(design, body, *, slots, slot_path, qualify_targets=True, pair_only=False):
    from backend.api.connection_version_teardown import remove_conflicts

    index = _index(design, body)
    version = common._resolve(index, 'connection_version', body.version_id, 'version_id')
    for field in ('overhang_a_id', 'overhang_b_id'):
        identity = getattr(body, field)
        common._resolve(index, 'overhang', identity, field)
        if getattr(version, field) != identity:
            common._fail('Selected direct version endpoint changed', 'overhang', identity, field)
    if body.overhang_a_id == body.overhang_b_id:
        common._fail('Direct application requires two distinct endpoints', 'overhang', body.overhang_b_id, 'overhang_b_id')
    if version.connection_type != body.connection_type:
        common._fail('Selected direct version type changed', 'connection_version', version.id, 'connection_type')
    collision = slots & index.keys()
    if collision:
        common._fail('Direct output identity already exists', *sorted(collision)[0], slot_path)
    for record in (index.values() if slots else ()):
        incoming = referenced_resources(record) & slots
        if incoming:
            common._fail('Direct output identity already has an incoming reference', *sorted(incoming)[0], slot_path)
        saved = snapshot_for(record)
        if saved is not None:
            historical = {key for key, _ in saved.definitions()} & slots
            if historical:
                common._fail('Direct output identity collides with saved topology', *sorted(historical)[0], slot_path)
    from backend.api.part_connection_owner_selection import resolve_selection
    body = resolve_selection(design, body, index, pair_only=pair_only)
    conflicts = _conflicts(design, body, index, pair_only=pair_only)
    backings, hosts = _backings(design)
    # Existing exact finite/indirect ownership checks prevent prefix-based
    # teardown from consuming unrelated authored material.
    common._removed_ownership(design, index, conflicts['overhang_connection'], backings, hosts, allow_indirect=True)
    _restoration_owners(design, conflicts, index)
    restored = remove_conflicts(design, (body.overhang_a_id, body.overhang_b_id), pair_only=pair_only)
    restored_index = _index(restored, body)  # Detect external references to removed owners.
    # Exact-pair removal may retain a legitimate A/C owner while removing A/B.
    # It must not leave an orphan placement from a missing A/B binding, including
    # legacy owners without a creator namespace.
    retained_drivers = set()
    if pair_only:
        from backend.api.connection_version_teardown import matches_endpoints
        selected = {body.overhang_a_id, body.overhang_b_id}
        retained_drivers.update(b.driver_oh_id for b in restored.overhang_bindings
                                if b.bound and not matches_endpoints(b, selected, pair_only=True))
        retained_drivers.update(d.left.overhang_id if d.driver == 'left' else d.right.overhang_id
                                for d in restored.duplexes
                                if d.bound and not matches_endpoints(d, selected, pair_only=True))
    for cluster in restored.cluster_transforms:
        driver = cluster.overhang_duplex_driver_id
        if driver in {body.overhang_a_id, body.overhang_b_id} and driver not in retained_drivers:
            common._fail('Retained placement already owns a direct endpoint', 'cluster', cluster.id, 'version_id')
    if qualify_targets:
        backings, hosts = _backings(restored)
        targets = [common._target(restored, restored_index, backings, hosts, getattr(body, field), field)
                   for field in ('overhang_a_id', 'overhang_b_id')]
        # Linker v3 performs this qualification together with its bridge budget
        # in _select_inputs; do not repeat the same domain/occupant scan there.
        common._complement_ownership(restored, restored_index, targets, set())
    return restored, version, index, restored_index
