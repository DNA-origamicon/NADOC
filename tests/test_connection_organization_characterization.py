"""Native organization migration evidence; no gate bypass in production.

The oracle deliberately removes organization in an isolated copy to observe the
unchanged molecular builder. These checks do not claim organized replay support.
"""

import pytest

from backend.api.part_proof_commands import execute
from backend.core.part_command_errors import CommandContractError
from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, native_prefix as native_prefix
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_inverse import apply_params


def organize(source):
    source = append(source, 'group-organize', {'_proof_version': 1,
        'expected_placement_ids': [c.id for c in source.cluster_transforms]}, 'organize')
    for i, overhang in enumerate(source.overhangs[:2]):
        strand, ordinal = next((s, j) for s in source.strands for j, d in enumerate(s.domains)
                               if d.overhang_id == overhang.id)
        for mode in ['host', 'domain']:
            values = {'id': f'{mode}-{i}', 'name': f'{mode}-{i}', 'helix_ids': [overhang.helix_id]}
            if mode == 'domain':
                values['domain_ids'] = [{'strand_id': strand.id, 'domain_index': ordinal}]
            source = append(source, 'group-create', {'_proof_version': 1, 'group': values}, f'{mode}-{i}')
    return source


def address(domain):
    return domain.helix_id, domain.direction, domain.start_bp, domain.end_bp


def backing(design, identity):
    return next((s.id, i, d) for s in design.strands for i, d in enumerate(s.domains) if d.overhang_id == identity)


@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
def test_direct_relocation_requires_material_transport_not_only_identity(direct_source, direct_type):
    source = organize(pending(direct_source, direct_type))
    before = source.model_dump_json()
    inputs = direct_params(source)
    with pytest.raises(CommandContractError) as caught:
        execute('overhang-bulk', source, inputs)
    assert caught.value.code == 'unsupported_group_organization_command'
    native = execute('overhang-bulk', source.copy_with(group_organization=None), inputs)
    owner = next(o for o in [*native.overhang_bindings, *native.duplexes] if o.bound and o.prior_driven_topology)
    saved = owner.prior_driven_topology
    identity = saved['driven_oh_id']
    prior, current = backing(source, identity), backing(native, identity)
    # A valid source domain survives, but at a different directional address.
    assert prior[:2] == current[:2]
    assert address(prior[2]) != address(current[2])
    assert abs(prior[2].end_bp - prior[2].start_bp) == abs(current[2].end_bp - current[2].start_bp)
    removed = {h.id for h in source.helices} - {h.id for h in native.helices}
    assert removed == {prior[2].helix_id}
    from backend.core.part_structure_gate import require_valid_structure, PartStructureError
    with pytest.raises(PartStructureError):
        require_valid_structure(native.copy_with(group_organization=source.group_organization))
    from backend.core.part_group_lineage import prepare_lineage, apply_lineage
    # Reusing a conserved/fresh-helix adapter cannot classify relocation.
    with pytest.raises(CommandContractError):
        apply_lineage(prepare_lineage(source, 'sweep', {}), native)
    assert any(g.helix_ids == [prior[2].helix_id] and not g.domain_ids for g in source.group_organization.groups)
    # Same-address overlap cannot follow this owner. Copying old organization
    # also leaves a dangling whole-host group despite a valid domain reference.
    assert not any(address(d) == address(prior[2]) for s in native.strands for d in s.domains)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('family', ['root-to-root-ssdna-linker', 'root-to-root-dsdna-linker', 'root-to-root-indirect'])
def test_linker_adds_new_material_on_existing_hosts(application_prefix, family):
    source = organize(pending(application_prefix, family))
    inputs = apply_params(source, 'candidate')
    native = execute('overhang-bulk', source.copy_with(group_organization=None), inputs)
    old = {address(d) for s in source.strands for d in s.domains}
    added_on_old_hosts = [d for s in native.strands for d in s.domains
                          if d.helix_id in {h.id for h in source.helices} and address(d) not in old]
    assert added_on_old_hosts
    from backend.core.part_group_lineage import prepare_lineage, apply_lineage
    with pytest.raises(CommandContractError):
        apply_lineage(prepare_lineage(source, 'sweep', {}), native)
    assert all(d.binds_overhang_id in {o.id for o in source.overhangs[:2]} for d in added_on_old_hosts)


@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
def test_restoration_returns_material_to_its_original_address(direct_source, direct_type):
    from backend.api.part_connection_disconnect import capture_inputs
    source = pending(direct_source, direct_type)
    native = append(source, 'overhang-bulk', direct_params(source), 'apply')
    owner = next(o for o in [*native.overhang_bindings, *native.duplexes] if o.bound and o.prior_driven_topology)
    identity = owner.prior_driven_topology['driven_oh_id']
    disconnected = execute('overhang-bulk', native, capture_inputs(native, native.connection_versions[0], delete_version=False))
    assert address(backing(disconnected, identity)[2]) == address(backing(source, identity)[2])
    assert backing(disconnected, identity)[:2] == backing(source, identity)[:2]
