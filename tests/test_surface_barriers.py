"""Engine-free checks for plane adapters, coating registration and periodic cells."""
from copy import deepcopy

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.surface_transforms import RigidTransform, surface_frame, transform_surface
from backend.core.surface_periodic import unwrap_chains, unwrap_connected, surface_aligned_cell
from backend.core.graphene_cell_frame import transform_pdb_coordinates, namd_cell_basis
from backend.core.namd_graphene import tile_graphene_to_cell
from backend.core.namd_solvate import _graphene_pdb_atoms, _hetatm_record
from backend.physics.oxdna_surface_geometry import resolved_wall, persisted_wall, same_plane
from backend.core.constants import NM_TO_OXDNA


def test_chain_unwrap_uses_registered_grafts_not_chain_centroids():
    wrapped = [[.1, 2, 3], [9.8, 2, 3], [9.5, 2, 3], [8, 4, 3], [8.2, 4, 3]]
    before = deepcopy(wrapped)
    whole = unwrap_chains(wrapped, [[0, 1, 2], [3, 4]], [10, 10, 10],
                          graft_sites_nm=[[10.1, 2, 3], [-2, 4, 3]])
    assert np.allclose(whole[:, 0], [10.1, 9.8, 9.5, -2, -1.8])
    assert wrapped == before
    transform = RigidTransform(translation_nm=[20, 30, 40])
    assert np.allclose(np.diff(transform.points(whole[:3]), axis=0), np.diff(whole[:3], axis=0))


@pytest.mark.parametrize('chains,box,points', [([[0], [0]], [10]*3, [[0]*3]),
    ([[0, 1]], [0, 10, 10], [[0]*3, [1]*3]),
    ([[0, 1]], [10]*3, [[0]*3, [5, 0, 0]])])
def test_invalid_or_ambiguous_periodic_inputs(chains, box, points):
    with pytest.raises(ValueError):
        unwrap_chains(points, chains, box)


def test_connected_cycle_and_root_image():
    whole = unwrap_connected([[9.8, 0, 0], [.1, 0, 0], [.2, 0, 0]],
                             [(0, 1), (1, 2), (0, 2)], [10]*3)
    assert np.allclose(whole[:, 0], [9.8, 10.1, 10.2])
    with pytest.raises(ValueError, match='winds'):
        unwrap_connected([[0, 0, 0], [4, 0, 0], [8, 0, 0]],
                         [(0, 1), (1, 2), (2, 0)], [10]*3)


def test_oblique_wall_writer_and_persistence(tmp_path, monkeypatch):
    from backend.physics import oxdna_interface as interface
    wall = {'dir': [1, 1, 0], 'plane_point_nm': [3, 1, 0], 'stiff': 5}
    cm = [[5, 5, 0], [6, 6, 1]]
    resolved = resolved_wall(wall, cm)
    assert resolved['position'] == pytest.approx(-4 / np.sqrt(2) * NM_TO_OXDNA)
    assert same_plane(wall, persisted_wall(wall, resolved))
    assert 'position_nm' not in persisted_wall(wall, resolved)
    conf = tmp_path / 'conf.dat'
    conf.write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n' +
                    '\n'.join(' '.join(map(str, p)) + ' 1 0 0 0 0 1 0 0 0 0 0 0' for p in cm) + '\n')
    monkeypatch.setattr(interface, 'resolve_anchor_particles', lambda *_: ([], []))
    force = tmp_path / 'forces.txt'
    result = interface.write_run_forces(force, object(), conf, wall=wall)
    assert result['wall']['position'] == pytest.approx(resolved['position'])
    assert 'repulsion_plane' in force.read_text()
    assert result['wall']['plane_point_nm'] == [3, 1, 0]


def test_oblique_setup_api_carries_plane_and_tangent():
    from backend.api.main import app
    payload = {'surface': {'dir': [2**-.5, 0, 2**-.5], 'plane_point_nm': [1, 2, 3],
                           'tangent_u': [0, 1, 0]}, 'surface_strands': {}}
    response = TestClient(app).post('/api/oxdna/peg/setup', json=payload)
    assert response.status_code == 200, response.text
    surface = response.json()['job_request_fragment']['surface']
    assert surface['plane_point_nm'] == [1, 2, 3]
    assert surface['tangent_u'] == [0, 1, 0]
    payload['surface'] = {'dir': [2**-.5, 0, 2**-.5], 'position_nm': 3}
    assert TestClient(app).post('/api/oxdna/peg/setup', json=payload).status_code == 422


def test_clearance_moves_coating_with_graphene_and_updates_axis_position():
    spec = {'dir': [0, 0, 1], 'position_nm': 0., 'plane_point_nm': [0, 0, 0],
            'pore_center_nm': [0, 0, 0], 'graft_sites_nm': [[2, 0, 0]],
            'peg_positions_nm': [[2, 0, .7]], 'atomistic_clearance_nm': .32}
    pdb = _hetatm_record(1, 'C', 'DNA', 'A', 1, 0, 0, 1, segname='DNA')
    _graphene_pdb_atoms(pdb.replace('HETATM', 'ATOM  '), spec)
    assert spec['atomistic_clearance_shift_nm'] == pytest.approx(.22)
    assert spec['position_nm'] == pytest.approx(-.22)
    assert np.allclose(spec['graft_sites_nm'], [[2, 0, -.22]])
    assert np.allclose(spec['peg_positions_nm'], [[2, 0, .48]])
    assert surface_frame(spec).signed_distance(spec['graft_sites_nm'])[0] == pytest.approx(0)


def test_surface_aligned_reboxing_preserves_all_registered_distances():
    points = np.array([[5, 6, 7], [1, 4, 8]])
    spec = {'dir': [1, 1, 1], 'plane_point_nm': [0, 0, 0],
            'graft_sites_nm': [[2, -2, 0]], 'peg_positions_nm': [[3, -1, 1]]}
    before = deepcopy(spec)
    cell = surface_aligned_cell(points, spec, padding_nm=2)
    assert np.allclose(cell['surface']['dir'], [0, 0, 1])
    assert np.all(cell['points_nm'] >= 2 - 1e-10)
    assert np.all(cell['points_nm'] <= cell['box_nm'] - 2 + 1e-10)
    assert np.allclose(cell['inverse'].points(cell['points_nm']), points)
    assert np.allclose(surface_frame(cell['surface']).signed_distance(cell['points_nm']),
                       surface_frame(spec).signed_distance(points))
    assert spec == before


def test_oblique_graphene_tiles_in_matching_periodic_cell():
    angle = .41
    rotation = RigidTransform([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                               [-np.sin(angle), 0, np.cos(angle)]])
    base = {'dir': [0, 0, 1], 'plane_point_nm': [0, 0, 2], 'position_nm': 2,
            'pore_center_nm': [2, 2, 2], 'pore_diameter_nm': 1,
            '_first_site_nm': [0, 0, 2], 'graft_sites_nm': [[1, 1, 2]]}
    pdb = _hetatm_record(1, 'C', 'GRP', 'G', 1, 0, 0, 20, segname='GR00') + '\nEND\n'
    box = np.array([4, 4, 6])
    expected = tile_graphene_to_cell(pdb, box, deepcopy(base))
    spec = transform_surface(base, rotation)
    spec['_first_site_nm'] = rotation.points(base['_first_site_nm']).tolist()
    vectors = np.diag(box) @ np.asarray(rotation.rotation).T
    tiled = tile_graphene_to_cell(transform_pdb_coordinates(pdb, rotation), box, spec,
                                  cell_vectors_nm=vectors)
    def coords(text):
        return np.array([[float(line[i:i+8]) / 10 for i in (30, 38, 46)]
                         for line in text.splitlines() if line.startswith('HETATM')])
    assert np.allclose(coords(tiled), rotation.points(coords(expected)), atol=2e-4)
    assert 'position_nm' not in spec
    assert np.allclose(spec['graft_sites_nm'], rotation.points([[1, 1, 2]]), atol=2e-4)
    assert 'cellBasisVector3' in namd_cell_basis(spec)
    assert np.allclose(spec['periodic_cell_vectors_nm'], vectors)
    # An oblique plane in the original axis-aligned box cannot tile periodically.
    with pytest.raises(ValueError, match='Cartesian'):
        tile_graphene_to_cell(transform_pdb_coordinates(pdb, rotation), box,
                              transform_surface(base, rotation))


def test_peg_builder_preserves_patch_frame_under_rigid_transform():
    from backend.physics.oxdna_surface_strands import CaptureSpec, build_capture_strands
    spec = CaptureSpec.from_payload({'material': 'PEG', 'segments': 2, 'enabled': True,
                                    'shape': 'square', 'sizeNm': 2, 'densityPerUm2': 1000000,
                                    'offsetXNm': .5, 'offsetYNm': -.2})
    cm = np.array([[0., 0., 10.], [1., 0., 10.]]) * NM_TO_OXDNA
    surface = resolved_wall({'dir': [0, 0, 1], 'position_nm': 0}, cm)
    angle = .31
    rotate = RigidTransform([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)],
                              [0, np.sin(angle), np.cos(angle)]], [1, 2, 3])
    def build(cm, wall):
        result = build_capture_strands(spec, origami_cm_oxdna=cm.tolist(),
                                       n_particles_origami=2, n_strands_origami=1, surface=wall)
        return np.array([[float(v) for v in line.split()[:3]] for line in result.conf_lines]) / NM_TO_OXDNA
    before = build(cm, surface)
    after = build(rotate.points(cm / NM_TO_OXDNA) * NM_TO_OXDNA, transform_surface(surface, rotate))
    assert np.allclose(after, rotate.points(before), atol=2e-6)


def test_transform_invalidates_engine_scalars_and_moves_periodic_frame():
    spec = {'dir': [0, 0, 1], 'position_nm': 3, 'position': -9, 'min_proj': 5,
            'periodic_cell_vectors_nm': np.diag([10, 12, 14]).tolist(),
            'periodic_cell_origin_nm': [0, 0, 0]}
    transform = RigidTransform([[0, -1, 0], [1, 0, 0], [0, 0, 1]], [2, 3, 4])
    moved = transform_surface(spec, transform)
    assert 'position' not in moved and 'min_proj' not in moved
    assert moved['periodic_cell_origin_nm'] == [2, 3, 4]
    assert np.allclose(moved['periodic_cell_vectors_nm'], [[0, 10, 0], [-12, 0, 0], [0, 0, 14]])


def test_deposition_freezes_offset_plane_before_moving_probe(tmp_path, monkeypatch):
    from backend.physics.oxdna_surface_geometry import absolute_wall_for_configuration
    from backend.physics import oxdna_interface as interface
    conf = tmp_path / 'conf.dat'
    conf.write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n2 2 5 1 0 0 0 0 1 0 0 0 0 0 0\n')
    monkeypatch.setattr(interface, 'resolve_anchor_particles', lambda *_: ([0], []))
    wall = absolute_wall_for_configuration({'dir': [0, 0, 1], 'offset_nm': 1, 'stiff': 5}, conf)
    position = resolved_wall(wall, [])['position']
    interface.place_configuration_against_surface(conf, object(), wall=wall, anchors=[{}])
    after = interface.read_cm_positions_oxdna(conf)
    assert resolved_wall(wall, after)['position'] == position
    assert resolved_wall({'dir': [0, 0, 1], 'offset_nm': 1}, after)['position'] != pytest.approx(position)


def test_graphene_honors_explicit_plane_without_pore_center():
    spec = {'dir': [0, 0, 1], 'plane_point_nm': [0, 0, -2]}
    pdb = _hetatm_record(1, 'C', 'DNA', 'A', 1, 10, 20, 30, segname='DNA').replace('HETATM', 'ATOM  ')
    _graphene_pdb_atoms(pdb, spec)
    assert np.allclose(spec['pore_center_nm'], [1, 2, -2])
    assert spec['position_nm'] == -2
    assert spec['atomistic_clearance_shift_nm'] == 0
