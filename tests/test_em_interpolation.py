"""Display interpolation must retain point values even in tiny adaptive cells."""
import copy
import numpy as np
from backend.rendering.em_interpolation import with_display_tetrahedra


def test_adaptive_connectivity_keeps_tiny_hotspot_and_source_values():
    points = [[x, y, z] for x in (-10, 10) for y in (-10, 10) for z in (-10, 10)]
    points += [[0, 0, 0], [.001, 0, 0], [0, .001, 0], [0, 0, .001]]
    source = dict(sampling={'layout': 'octree'}, sample_positions_nm=points,
                  intensity=[1]*8+[100, 1, 1, 1], outside=[True]*12)
    before = copy.deepcopy(source)
    result = with_display_tetrahedra(source)
    assert source == before
    assert result['intensity'] is source['intensity']
    cells = np.asarray(result['display_tetrahedra'])
    assert set(cells.ravel()) == set(range(12))
    vertices = np.asarray(points)[cells]
    assert np.all(np.linalg.det(vertices[:, 1:] - vertices[:, :1]) != 0)
    # Barycentric interpolation at each original vertex reproduces its value.
    for cell in cells:
        p = np.asarray(points)[cell]
        weights = np.linalg.solve(np.vstack((p.T, np.ones(4))), np.r_[points[cell[0]], 1])
        assert np.isclose(weights @ np.asarray(source['intensity'])[cell], source['intensity'][cell[0]])


def test_uniform_result_is_unchanged():
    source = {'sampling': {'layout': 'uniform'}}
    assert with_display_tetrahedra(source) is source


def test_trajectory_response_adds_connectivity_without_mutating_archive(monkeypatch):
    import json
    from backend.api import em_trajectory_jobs
    source = dict(sampling={'layout': 'octree'}, sample_positions_nm=np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float),
        intensity=np.array([100., 1., 1., 1.]), outside=np.ones(4, dtype=bool))
    monkeypatch.setattr(em_trajectory_jobs, 'read_frame', lambda path, ordinal: source)
    result = json.loads(em_trajectory_jobs.encode_frame('unused', 0))
    assert sorted(result['display_tetrahedra'][0]) == [0, 1, 2, 3]
    assert result['intensity'] == [100., 1., 1., 1.]
    assert 'display_tetrahedra' not in source
