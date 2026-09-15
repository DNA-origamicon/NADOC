import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.spatial import cKDTree

from backend.api import doc_context, state
from backend.api.main import app
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating, streptavidin_asset, require_coating_simulation_support
from backend.core.oxdna_staleness import design_build_fingerprint

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_design():
    doc_context.set_current_doc(None)
    state.set_design(Design())
    yield
    state.close_session()


def test_real_pdb_assembly_is_four_chains_not_first_model():
    protein = streptavidin_asset()
    assert {a.chain_id for a in protein.atoms} == set('ABCD')
    assert len([a for a in protein.atoms if a.name == 'CA']) == 484
    assert len(protein.atoms) == 3604
    assert not any(a.res_name == 'BTN' for a in protein.atoms)
    assert len([a for a in streptavidin_asset('biotin_tether').atoms if a.res_name == 'BTN']) == 16


@pytest.mark.parametrize('mode', ['adsorption', 'biotin_tether'])
def test_packing_is_deterministic_and_clash_checked(mode):
    coating = build_streptavidin_coating(20, mode)
    repeated = build_streptavidin_coating(20, mode)
    assert coating.model_dump() == repeated.model_dump()
    assert coating.target_count == 31
    assert 20 <= len(coating.poses) <= 31
    xyz = np.array([[a.x, a.y, a.z] for a in coating.protein.atoms])
    clouds = []
    for pose in coating.poses:
        mat = np.array(pose.values).reshape(4,4)
        assert np.linalg.det(mat[:3,:3]) == pytest.approx(1)
        cloud = xyz @ mat[:3,:3].T + mat[:3,3]
        assert np.min(np.linalg.norm(cloud, axis=1)) >= 10.17 - 1e-9
        for other in clouds:
            assert np.min(cKDTree(other).query(cloud)[0]) >= .25
        clouds.append(cloud)


def test_biotin_tail_points_toward_surface_and_anchor_has_requested_spacer():
    coating = build_streptavidin_coating(20, 'biotin_tether')
    xyz = {a.name: np.array([a.x,a.y,a.z]) for a in coating.protein.atoms if a.res_name == 'BTN'}
    for pose in coating.poses:
        mat = np.array(pose.values).reshape(4,4)
        anchor = mat[:3,:3] @ xyz['C11'] + mat[:3,3]
        tail = mat[:3,:3] @ (xyz['C11'] - xyz['C10'])
        assert np.linalg.norm(anchor) == pytest.approx(10 + coating.spacer_nm)
        assert np.dot(tail / np.linalg.norm(tail), anchor / np.linalg.norm(anchor)) == pytest.approx(-1)


def test_coating_create_resize_move_remove_and_undo_are_atomic():
    response = client.post('/api/design/nanoparticles/gold-nanospheres', json={'diameter_nm': 10, 'coating': {'mode': 'adsorption'}})
    assert response.status_code == 201, response.text
    particle = state.get_design().nanoparticles[0]
    pid = particle.id
    assert len(particle.coating.poses) == 7
    assert len(state.get_design().feature_log) == 1
    local_poses = [p.values for p in particle.coating.poses]
    pose = np.eye(4); pose[:3,3] = [3,4,5]
    assert client.patch(f'/api/design/nanoparticles/{pid}', json={'pose': pose.ravel().tolist()}).status_code == 200
    assert [p.values for p in state.get_design().nanoparticles[0].coating.poses] == local_poses
    assert client.patch(f'/api/design/nanoparticles/{pid}', json={'diameter_nm': 20}).status_code == 200
    assert len(state.get_design().nanoparticles[0].coating.poses) == 31
    assert client.patch(f'/api/design/nanoparticles/{pid}', json={'coating': None}).status_code == 200
    assert state.get_design().nanoparticles[0].coating is None
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_design().nanoparticles[0].coating is not None
    assert client.delete(f'/api/design/nanoparticles/{pid}').status_code == 200
    assert not state.get_design().nanoparticles
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_design().nanoparticles[0].coating is not None


def test_invalid_coating_does_not_create_partial_particle_or_history():
    response = client.post('/api/design/nanoparticles/gold-nanospheres', json={'diameter_nm': 101, 'coating': {}})
    assert response.status_code == 422
    assert not state.get_design().nanoparticles
    assert not state.get_design().feature_log


def test_simulation_guards_and_cosmetic_fingerprint_stability(tmp_path):
    from backend.core.namd_package import build_namd_package
    from backend.core.openmm_implicit import build_openmm_topology
    from backend.physics.oxdna_interface import write_topology
    design = Design(nanoparticles=[Nanoparticle(diameter_nm=10)])
    bare = design_build_fingerprint(design)
    design.nanoparticles[0].coating = build_streptavidin_coating(10)
    coated = design_build_fingerprint(design)
    assert bare != coated
    design.nanoparticles[0].visible = False
    design.nanoparticles[0].coating.protein.name = 'Renamed reference'
    assert design_build_fingerprint(design) == coated
    for build in [build_namd_package, build_openmm_topology, lambda d: write_topology(d, tmp_path/'out.top')]:
        with pytest.raises(ValueError, match='not simulation-ready'):
            build(design)
    assert not (tmp_path/'out.top').exists()
    require_coating_simulation_support(Design(), 'test')
    state.set_design(design)
    audit = client.get('/api/design/nanoparticles/coating-simulation-audit').json()
    assert audit['tetramers'] == 7 and audit['simulation_ready'] is False
    assert {'NAMD', 'OpenMM', 'oxDNA/DNANM', 'mrDNA', 'CanDo', 'SNUPI'} <= set(audit['engines'])


def test_custom_qd_coating_roundtrip():
    result = client.post('/api/design/nanoparticles/quantum-dots', json={'catalog_id': 'nn-hecz-520', 'diameter_nm': 9})
    assert result.status_code == 201
    pid = result.json()['nanoparticle_id']
    result = client.patch(f'/api/design/nanoparticles/{pid}', json={'coating': {'mode': 'biotin_tether'}})
    assert result.status_code == 200, result.text
    restored = Design.model_validate_json(state.get_design().model_dump_json())
    assert restored.nanoparticles[0].coating.protein.metadata['pdb_id'] == '1STP'
    assert len(restored.nanoparticles[0].coating.poses) > 0


def test_publication_count_and_override_persist_through_resize():
    response = client.post('/api/design/nanoparticles/gold-nanospheres', json={'diameter_nm': 10})
    pid = state.get_design().nanoparticles[0].id
    url = f'/api/design/nanoparticles/{pid}'
    assert client.patch(url, json={'coating': {'coverage_reference': 'gurtovenko_2019'}}).status_code == 200
    c = state.get_design().nanoparticles[0].coating
    assert c.target_count == 6
    assert c.coverage_reference == 'gurtovenko_2019'
    assert c.source.endswith('acs.jpclett.9b00065')
    assert client.patch(url, json={'diameter_nm': 20}).status_code == 200
    assert state.get_design().nanoparticles[0].coating.target_count == 25
    assert client.patch(url, json={'coating': {'coverage_reference': 'gurtovenko_2019', 'count_override': 4}}).status_code == 200
    assert client.patch(url, json={'diameter_nm': 10}).status_code == 200
    c = state.get_design().nanoparticles[0].coating
    assert c.target_count == len(c.poses) == c.count_override == 4
    assert client.patch(url, json={'coating': {'count_override': 1.5}}).status_code == 422
    assert client.patch(url, json={'coating': {'coverage_reference': 'unknown'}}).status_code == 422


def test_dense_publication_target_is_not_limited_by_legacy_footprint():
    assert build_streptavidin_coating(14.1, coverage_reference='gold_2017').target_count == 30
