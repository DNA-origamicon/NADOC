import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.vr_clipboard import paste_snapshot, rigid_matrix
from backend.core.models import Design, Nanoparticle
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.design_geometry import fitting_geometry
from backend.core.nanoparticle import build_thiol_conjugation
from backend.api.vr_ligation import parse_event
from tests.test_circular_pattern import source_design


def placement():
    m = np.eye(4)
    m[:3, :3] = Rotation.from_euler('xyz', [20, 35, -15], degrees=True).as_matrix()
    m[:3, 3] = [12, -4, 18]
    return m


def test_snapshot_cluster_copy_uses_pose_and_survives_source_deletion():
    source = source_design()
    before = source.model_dump_json()
    target = Design(id=source.id, lattice_type=source.lattice_type)
    m = placement()
    out, ids = paste_snapshot(target, source, [{'kind': 'cluster', 'id': 'source'}], m)
    assert len(ids) == len(source.helices)
    assert source.model_dump_json() == before and not target.helices
    for old, new in zip(source.helices, out.helices, strict=True):
        expected = deformed_nucleotide_arrays(old, source)['positions'] @ m[:3, :3].T + m[:3, 3]
        np.testing.assert_allclose(deformed_nucleotide_arrays(new, out)['positions'], expected, atol=1e-5)


def test_rigid_particle_and_owned_dna_follow_same_rotated_pose():
    particle = Nanoparticle(diameter_nm=10)
    conjugation, helices, strands = build_thiol_conjugation(particle, scheme='direct_thiol', sequence='ACGT', count=2)
    source = Design(nanoparticles=[particle], nanoparticle_conjugations=[conjugation], helices=helices, strands=strands)
    m = placement()
    out, _ = paste_snapshot(Design(id=source.id), source,
        [{'kind': 'nanoparticle', 'id': particle.id}, *[{'kind': 'strand', 'id': s.id} for s in strands]], m)
    np.testing.assert_allclose(out.nanoparticles[0].pose.to_array(), m)
    original = np.array([n['backbone_position'] for n in fitting_geometry(source)])
    actual = np.array([n['backbone_position'] for n in fitting_geometry(out)])
    np.testing.assert_allclose(actual, original @ m[:3, :3].T + m[:3, 3], atol=1e-5)


def test_invalid_placement_and_stale_selection_are_refused():
    for matrix in [np.zeros((4,4)), np.eye(4)*2, np.full((4,4), np.nan)]:
        with pytest.raises(ValueError): rigid_matrix(matrix.flatten(order='F'))
    source = source_design()
    with pytest.raises(ValueError, match='no longer exists'):
        paste_snapshot(source, source, [{'kind':'strand','id':'missing'}], np.eye(4))


def test_event_pose_is_converted_from_launch_basis():
    m = placement()
    basis = np.eye(4); basis[:3,:3] = Rotation.from_euler('z', 70, degrees=True).as_matrix()
    event = dict(sequence=1, version=2, source=0, target=0, action='paste', owners=['owner'], matrix=m.flatten(order='F').tolist())
    parsed = parse_event(event, basis)
    np.testing.assert_allclose(np.array(parsed['matrix']).reshape((4,4),order='F'), np.linalg.inv(basis) @ m @ basis)
    assert parse_event({**event, 'matrix': [0]*16}) is None


@pytest.mark.parametrize('scope', ['cluster', 'domain'])
def test_copy_validation_does_not_mutate_and_paste_is_undoable(scope):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state
    source = source_design()
    state.set_design(source)
    refs = [{'kind':'cluster','id':'source'}] if scope == 'cluster' else [{'kind':'domain','strandId':source.strands[0].id,'domainIndex':0}]
    body = {'source': source.model_dump(mode='json'), 'refs':refs, 'matrix':placement().flatten(order='F').tolist()}
    client = TestClient(app)
    assert client.post('/api/vr/clipboard/validate', json=body).status_code == 200
    assert len(state.get_or_404().helices) == len(source.helices)
    response = client.post('/api/vr/clipboard/paste', json=body)
    assert response.status_code == 200, response.text
    assert len(state.get_or_404().helices) == len(source.helices) + (len(source.helices) if scope == 'cluster' else 1)
    assert state.get_or_404().feature_log[-1].op_kind == 'element-paste'
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_or_404().helices == source.helices


def domain_fixture():
    from backend.core.models import Strand, Domain, Direction, StrandExtension, Crossover, HalfCrossover
    d = source_design()
    h = [h.id for h in d.helices]
    d.strands = [Strand(id='route', domains=[Domain(helix_id=hid, start_bp=0, end_bp=4, direction=Direction.FORWARD) for hid in h])]
    d.extensions = [StrandExtension(id='tail', strand_id='route', end='three_prime', sequence='TT')]
    d.crossovers = [Crossover(id='junction', half_a=HalfCrossover(helix_id=h[0], index=4, strand=Direction.FORWARD),
                            half_b=HalfCrossover(helix_id=h[1], index=4, strand=Direction.FORWARD))]
    return d


@pytest.mark.parametrize('kind,indices', [('base',[1]), ('end',[1]), ('bond',[0,1]), ('crossover',[0,1]), ('extension',[2]), ('domain',[1]), ('strand',[0,1,2])])
def test_small_selections_copy_minimum_owning_domains_and_exact_pose(kind, indices):
    from backend.core.clipboard_scope import domain_scope
    from backend.core.vr_clipboard import preview_snapshot
    d = domain_fixture()
    h = [h.id for h in d.helices]
    refs = {
        'base': {'kind':'base','key':f'{h[1]}:2:FORWARD'},
        'end': {'kind':'end','key':f'{h[1]}:4:FORWARD'},
        'bond': {'kind':'bond','fromKey':f'{h[0]}:4:FORWARD','toKey':f'{h[1]}:0:FORWARD','strandId':'route'},
        'crossover': {'kind':'crossover','id':'junction'},
        'extension': {'kind':'extension','id':'tail'},
        'domain': {'kind':'domain','strandId':'route','domainIndex':1},
        'strand': {'kind':'strand','id':'route'},
    }
    ref = refs[kind]
    assert domain_scope(d, [ref])[0] == {('route', i) for i in indices}
    m = placement()
    out, ids = paste_snapshot(Design(id=d.id), d, [ref], m)
    assert len(out.strands) == 1
    assert len(out.strands[0].domains) == len(indices)
    assert len(ids) == len(indices)
    original = [n for n in fitting_geometry(d) if n['helix_id'] in {h[i] for i in indices} or
                (2 in indices and n['helix_id'].startswith('__ext_'))]
    actual = fitting_geometry(out)
    assert len(actual) == len(original)
    # Domain/helix identity is fresh, but traversal and nucleotide identity are retained.
    for a, b in zip(original, actual, strict=True):
        np.testing.assert_allclose(b['backbone_position'], m[:3,:3] @ a['backbone_position'] + m[:3,3], atol=1e-5)
    assert preview_snapshot(d, [ref])
    Design.model_validate_json(out.model_dump_json())


def test_union_deduplicates_and_splits_unselected_domain_gaps():
    d = domain_fixture()
    refs = [{'kind':'domain','strandId':'route','domainIndex':i} for i in (0,2,0)]
    out, _ = paste_snapshot(Design(id=d.id), d, refs, placement())
    assert len(out.strands) == 2
    assert all(len(s.domains) == 1 for s in out.strands)
    assert len(out.extensions) == 1 and out.extensions[0].strand_id == out.strands[1].id
    assert not out.crossovers


def test_overhang_forced_ligation_and_synthetic_base_ownership():
    from backend.core.clipboard_scope import domain_scope
    from backend.core.models import OverhangSpec, ForcedLigation
    d = domain_fixture()
    d.strands[0].domains[1].overhang_id = 'overhang'
    d.overhangs = [OverhangSpec(id='overhang', helix_id=d.helices[1].id, strand_id='route')]
    d.forced_ligations = [ForcedLigation(id='forced', three_prime_helix_id=d.helices[0].id,
        three_prime_bp=4, three_prime_direction='FORWARD', five_prime_helix_id=d.helices[1].id,
        five_prime_bp=0, five_prime_direction='FORWARD')]
    cases = [({'kind':'overhang','id':'overhang'}, {1}),
             ({'kind':'crossover','subtype':'forced_ligation','id':'forced'}, {0,1}),
             ({'kind':'base','key':'__ext_tail:0:FORWARD'}, {2}),
             ({'kind':'base','key':'__xb__:junction:0'}, {0,1})]
    for ref, indices in cases:
        assert domain_scope(d, [ref])[0] == {('route', i) for i in indices}
        out, _ = paste_snapshot(Design(id=d.id), d, [ref], placement())
        assert len(out.strands[0].domains) == len(indices)
        assert len(out.overhangs) == int(1 in indices)
        assert len(out.forced_ligations) == int({0,1} <= indices)


def test_free_protein_preview_and_copy_share_the_placement():
    from backend.core.models import ProteinAsset, ProteinAtom, ProteinAttachment, ProteinTargetFree
    from backend.core.vr_clipboard import preview_snapshot
    atom = ProteinAtom(serial=1, name='CA', element='C', res_name='GLY', chain_id='A', res_seq=1, x=2,y=3,z=4)
    asset = ProteinAsset(atoms=[atom])
    protein = ProteinAttachment(asset_id=asset.id, target=ProteinTargetFree())
    d = Design(protein_assets=[asset], protein_attachments=[protein])
    refs = [{'kind':'protein','id':protein.id}]
    out, _ = paste_snapshot(Design(id=d.id), d, refs, placement())
    np.testing.assert_allclose(out.protein_attachments[0].pose.to_array(), placement())
    assert len(preview_snapshot(d, refs)) == 12


def test_nanoparticle_kind_crosses_native_launch_boundary():
    from backend.api.routes_vr import VRLaunchRequest
    request = VRLaunchRequest(selected_selection_kind='nanoparticle', selected_owner_tokens=['particle'])
    assert request.selected_selection_kind == 'nanoparticle' and request.selected_owner_tokens == ['particle']


def test_domain_cluster_and_overlapping_picks_copy_once():
    from backend.core.models import DomainRef
    d = domain_fixture()
    d.cluster_transforms[0].domain_ids = [DomainRef(strand_id='route',domain_index=1)]
    out, _ = paste_snapshot(Design(id=d.id), d, [{'kind':'cluster','id':'source'},
        {'kind':'base','key':f'{d.helices[1].id}:2:FORWARD'}], placement())
    assert len(out.strands) == 1 and len(out.strands[0].domains) == 1
    assert len(out.helices) == 1


def test_bound_protein_keeps_external_anchor_pose_without_copying_anchor_dna():
    from backend.core.models import ProteinAsset, ProteinAtom, ProteinAttachment, ProteinTargetDesign, OverhangSpec
    from backend.core.protein import compose_protein_world_transform, resolve_overhang_anchor
    from backend.core.vr_clipboard import preview_snapshot
    d = domain_fixture()
    d.strands[0].domains[2].overhang_id = 'oh'
    d.overhangs = [OverhangSpec(id='oh',helix_id=d.helices[2].id,strand_id='route')]
    asset = ProteinAsset(atoms=[ProteinAtom(serial=1,name='CA',element='C',res_name='GLY',chain_id='A',res_seq=1,x=0,y=0,z=0)])
    protein = ProteinAttachment(asset_id=asset.id,target=ProteinTargetDesign(overhang_id='oh'))
    d.protein_assets = [asset]
    d.protein_attachments = [protein]
    tip, outward = resolve_overhang_anchor(fitting_geometry(d), 'oh', 'free_end')
    expected = placement() @ compose_protein_world_transform(asset,protein,tip,outward)
    refs = [{'kind':'protein','id':protein.id}]
    out, _ = paste_snapshot(Design(id=d.id), d, refs, placement())
    assert not out.strands and not out.helices
    np.testing.assert_allclose(out.protein_attachments[0].pose.to_array(),expected)
    assert preview_snapshot(d,refs)


def test_linker_base_copies_its_bridge_domain_without_adjacent_complements():
    from backend.core.models import OverhangConnection
    from backend.core.lattice import generate_linker_topology
    from tests.test_overhang_connections import _seed_with_real_oh_domains
    d = _seed_with_real_oh_domains()
    c = OverhangConnection(id='bridge-copy',overhang_a_id='oh_a_5p',overhang_b_id='oh_b_5p',
        overhang_a_attach='free_end',overhang_b_attach='free_end',linker_type='ds',length_value=8,length_unit='bp')
    d.overhang_connections = [c]
    d = generate_linker_topology(d,c)
    ns = [n for n in fitting_geometry(d) if n['helix_id']=='__lnk__bridge-copy']
    assert ns
    n = ns[0]
    out, _ = paste_snapshot(Design(id=d.id), d, [{'kind':'base','key':f"{n['helix_id']}:{n['bp_index']}:{n['direction']}"}], placement())
    assert len(out.strands) == 1 and len(out.strands[0].domains) == 1
    assert len(out.helices) == 1
    expected = [x for x in ns if x['direction']==n['direction']]
    actual = fitting_geometry(out)
    assert len(actual)==len(expected)
    for a,b in zip(expected,actual,strict=True):
        np.testing.assert_allclose(b['backbone_position'],placement()[:3,:3]@a['backbone_position']+placement()[:3,3],atol=1e-5)


def test_rigid_only_native_export_contains_selectable_visible_objects():
    from urllib.parse import unquote
    from backend.api.routes_vr import _serialize_scene
    from backend.core.models import ProteinAsset, ProteinAtom, ProteinAttachment, ProteinTargetFree
    atom = ProteinAtom(serial=1,name='CA',element='C',res_name='GLY',chain_id='A',res_seq=1,x=1,y=2,z=3)
    asset = ProteinAsset(atoms=[atom])
    d = Design(protein_assets=[asset], protein_attachments=[ProteinAttachment(id='protein',asset_id=asset.id,target=ProteinTargetFree())],
               nanoparticles=[Nanoparticle(id='particle',diameter_nm=4)])
    from types import SimpleNamespace
    scene = _serialize_scene(d,[],[],representations={'full'},atomistic_model=SimpleNamespace(atoms=[],bonds=[]))
    points = [line.split() for line in scene.splitlines() if line.startswith('P ')]
    assert len(points)==2
    assert {unquote(p[1]) for p in points} == {'rigid-ref:["protein","protein","0"]','rigid-ref:["nanoparticle","particle","core"]'}
    np.testing.assert_allclose([float(v) for v in points[0][2:6]], [0,0,0,2])
    assert len([line for line in scene.splitlines() if line.startswith('A ')]) == 2


def test_domain_copy_preserves_loop_copy_identity_and_skips():
    from backend.core.models import LoopSkip
    d = domain_fixture()
    d.helices[0].loop_skips = [LoopSkip(bp_index=2,delta=1),LoopSkip(bp_index=3,delta=-1)]
    ref = {'kind':'base','key':f'{d.helices[0].id}:2:FORWARD:1'}
    out, _ = paste_snapshot(Design(id=d.id),d,[ref],placement())
    old = [n for n in fitting_geometry(d) if n['helix_id']==d.helices[0].id]
    new = fitting_geometry(out)
    assert [(n['bp_index'],n['copy_k']) for n in new] == [(n['bp_index'],n['copy_k']) for n in old]
    for a,b in zip(old,new,strict=True):
        np.testing.assert_allclose(b['backbone_position'],placement()[:3,:3]@a['backbone_position']+placement()[:3,3],atol=1e-5)
