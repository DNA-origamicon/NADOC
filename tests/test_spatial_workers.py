import threading
from types import SimpleNamespace

import numpy as np

from backend.core.spatial_workers import spatial_workers


def test_worker_policy_is_evaluated_at_query_time(monkeypatch):
    monkeypatch.delenv('NADOC_PRECOMPUTE_WORKER', raising=False)
    assert spatial_workers() == -1
    monkeypatch.setenv('NADOC_PRECOMPUTE_WORKER', '1')
    assert spatial_workers() == 1


def test_background_surface_preserves_mesh_without_starting_threads(monkeypatch):
    from backend.core import surface

    atoms = [SimpleNamespace(x=x, y=0., z=0., element='C',
                             strand_id=f's{i}', helix_id='h', bp_index=i,
                             direction='FORWARD')
             for i, x in enumerate([0., .4])]
    monkeypatch.delenv('NADOC_PRECOMPUTE_WORKER', raising=False)
    expected = surface.compute_surface(atoms, probe_radius=0)

    def forbidden(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setenv('NADOC_PRECOMPUTE_WORKER', '1')
    monkeypatch.setattr(threading.Thread, 'start', forbidden)
    actual = surface.compute_surface(atoms, probe_radius=0)
    np.testing.assert_array_equal(actual.vertices, expected.vertices)
    np.testing.assert_array_equal(actual.faces, expected.faces)
    assert actual.vertex_strand_ids == expected.vertex_strand_ids
    assert actual.vertex_nuc_ids == expected.vertex_nuc_ids

    # The point-cloud surface path must obey the same policy.
    cloud = surface.compute_surface_from_cloud(
        np.array([[a.x, a.y, a.z] for a in atoms]),
        np.array([.17, .17]), ['s0', 's1'], probe_radius=0)
    assert len(cloud.vertices) > 0
