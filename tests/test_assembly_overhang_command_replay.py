"""Overhang assembly commands replay from recorded user-authored part sources."""

import pytest

from backend.api import assembly_state, state, crud, part_proof_commands
from backend.api.assembly import AddInstanceRequest, add_instance, EditAssemblyFeatureRequest, edit_assembly_feature
from backend.api import routes_assembly_overhangs as routes
from backend.core.models import Assembly
from backend.core.part_history_contract import assess_part_history
from tests.conftest import valid_overhang_sites
from tests.test_assembly_command_replay import replay_saved


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session()
    state.close_session()
    yield
    assembly_state.close_session()
    state.close_session()


def source_part(five_prime):
    crud.create_bundle(crud.BundleRequest(cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
    site = next(site for site in valid_overhang_sites(state.get_or_404()) if site['is_five_prime'] == five_prime)
    crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=8))
    design = state.get_or_404()
    proof = assess_part_history(design, execute=part_proof_commands.execute, dependencies=part_proof_commands.dependencies)
    assert proof['status'] == 'verified', proof
    return design.model_copy(deep=True)


def pair():
    root = Assembly()
    assembly_state.load_assembly(root)
    ends = []
    for five in [True, False]:
        design = source_part(five)
        add_instance(AddInstanceRequest(name=f'Part {five}', source={'type': 'inline', 'design': design.model_dump(mode='json')}))
        instance = assembly_state.get_or_404().instances[-1]
        ends.append((instance.id, design.overhangs[0]))
    return root, ends


def bind(ends):
    (a, oa), (b, ob) = ends
    routes.create_assembly_overhang_binding(routes.CreateAssemblyOverhangBindingRequest(
        instance_a_id=a, overhang_a_id=oa.id, sub_domain_a_id=oa.sub_domains[0].id,
        instance_b_id=b, overhang_b_id=ob.id, sub_domain_b_id=ob.sub_domains[0].id,
    ))
    return assembly_state.get_or_404().overhang_bindings[-1].id


def test_binding_sync_and_duplex_lifecycle_preserve_ids_times_and_inputs():
    root, ends = pair()
    binding = bind(ends)
    routes.patch_assembly_overhang_binding(binding, routes.PatchAssemblyOverhangBindingRequest(binding_mode='toehold'))
    replay_saved(root, assembly_state.get_or_404())
    routes.sync_assembly_duplexes()
    saved = assembly_state.get_or_404()
    assert len(saved.feature_log[-1].params['outputs']) == 1
    replay_saved(root, saved)
    duplex = saved.duplexes[0].id
    routes.patch_assembly_duplex(duplex, routes.PatchAssemblyDuplexBody(name='Recorded', driver='right'))
    index = len(assembly_state.get_or_404().feature_log) - 1
    routes.delete_assembly_overhang_binding(binding)
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'name': 'Edited'}))
    assert assembly_state.get_or_404().duplexes[0].name == 'Edited'
    replay_saved(root, assembly_state.get_or_404())
    routes.delete_assembly_duplex(duplex)
    replay_saved(root, assembly_state.get_or_404())
    (a, oa), (b, ob) = ends
    routes.connect_assembly_duplex(routes.ConnectAssemblyDuplexBody(
        instance_a_id=a, overhang_a_id=oa.id, instance_b_id=b, overhang_b_id=ob.id,
    ))
    saved = assembly_state.get_or_404()
    replay_saved(root, saved)
    dx = saved.duplexes[0]
    routes.delete_assembly_duplex(dx.id)
    routes.create_assembly_duplex(routes.CreateAssemblyDuplexBody(
        left=dx.left.model_dump(), right=dx.right.model_dump(), driver='left',
    ))
    replay_saved(root, assembly_state.get_or_404())


def test_linker_creation_patch_relax_and_delete_replay_materialized_topology():
    root, ends = pair()
    (a, oa), (b, ob) = ends
    routes.create_assembly_overhang_connection(routes.CreateAssemblyOverhangConnectionRequest(
        instance_a_id=a, overhang_a_id=oa.id, overhang_a_attach='free_end',
        instance_b_id=b, overhang_b_id=ob.id, overhang_b_attach='root',
        linker_type='ds', length_value=8, length_unit='bp',
    ))
    conn = assembly_state.get_or_404().overhang_connections[0].id
    replay_saved(root, assembly_state.get_or_404())
    routes.patch_assembly_overhang_connection(conn, routes.PatchAssemblyOverhangConnectionRequest(length_value=10, name='Edited linker'))
    replay_saved(root, assembly_state.get_or_404())
    before = assembly_state.get_or_404().model_copy(deep=True)
    routes.relax_assembly_overhang_connection(conn)
    relaxed = assembly_state.get_or_404()
    replay_saved(root, relaxed)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == relaxed
    routes.delete_assembly_overhang_connection(conn)
    assert not assembly_state.get_or_404().assembly_strands
    replay_saved(root, assembly_state.get_or_404())


def test_source_revisions_with_same_document_id_survive_wire_and_snapshot():
    from backend.api.assembly import _assembly_response
    from backend.core.assembly_geometry import geo_cache_key
    from backend.core.assembly_source_identity import compact_sources

    _, _ends = pair()
    original = assembly_state.get_or_404()
    a, b = original.instances
    assert a.source.design.id == b.source.design.id
    assert a.source.design != b.source.design
    assert geo_cache_key(a, None) != geo_cache_key(b, None)
    sources, _ = compact_sources([a, b, a.model_copy(deep=True)])
    assert len(sources) == 2
    saved = Assembly.from_json(original.to_json())
    assert saved.instances == original.instances
    payload = _assembly_response(original)['assembly']
    assert Assembly.model_validate(Assembly._expand_v2_payload(payload)).instances == original.instances
    snapshot, _ = assembly_state.encode_assembly_snapshot(original)
    assert assembly_state.decode_assembly_snapshot(snapshot).instances == original.instances


@pytest.mark.parametrize('operation', ['instance', 'group'])
def test_part_deletion_removes_cross_part_edges_and_linker_topology(operation):
    from backend.api.assembly import delete_instance
    from backend.api.routes_assembly_groups import CreateGroupRequest, create_group, cascade_delete_group

    root, ends = pair()
    bind(ends)
    routes.sync_assembly_duplexes()
    (a, oa), (b, ob) = ends
    routes.create_assembly_overhang_connection(routes.CreateAssemblyOverhangConnectionRequest(
        instance_a_id=a, overhang_a_id=oa.id, overhang_a_attach='free_end',
        instance_b_id=b, overhang_b_id=ob.id, overhang_b_attach='root',
        linker_type='ds', length_value=8, length_unit='bp',
    ))
    create_group(CreateGroupRequest(instance_ids=[a], name='Removed'))
    before = assembly_state.get_or_404().model_copy(deep=True)
    assert before.assembly_helices and before.assembly_strands and before.duplexes
    if operation == 'instance':
        delete_instance(a)
    else:
        cascade_delete_group(before.groups[0].id)
    after = assembly_state.get_or_404()
    assert not after.overhang_bindings
    assert not after.overhang_connections
    assert not after.duplexes
    assert not after.assembly_helices
    assert not after.assembly_strands
    assert after.instances == [before.instances[1]]
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after
